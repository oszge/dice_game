from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
import streamlit as st
from argon2 import PasswordHasher 
from argon2.exceptions import InvalidHashError, VerifyMismatchError  
from psycopg.rows import dict_row  
from sqlalchemy import create_engine, text


_PASSWORD_HASHER = PasswordHasher()
_MATCHMAKING_LOCK_KEY = 4_204_206_071_626


class GameError(Exception):
    """A user-facing game or validation error."""


def _database_url() -> str:
    """Return DATABASE_URL from Streamlit secrets or the environment."""
    try:
        url = st.secrets.get("DATABASE_URL")
    except (FileNotFoundError, KeyError):
        url = None

    url = url or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is missing. Add it to .streamlit/secrets.toml "
            "or set it as an environment variable."
        )
    return str(url)


def _connect() -> psycopg.Connection:
    return psycopg.connect(
        _database_url(),
        row_factory=dict_row,
        connect_timeout=10,
    )


@st.cache_resource
def _sqlalchemy_engine():
    url = _database_url()
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url, pool_pre_ping=True)


def init_db() -> None:
    """Create the tables when the app starts.

    schema.sql contains only simple CREATE statements, so running the complete
    file as a non-prepared command is safe here.
    """
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(schema, prepare=False)


def _normalize(value: str) -> str:
    return value.strip()


def register_player(username: str, nickname: str, password: str) -> int:
    username = _normalize(username)
    nickname = _normalize(nickname)

    if len(username) < 3:
        raise GameError("Username must contain at least 3 characters.")
    if len(nickname) < 2:
        raise GameError("Nickname must contain at least 2 characters.")
    if len(password) < 8:
        raise GameError("Password must contain at least 8 characters.")

    password_hash = _PASSWORD_HASHER.hash(password)

    try:
        with _connect() as conn:
            row = conn.execute(
                """
                INSERT INTO player (nickname, username, password)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (nickname, username, password_hash),
            ).fetchone()
            return int(row["id"])
    except psycopg.errors.UniqueViolation as exc:
        raise GameError("That username or nickname is already registered.") from exc


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    with _connect() as conn:
        player = conn.execute(
            """
            SELECT id, nickname, username, password, matches_won
            FROM player
            WHERE LOWER(username) = LOWER(%s)
            """,
            (_normalize(username),),
        ).fetchone()

    if not player:
        return None

    try:
        _PASSWORD_HASHER.verify(player["password"], password)
    except (VerifyMismatchError, InvalidHashError):
        return None

    # Upgrade old Argon2 parameters after a successful login when necessary.
    if _PASSWORD_HASHER.check_needs_rehash(player["password"]):
        new_hash = _PASSWORD_HASHER.hash(password)
        with _connect() as conn:
            conn.execute(
                "UPDATE player SET password = %s WHERE id = %s",
                (new_hash, player["id"]),
            )

    player.pop("password", None)
    return player


def get_player(player_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT id, nickname, username, matches_won
            FROM player
            WHERE id = %s
            """,
            (player_id,),
        ).fetchone()


def _find_open_match(cur: psycopg.Cursor, player_id: int) -> dict[str, Any] | None:
    return cur.execute(
        """
        SELECT *
        FROM "match"
        WHERE (player1_id = %s OR player2_id = %s)
          AND status IN ('active', 'awaiting_rematch')
        ORDER BY id DESC
        LIMIT 1
        """,
        (player_id, player_id),
    ).fetchone()


def get_open_match_id(player_id: int) -> int | None:
    with _connect() as conn:
        row = _find_open_match(conn.cursor(), player_id)
    return int(row["id"]) if row else None


def is_queued(player_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM game_queue WHERE player_id = %s",
            (player_id,),
        ).fetchone()
    return row is not None


def join_queue(player_id: int) -> int | None:
    """Join the queue and atomically match with the oldest waiting opponent."""
    with _connect() as conn:
        with conn.transaction():
            cur = conn.cursor()

            # Serializes the short matchmaking section across app sessions.
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_MATCHMAKING_LOCK_KEY,))

            if _find_open_match(cur, player_id):
                raise GameError("You are already in an active match.")

            cur.execute(
                """
                INSERT INTO game_queue (player_id)
                VALUES (%s)
                ON CONFLICT (player_id) DO NOTHING
                """,
                (player_id,),
            )

            opponent = cur.execute(
                """
                SELECT q.player_id
                FROM game_queue AS q
                WHERE q.player_id <> %s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM "match" AS m
                      WHERE (m.player1_id = q.player_id OR m.player2_id = q.player_id)
                        AND m.status IN ('active', 'awaiting_rematch')
                  )
                ORDER BY q.joined_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                (player_id,),
            ).fetchone()

            if not opponent:
                return None

            opponent_id = int(opponent["player_id"])
            match = cur.execute(
                """
                INSERT INTO "match" (player1_id, player2_id)
                VALUES (%s, %s)
                RETURNING id
                """,
                (opponent_id, player_id),
            ).fetchone()
            match_id = int(match["id"])

            cur.execute(
                """
                INSERT INTO match_round (match_id, round_number)
                VALUES (%s, 1)
                """,
                (match_id,),
            )
            cur.execute(
                "DELETE FROM game_queue WHERE player_id IN (%s, %s)",
                (opponent_id, player_id),
            )
            return match_id


def leave_queue(player_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM game_queue WHERE player_id = %s", (player_id,))


def get_match(match_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        match = conn.execute(
            """
            SELECT
                m.*,
                p1.nickname AS player1_nickname,
                p2.nickname AS player2_nickname
            FROM "match" AS m
            JOIN player AS p1 ON p1.id = m.player1_id
            JOIN player AS p2 ON p2.id = m.player2_id
            WHERE m.id = %s
            """,
            (match_id,),
        ).fetchone()

        if not match:
            return None

        rounds = conn.execute(
            """
            SELECT round_number, player1_roll, player2_roll,
                   round_winner_player_id, resolved_at
            FROM match_round
            WHERE match_id = %s
            ORDER BY round_number
            """,
            (match_id,),
        ).fetchall()

    match["rounds"] = rounds
    return match


def roll_dice(match_id: int, player_id: int) -> int:
    """Save one player's roll and resolve the round after both have rolled."""
    rolled_value = secrets.randbelow(6) + 1

    with _connect() as conn:
        with conn.transaction():
            cur = conn.cursor()
            match = cur.execute(
                'SELECT * FROM "match" WHERE id = %s FOR UPDATE',
                (match_id,),
            ).fetchone()

            if not match or match["status"] != "active":
                raise GameError("This match is no longer active.")
            if player_id not in (match["player1_id"], match["player2_id"]):
                raise GameError("You are not a player in this match.")

            round_no = int(match["current_round"])
            round_row = cur.execute(
                """
                SELECT * FROM match_round
                WHERE match_id = %s AND round_number = %s
                FOR UPDATE
                """,
                (match_id, round_no),
            ).fetchone()

            is_player1 = player_id == match["player1_id"]
            roll_column = "player1_roll" if is_player1 else "player2_roll"
            if round_row[roll_column] is not None:
                raise GameError("You have already rolled in this round.")

            # The column name is selected only from the two constants above.
            cur.execute(
                f"""
                UPDATE match_round
                SET {roll_column} = %s
                WHERE match_id = %s AND round_number = %s
                """,
                (rolled_value, match_id, round_no),
            )

            round_row = cur.execute(
                """
                SELECT * FROM match_round
                WHERE match_id = %s AND round_number = %s
                """,
                (match_id, round_no),
            ).fetchone()

            p1_roll = round_row["player1_roll"]
            p2_roll = round_row["player2_roll"]
            if p1_roll is None or p2_roll is None:
                return rolled_value

            round_winner_id = None
            p1_score_add = 0
            p2_score_add = 0
            if p1_roll > p2_roll:
                round_winner_id = match["player1_id"]
                p1_score_add = 1
            elif p2_roll > p1_roll:
                round_winner_id = match["player2_id"]
                p2_score_add = 1

            cur.execute(
                """
                UPDATE match_round
                SET round_winner_player_id = %s, resolved_at = NOW()
                WHERE match_id = %s AND round_number = %s
                """,
                (round_winner_id, match_id, round_no),
            )

            new_p1_score = int(match["player1_name_score"]) + p1_score_add
            new_p2_score = int(match["player2_name_score"]) + p2_score_add

            if round_no < 5:
                cur.execute(
                    """
                    UPDATE "match"
                    SET player1_name_score = %s,
                        player2_name_score = %s,
                        current_round = current_round + 1
                    WHERE id = %s
                    """,
                    (new_p1_score, new_p2_score, match_id),
                )
                cur.execute(
                    """
                    INSERT INTO match_round (match_id, round_number)
                    VALUES (%s, %s)
                    """,
                    (match_id, round_no + 1),
                )
                return rolled_value

            winner_id = None
            winner_name = None
            if new_p1_score > new_p2_score:
                winner_id = int(match["player1_id"])
            elif new_p2_score > new_p1_score:
                winner_id = int(match["player2_id"])

            if winner_id is not None:
                winner = cur.execute(
                    "SELECT nickname FROM player WHERE id = %s",
                    (winner_id,),
                ).fetchone()
                winner_name = winner["nickname"]
                cur.execute(
                    "UPDATE player SET matches_won = matches_won + 1 WHERE id = %s",
                    (winner_id,),
                )

            cur.execute(
                """
                UPDATE "match"
                SET player1_name_score = %s,
                    player2_name_score = %s,
                    winner_player_name = %s,
                    status = 'awaiting_rematch',
                    finished_at = NOW()
                WHERE id = %s
                """,
                (new_p1_score, new_p2_score, winner_name, match_id),
            )
            return rolled_value


def vote_rematch(match_id: int, player_id: int, accept: bool) -> int | None:
    """Store a vote; return the new match ID when both players accept."""
    with _connect() as conn:
        with conn.transaction():
            cur = conn.cursor()
            match = cur.execute(
                'SELECT * FROM "match" WHERE id = %s FOR UPDATE',
                (match_id,),
            ).fetchone()

            if not match:
                raise GameError("Match not found.")
            if match["status"] == "rematched":
                return match["rematch_match_id"]
            if match["status"] == "closed":
                return None
            if match["status"] != "awaiting_rematch":
                raise GameError("Rematch voting is not available yet.")
            if player_id not in (match["player1_id"], match["player2_id"]):
                raise GameError("You are not a player in this match.")

            vote_column = (
                "player1_rematch"
                if player_id == match["player1_id"]
                else "player2_rematch"
            )
            cur.execute(
                f'UPDATE "match" SET {vote_column} = %s WHERE id = %s',
                (accept, match_id),
            )

            updated = cur.execute(
                'SELECT * FROM "match" WHERE id = %s',
                (match_id,),
            ).fetchone()
            p1_vote = updated["player1_rematch"]
            p2_vote = updated["player2_rematch"]

            if p1_vote is True and p2_vote is True:
                new_match = cur.execute(
                    """
                    INSERT INTO "match" (player1_id, player2_id)
                    VALUES (%s, %s)
                    RETURNING id
                    """,
                    (updated["player1_id"], updated["player2_id"]),
                ).fetchone()
                new_match_id = int(new_match["id"])
                cur.execute(
                    "INSERT INTO match_round (match_id, round_number) VALUES (%s, 1)",
                    (new_match_id,),
                )
                cur.execute(
                    """
                    UPDATE "match"
                    SET status = 'rematched', rematch_match_id = %s
                    WHERE id = %s
                    """,
                    (new_match_id, match_id),
                )
                return new_match_id

            if p1_vote is False and p2_vote is False:
                cur.execute(
                    'UPDATE "match" SET status = \'closed\' WHERE id = %s',
                    (match_id,),
                )

            return None


def leaderboard() -> pd.DataFrame:
    query = text(
        """
        SELECT
            DENSE_RANK() OVER (ORDER BY matches_won DESC) AS rank,
            nickname,
            matches_won
        FROM player
        ORDER BY matches_won DESC, LOWER(nickname)
        LIMIT 20
        """
    )
    return pd.read_sql_query(query, _sqlalchemy_engine())


def recent_matches(player_id: int) -> pd.DataFrame:
    query = text(
        """
        SELECT
            m.id AS match_id,
            p1.nickname AS player_1,
            m.player1_name_score AS score_1,
            p2.nickname AS player_2,
            m.player2_name_score AS score_2,
            COALESCE(m.winner_player_name, 'Draw') AS winner,
            m.finished_at
        FROM "match" AS m
        JOIN player AS p1 ON p1.id = m.player1_id
        JOIN player AS p2 ON p2.id = m.player2_id
        WHERE (m.player1_id = :player_id OR m.player2_id = :player_id)
          AND m.finished_at IS NOT NULL
        ORDER BY m.finished_at DESC
        LIMIT 10
        """
    )
    return pd.read_sql_query(
        query,
        _sqlalchemy_engine(),
        params={"player_id": player_id},
    )
