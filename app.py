from __future__ import annotations

import pandas as pd
import streamlit as st

import db


st.set_page_config(page_title="Neon Dice Arena", page_icon="🎲", layout="wide")

DICE = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}


def initialize_session() -> None:
    st.session_state.setdefault("player_id", None)


def login_player(player: dict) -> None:
    st.session_state.player_id = int(player["id"])
    st.rerun()


def logout() -> None:
    if st.session_state.player_id:
        db.leave_queue(int(st.session_state.player_id))
    st.session_state.player_id = None
    st.rerun()


def show_authentication() -> None:
    st.title("🎲 Neon Dice Arena")
    st.caption("Register or sign in, then find another online player.")

    login_tab, register_tab = st.tabs(["Sign in", "Register"])

    with login_tab:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", use_container_width=True)

        if submitted:
            player = db.authenticate(username, password)
            if player:
                login_player(player)
            else:
                st.error("Incorrect username or password.")

    with register_tab:
        with st.form("register_form"):
            nickname = st.text_input("Game nickname")
            username = st.text_input("Username", key="register_username")
            password = st.text_input(
                "Password (minimum 8 characters)",
                type="password",
                key="register_password",
            )
            confirm_password = st.text_input(
                "Confirm password", type="password"
            )
            submitted = st.form_submit_button("Create account", use_container_width=True)

        if submitted:
            if password != confirm_password:
                st.error("The passwords do not match.")
            else:
                try:
                    player_id = db.register_player(username, nickname, password)
                    player = db.get_player(player_id)
                    st.success("Registration successful.")
                    login_player(player)
                except db.GameError as exc:
                    st.error(str(exc))


def round_history_dataframe(match: dict) -> pd.DataFrame:
    records = []
    for row in match["rounds"]:
        if row["player1_roll"] is None and row["player2_roll"] is None:
            continue

        if row["round_winner_player_id"] == match["player1_id"]:
            result = match["player1_nickname"]
        elif row["round_winner_player_id"] == match["player2_id"]:
            result = match["player2_nickname"]
        elif row["resolved_at"] is not None:
            result = "Tie"
        else:
            result = "Waiting"

        records.append(
            {
                "Round": row["round_number"],
                match["player1_nickname"]: (
                    DICE.get(row["player1_roll"], "Waiting")
                ),
                match["player2_nickname"]: (
                    DICE.get(row["player2_roll"], "Waiting")
                ),
                "Round winner": result,
            }
        )
    return pd.DataFrame(records)


def render_active_match(match: dict, player_id: int) -> None:
    p1_name = match["player1_nickname"]
    p2_name = match["player2_nickname"]

    st.subheader(f"{p1_name} vs. {p2_name}")
    score1, round_metric, score2 = st.columns(3)
    score1.metric(p1_name, match["player1_name_score"])
    round_metric.metric("Round", f'{match["current_round"]} / 5')
    score2.metric(p2_name, match["player2_name_score"])

    current = next(
        row
        for row in match["rounds"]
        if row["round_number"] == match["current_round"]
    )
    is_player1 = player_id == match["player1_id"]
    own_roll = current["player1_roll"] if is_player1 else current["player2_roll"]
    opponent_roll = current["player2_roll"] if is_player1 else current["player1_roll"]

    left, right = st.columns(2)
    with left:
        st.markdown("#### Your roll")
        st.markdown(f"# {DICE.get(own_roll, '—')}")
    with right:
        st.markdown("#### Opponent")
        st.markdown("# ✅" if opponent_roll is not None else "# …")

    if own_roll is None:
        if st.button("🎲 Roll dice", type="primary", use_container_width=True):
            try:
                rolled = db.roll_dice(int(match["id"]), player_id)
                st.toast(f"You rolled {rolled} {DICE[rolled]}")
                st.rerun(scope="fragment")
            except db.GameError as exc:
                st.error(str(exc))
    else:
        st.info("Your roll is saved. Waiting for the other player.")

    history = round_history_dataframe(match)
    if not history.empty:
        st.markdown("#### Round history")
        st.dataframe(history, hide_index=True, use_container_width=True)



def vote_label(value: bool | None) -> str:
    if value is True:
        return "Accepted"
    if value is False:
        return "Rejected"
    return "Waiting"


def render_rematch(match: dict, player_id: int) -> None:
    st.subheader("Match finished")
    p1 = match["player1_nickname"]
    p2 = match["player2_nickname"]
    st.markdown(
        f"### {p1} {match['player1_name_score']} – "
        f"{match['player2_name_score']} {p2}"
    )

    if match["winner_player_name"]:
        st.success(f"Winner: {match['winner_player_name']} 🏆")
    else:
        st.info("The match ended in a draw. No win was added.")

    history = round_history_dataframe(match)
    st.dataframe(history, hide_index=True, use_container_width=True)

    my_vote = (
        match["player1_rematch"]
        if player_id == match["player1_id"]
        else match["player2_rematch"]
    )
    other_vote = (
        match["player2_rematch"]
        if player_id == match["player1_id"]
        else match["player1_rematch"]
    )

    st.caption(
        f"Your vote: {vote_label(my_vote)} · "
        f"Opponent: {vote_label(other_vote)}"
    )
    st.write(
        "Both players must accept within 2 minutes to start a rematch. "
        "If both players do not accept before the timeout, the match closes "
        "automatically and returns to the main menu."
    )

    accept_col, reject_col = st.columns(2)
    with accept_col:
        if st.button("Accept rematch", type="primary", use_container_width=True):
            try:
                db.vote_rematch(int(match["id"]), player_id, True)
                st.rerun(scope="fragment")
            except db.GameError as exc:
                st.error(str(exc))
    with reject_col:
        if st.button("Reject rematch", use_container_width=True):
            try:
                db.vote_rematch(int(match["id"]), player_id, False)
                st.rerun(scope="fragment")
            except db.GameError as exc:
                st.error(str(exc))


@st.fragment(run_every="2s")
def live_area(player_id: int) -> None:
    match = db.get_open_match(player_id)

    if match:
        if match["status"] == "active":
            render_active_match(match, player_id)

        elif match["status"] == "awaiting_rematch":
            render_rematch(match, player_id)

        return

    st.subheader("Find an opponent")

    if db.is_queued(player_id):
        st.info(
            "You are in the matchmaking queue. "
            "Looking for another player…"
        )

        if st.button("Leave queue", use_container_width=True):
            db.leave_queue(player_id)
            st.rerun(scope="fragment")

    else:
        if st.button(
            "Join matchmaking queue",
            type="primary",
            use_container_width=True,
        ):
            try:
                match_id = db.join_queue(player_id)

                if match_id:
                    st.toast(
                        "Opponent found. The match is starting!"
                    )

                st.rerun(scope="fragment")

            except db.GameError as exc:
                st.error(str(exc))

    st.divider()

    leaderboard_col, recent_col = st.columns(2)

    with leaderboard_col:
        st.markdown("#### Leaderboard")
        st.dataframe(
            db.leaderboard(),
            hide_index=True,
            use_container_width=True,
        )

    with recent_col:
        st.markdown("#### Your recent matches")
        recent = db.recent_matches(player_id)

        if recent.empty:
            st.caption("No completed matches yet.")
        else:
            st.dataframe(
                recent,
                hide_index=True,
                use_container_width=True,
            )

def show_main_page() -> None:
    player_id = int(st.session_state.player_id)
    player = db.get_player(player_id)
    if not player:
        st.session_state.player_id = None
        st.rerun()

    with st.sidebar:
        st.header(f"🎲 {player['nickname']}")
        st.write(f"Username: `{player['username']}`")
        st.metric("Matches won", player["matches_won"])
        if st.button("Sign out", use_container_width=True):
            logout()

    st.title("Neon Dice Arena")
    live_area(player_id)


def main() -> None:
    initialize_session()
    try:
        db.init_db()
    except Exception as exc:
        st.error(f"Database initialization failed: {exc}")
        st.stop()

    if st.session_state.player_id is None:
        show_authentication()
    else:
        show_main_page()


if __name__ == "__main__":
    main()
