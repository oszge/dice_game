# Neon Dice Arena

A two-player online dice game built with Streamlit, Neon Postgres, Psycopg,
SQLAlchemy, Pandas, and Argon2 password hashing.

## Features

- Multiple-player registration and sign-in
- Unique usernames and nicknames
- Passwords stored as Argon2 hashes
- Database-backed matchmaking queue
- One active opponent per player
- Five rounds, one dice roll per player per round
- Match and round history stored in PostgreSQL
- Winner's `matches_won` value incremented atomically
- Rematch starts only after both players accept
- Match closes only after both players reject
- Live polling every two seconds with a Streamlit fragment
- Pandas leaderboard and recent-match tables

A dice tie counts as a tied round. Therefore, a five-round match can also end in
a draw; in that case, neither player's `matches_won` value is incremented.

## Project files

```text
neon_dice_game/
├── app.py
├── db.py
├── schema.sql
├── requirements.txt
├── README.md
└── .streamlit/
    └── secrets.toml.example
```

## Setup

1. Create a Neon project and copy its pooled PostgreSQL connection string.
2. Create and activate a virtual environment.
3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Copy the example secrets file:

   **Windows PowerShell**

   ```powershell
   Copy-Item .streamlit/secrets.toml.example .streamlit/secrets.toml
   ```

   **macOS/Linux**

   ```bash
   cp .streamlit/secrets.toml.example .streamlit/secrets.toml
   ```

5. Replace `DATABASE_URL` with the Neon connection string.
6. Start the app:

   ```bash
   streamlit run app.py
   ```

The app runs `schema.sql` automatically on startup. You may also paste the same
file into the Neon SQL Editor and execute it once.

## Testing multiplayer locally

Open the app in a normal browser window and an incognito/private window. Create
a different account in each window, sign in, and join the queue from both.

## Main SQL operations

### Register a player

```sql
INSERT INTO player (nickname, username, password)
VALUES (%s, %s, %s)
RETURNING id;
```

### Find an open match

```sql
SELECT *
FROM "match"
WHERE (player1_id = %s OR player2_id = %s)
  AND status IN ('active', 'awaiting_rematch')
ORDER BY id DESC
LIMIT 1;
```

### Increment the winner

```sql
UPDATE player
SET matches_won = matches_won + 1
WHERE id = %s;
```

### Leaderboard

```sql
SELECT
    DENSE_RANK() OVER (ORDER BY matches_won DESC) AS rank,
    nickname,
    matches_won
FROM player
ORDER BY matches_won DESC, LOWER(nickname);
```

## Important production improvements

This is a strong course-project prototype, but a public production deployment
should also add CSRF/session hardening, rate limiting, account recovery,
structured logging, automated tests, stale-queue cleanup, match abandonment,
and stronger database-level enforcement that a player cannot appear in two
open matches.
