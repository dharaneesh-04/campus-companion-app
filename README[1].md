# Campus Companion — running it locally

## Requirements
Just Python 3.8+. No `pip install` needed — the backend uses only
the standard library (`http.server`, `sqlite3`, `hashlib`, `secrets`).

## Run it
```
python3 server.py
```
Then open **http://localhost:8000** in your browser.

That's it — the server serves the frontend *and* the API from the
same address, so there's no CORS setup and no separate dev server.

## What's actually happening
- Signing up or logging in creates a **real account** in `campus.db`,
  a SQLite file created next to `server.py` the first time you run it.
- Passwords are salted and hashed with PBKDF2 (100,000 iterations) —
  never stored in plain text.
- After login, the server sets an **HttpOnly session cookie**, so
  refreshing the page keeps you logged in (no client-side storage
  involved at all).
- Notes and Events are read from and written to the same database —
  add one while logged in and it's there the next time you open the
  page, even after restarting the server.
- Lost & Found stays open to everyone (no login required), matching
  the original design.

## Files
| File | What it is |
|---|---|
| `server.py` | The backend — start this one |
| `campus-companion.html` | The frontend — served automatically by `server.py`, don't open it directly with `file://` or the API calls won't have anywhere to go |
| `campus.db` | Created automatically on first run — delete it any time to reset all accounts/notes/events |

## A note on "production-ready"
This is built to be genuinely functional and a solid base to learn
from — real hashing, real sessions, real persistence — but a couple
of things you'd want before shipping it publicly:
- Run it behind HTTPS and add the `Secure` flag to the session cookie
  (currently omitted so it works over plain `http://localhost`).
- Add rate-limiting on `/api/login` and `/api/signup` to slow down
  brute-force attempts.
- Swap the single-file SQLite setup for a managed database if you
  expect concurrent traffic beyond a class project.
