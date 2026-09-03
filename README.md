# Neon Dice Arena

A web-only multiplayer dice game built with Python and Streamlit, using NeonDB for persistent game data.

This game is designed to be played online through the browser only and is not a local offline game.

Live app: https://dicegamezz.streamlit.app/

## Overview

Neon Dice Arena is a browser-based two-player dice game where users create an account, sign in, join a matchmaking queue, and play a five-round match against another online player. The app stores match data in PostgreSQL and updates the leaderboard in real time.

The game is intended for quick online play and supports:

- Registration and login
- Username and nickname validation
- Secure password hashing with Argon2
- Matchmaking queue management
- Five-round competitive play
- Match history and leaderboard tracking
- Rematch voting flow

## Features

- User registration with unique username and nickname checks
- Passwords stored as Argon2 hashes, not as raw text
- Database-backed online queue using PostgreSQL
- One active match per player at a time
- Each match consists of five rounds
- One dice roll per player per round
- Match results and round history saved to the database
- Leaderboard showing wins
- Rematch flow that requires both players to accept
- Automatic match closure if the rematch timeout expires
- Live updates in the UI using Streamlit fragments

## Tech stack

- Python
- Streamlit
- PostgreSQL / NeonDB
- Psycopg
- SQLAlchemy
- Pandas
- Argon2 password hashing

## Project structure

```text
dice_game/
├── app.py
├── db.py
├── schema.sql
├── requirements.txt
├── README.md
├── .streamlit/
│   └── secrets.toml
└── .gitignore
```

## How to play

This project is designed specifically for online gameplay in the browser.

To play the game, open the public web app here:

https://dicegamezz.streamlit.app/

The app connects to NeonDB for all persistent game data, including accounts, match state, queue status, and leaderboard information.

No local installation or local game session is required for normal use.

## How the game works

1. Create an account with a username, nickname, and password.
2. Sign in with your account.
3. Join the matchmaking queue.
4. When another player is found, a match starts.
5. Each player rolls a die for each round.
6. After five rounds, the winner is determined.
7. The app tracks matches and updates the leaderboard.
8. Players can accept or reject a rematch.

## Game rules

- A match lasts up to five rounds.
- Each round, both players roll one die.
- The higher roll wins the round.
- If both dice are equal, the round is a tie.
- A match can also end in a draw.
- Only the winner's `matches_won` value increases after a non-draw result.

## Deployment

This project is online and accessible here:

https://dicegamezz.streamlit.app/

## Notes

The app is designed as a small real-time multiplayer project and uses a database-driven queue and persistent game state. For a production-grade deployment, you would typically add stronger session protection, rate limiting, better queue cleanup logic, and automated tests.
