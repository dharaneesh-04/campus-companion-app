#!/usr/bin/env python3
"""
Campus Companion — backend server.

Uses ONLY the Python standard library (http.server, sqlite3, hashlib,
secrets) — no pip install needed. Works with Python 3.8+.

Run:
    python3 server.py

Then open:
    http://localhost:8000

Data (accounts, notes, events) is stored in campus.db, a SQLite file
created next to this script the first time it runs. Restarting the
server keeps everything — this is real persistence, not a demo reset.
"""

import json
import os
import secrets
import hashlib
import sqlite3
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "campus.db")
FRONTEND_FILE = os.path.join(BASE_DIR, "campus-companion.html")
PORT = int(os.environ.get("PORT", 8000))
SESSION_COOKIE = "campus_session"
PBKDF2_ITERATIONS = 100_000


# ---------------------------------------------------------------- database

def get_db():
  
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL,
            email         TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt          TEXT NOT NULL,
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token      TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS notes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER,
            title      TEXT NOT NULL,
            subject    TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER,
            title      TEXT NOT NULL,
            event_date TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
        );
        """
    )
    if conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO notes (user_id, title, subject) VALUES (NULL, ?, ?)",
            [
                ("Unit 3 recap", "Thermodynamics"),
                ("Trees & Graphs", "Data Structures"),
                ("Midterm recap", "Microeconomics"),
            ],
        )
    if conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO events (user_id, title, event_date) VALUES (NULL, ?, ?)",
            [
                ("Robotics Club Demo Day", "Fri · 6:00 PM"),
                ("Guest Lecture: AI Ethics", "Mon · 3:30 PM"),
                ("Spring Fest Auditions", "Wed · 5:00 PM"),
            ],
        )
    conn.commit()
    conn.close()


# ------------------------------------------------------------------- auth

def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return digest.hex(), salt


def verify_password(password, salt, expected_hash):
    digest, _ = hash_password(password, salt)
    return secrets.compare_digest(digest, expected_hash)


def current_user(conn, handler):
    token = handler.get_cookie(SESSION_COOKIE)
    if not token:
        return None
    row = conn.execute(
        """SELECT users.id, users.name, users.email FROM sessions
           JOIN users ON users.id = sessions.user_id
           WHERE sessions.token = ?""",
        (token,),
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------- handler

class Handler(BaseHTTPRequestHandler):
    server_version = "CampusCompanion/1.0"

    # ---------- helpers ----------
    def get_cookie(self, name):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = cookies.SimpleCookie()
        jar.load(raw)
        morsel = jar.get(name)
        return morsel.value if morsel else None

    def send_json(self, status, payload, set_cookie=None, clear_cookie=False):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}={set_cookie}; Path=/; HttpOnly; SameSite=Lax",
            )
        if clear_cookie:
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
            )
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def log_message(self, fmt, *args):
        pass  # quiet console — remove this line to see request logs

    # ---------- routing ----------
        def do_GET(self):
    path = urlparse(self.path).path

    if path in ("/", "/index.html", "/campus-companion.html"):
        return self.serve_frontend()

    if path == "/api/me":
        return self.handle_me()

    if path == "/api/notes":
        return self.handle_list_notes()

    if path == "/api/search":
        return self.handle_search_notes()

    if path == "/api/events":
        return self.handle_list_events()

    def do_POST(self):
        path = urlparse(self.path).path
        routes = {
            "/api/signup": self.handle_signup,
            "/api/login": self.handle_login,
            "/api/logout": self.handle_logout,
            "/api/notes": self.handle_create_note,
            "/api/events": self.handle_create_event,
        }
        handler = routes.get(path)
        if handler:
            return handler()
        self.send_json(404, {"error": "Not found"})

    # ---------- static ----------
    def serve_frontend(self):
        try:
            with open(FRONTEND_FILE, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self.send_json(
                500, {"error": "campus-companion.html not found next to server.py"}
            )
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------- auth ----------
    def handle_signup(self):
        data = self.read_json()
        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        if not name or not email or len(password) < 6:
            return self.send_json(
                400,
                {"error": "Fill in every field — password needs at least 6 characters."},
            )
        conn = get_db()
        try:
            if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                return self.send_json(
                    409,
                    {"error": "An account with that email already exists — try logging in."},
                )
            password_hash, salt = hash_password(password)
            cur = conn.execute(
                "INSERT INTO users (name, email, password_hash, salt) VALUES (?, ?, ?, ?)",
                (name, email, password_hash, salt),
            )
            user_id = cur.lastrowid
            token = secrets.token_hex(24)
            conn.execute(
                "INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id)
            )
            conn.commit()
            self.send_json(
                201,
                {"user": {"id": user_id, "name": name, "email": email}},
                set_cookie=token,
            )
        finally:
            conn.close()

    def handle_login(self):
        data = self.read_json()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT id, name, email, password_hash, salt FROM users WHERE email = ?",
                (email,),
            ).fetchone()
            if not row or not verify_password(password, row["salt"], row["password_hash"]):
                return self.send_json(
                    401, {"error": "That email and password don't match an account."}
                )
            token = secrets.token_hex(24)
            conn.execute(
                "INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, row["id"])
            )
            conn.commit()
            self.send_json(
                200,
                {"user": {"id": row["id"], "name": row["name"], "email": row["email"]}},
                set_cookie=token,
            )
        finally:
            conn.close()

    def handle_logout(self):
        token = self.get_cookie(SESSION_COOKIE)
        conn = get_db()
        try:
            if token:
                conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                conn.commit()
        finally:
            conn.close()
        self.send_json(200, {"ok": True}, clear_cookie=True)

    def handle_me(self):
        conn = get_db()
        try:
            user = current_user(conn, self)
            if not user:
                return self.send_json(401, {"error": "Not logged in"})
            self.send_json(200, {"user": user})
        finally:
            conn.close()

    # ---------- notes ----------
    def handle_list_notes(self):
        conn = get_db()
        try:
            user = current_user(conn, self)
            if not user:
                return self.send_json(401, {"error": "Log in to view notes"})
            rows = conn.execute(
                """SELECT notes.title, notes.subject,
                          COALESCE(users.name, 'Shared by faculty') AS author
                   FROM notes LEFT JOIN users ON users.id = notes.user_id
                   ORDER BY notes.created_at DESC LIMIT 25"""
            ).fetchall()
            self.send_json(200, {"notes": [dict(r) for r in rows]})
        finally:
            conn.close()
            def handle_search_notes(self):
    conn = get_db()
    try:
        user = current_user(conn, self)
        if not user:
            return self.send_json(401, {"error": "Login required"})

        query = parse_qs(urlparse(self.path).query)
        keyword = query.get("q", [""])[0]

        rows = conn.execute("""
            SELECT title, subject
            FROM notes
            WHERE title LIKE ?
               OR subject LIKE ?
            ORDER BY created_at DESC
        """, (f"%{keyword}%", f"%{keyword}%")).fetchall()

        self.send_json(200, {
            "notes": [dict(r) for r in rows]
        })

    finally:
        conn.close()

    def handle_create_note(self):
        conn = get_db()
        try:
            user = current_user(conn, self)
            if not user:
                return self.send_json(401, {"error": "Log in to add a note"})
            data = self.read_json()
            title = (data.get("title") or "").strip()
            subject = (data.get("subject") or "").strip()
            if not title:
                return self.send_json(400, {"error": "Give the note a title"})
            conn.execute(
                "INSERT INTO notes (user_id, title, subject) VALUES (?, ?, ?)",
                (user["id"], title, subject),
            )
            conn.commit()
            self.send_json(201, {"ok": True})
        finally:
            conn.close()

    # ---------- events ----------
    def handle_list_events(self):
        conn = get_db()
        try:
            user = current_user(conn, self)
            if not user:
                return self.send_json(401, {"error": "Log in to view events"})
            rows = conn.execute(
                """SELECT events.title, events.event_date,
                          COALESCE(users.name, 'Campus Events') AS author
                   FROM events LEFT JOIN users ON users.id = events.user_id
                   ORDER BY events.created_at DESC LIMIT 25"""
            ).fetchall()
            self.send_json(200, {"events": [dict(r) for r in rows]})
        finally:
            conn.close()

    def handle_create_event(self):
        conn = get_db()
        try:
            user = current_user(conn, self)
            if not user:
                return self.send_json(401, {"error": "Log in to add an event"})
            data = self.read_json()
            title = (data.get("title") or "").strip()
            event_date = (data.get("event_date") or "").strip()
            if not title:
                return self.send_json(400, {"error": "Give the event a title"})
            conn.execute(
                "INSERT INTO events (user_id, title, event_date) VALUES (?, ?, ?)",
                (user["id"], title, event_date),
            )
            conn.commit()
            self.send_json(201, {"ok": True})
        finally:
            conn.close()


def main():
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Campus Companion running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
