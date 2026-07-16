-- Run this file once in the Neon SQL Editor.

CREATE TABLE IF NOT EXISTS player (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nickname VARCHAR(40) NOT NULL,
    username VARCHAR(50) NOT NULL,
    -- Stores an Argon2 password hash, never the plain-text password.
    password TEXT NOT NULL,
    matches_won INTEGER NOT NULL DEFAULT 0 CHECK (matches_won >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_player_username_ci
    ON player ((LOWER(username)));

CREATE UNIQUE INDEX IF NOT EXISTS uq_player_nickname_ci
    ON player ((LOWER(nickname)));

-- Quoted because MATCH is an SQL keyword in some SQL contexts.
-- player1_name_score and player2_name_score store rounds won in the match.
CREATE TABLE IF NOT EXISTS "match" (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    player1_id BIGINT NOT NULL REFERENCES player(id),
    player2_id BIGINT NOT NULL REFERENCES player(id),
    player1_name_score INTEGER NOT NULL DEFAULT 0
        CHECK (player1_name_score BETWEEN 0 AND 5),
    player2_name_score INTEGER NOT NULL DEFAULT 0
        CHECK (player2_name_score BETWEEN 0 AND 5),
    winner_player_name VARCHAR(40),
    status VARCHAR(24) NOT NULL DEFAULT 'active'
        CHECK (status IN (
            'active', 'awaiting_rematch', 'rematched', 'closed', 'cancelled'
        )),
    current_round SMALLINT NOT NULL DEFAULT 1
        CHECK (current_round BETWEEN 1 AND 5),
    player1_rematch BOOLEAN,
    player2_rematch BOOLEAN,
    rematch_match_id BIGINT REFERENCES "match"(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    CHECK (player1_id <> player2_id)
);

CREATE INDEX IF NOT EXISTS ix_match_player1_status
    ON "match" (player1_id, status);

CREATE INDEX IF NOT EXISTS ix_match_player2_status
    ON "match" (player2_id, status);

CREATE TABLE IF NOT EXISTS match_round (
    match_id BIGINT NOT NULL REFERENCES "match"(id) ON DELETE CASCADE,
    round_number SMALLINT NOT NULL CHECK (round_number BETWEEN 1 AND 5),
    player1_roll SMALLINT CHECK (player1_roll BETWEEN 1 AND 6),
    player2_roll SMALLINT CHECK (player2_roll BETWEEN 1 AND 6),
    round_winner_player_id BIGINT REFERENCES player(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    PRIMARY KEY (match_id, round_number)
);

CREATE TABLE IF NOT EXISTS game_queue (
    player_id BIGINT PRIMARY KEY REFERENCES player(id) ON DELETE CASCADE,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
