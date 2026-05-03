"""
database.py — SQLite Database Setup & Helper Functions
=======================================================
This file handles all database operations:
- Creating tables (users, interviews)
- User registration and login
- Saving and loading interview records
"""

import sqlite3, hashlib
from datetime import datetime

DB_PATH = "interview_bot.db"    # SQLite database file stored locally

# ─────────────────────────────────────────────────────────────────────────────
# DB CONNECTION
# ─────────────────────────────────────────────────────────────────────────────

def get_db():
    """Open and return a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row    # lets us access columns by name (row["name"])
    return conn

# ─────────────────────────────────────────────────────────────────────────────
# CREATE TABLES
# ─────────────────────────────────────────────────────────────────────────────

def init_db():
    """Create all tables if they don't exist, and seed a default admin user."""
    conn = get_db()
    c = conn.cursor()

    # Users table: stores all registered accounts
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        name           TEXT NOT NULL,
        email          TEXT NOT NULL UNIQUE,
        password       TEXT NOT NULL,
        phone          TEXT,                   -- optional phone number
        college        TEXT,                   -- optional college/university
        target_company TEXT,                   -- optional dream company they're preparing for
        role           TEXT DEFAULT 'user',
        created_at     TEXT DEFAULT (datetime('now'))
    );

    -- Interviews table: stores each completed interview
    CREATE TABLE IF NOT EXISTS interviews (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        job_role   TEXT,
        experience TEXT,
        test_type  TEXT,
        avg_score  REAL,
        history    TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # Create a default admin account if none exists
    admin = c.execute("SELECT id FROM users WHERE email='admin@bot.com'").fetchone()
    if not admin:
        c.execute(
            "INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, 'admin')",
            ("Admin", "admin@bot.com", _hash("admin123"))
        )
        print("Default admin created: admin@bot.com / admin123")

    conn.commit()
    conn.close()

# ─────────────────────────────────────────────────────────────────────────────
# PASSWORD HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _hash(password: str) -> str:
    """Hash a password using SHA-256 before storing it."""
    return hashlib.sha256(password.encode()).hexdigest()

def check_password(plain: str, hashed: str) -> bool:
    """Check if a plain password matches the stored hash."""
    return _hash(plain) == hashed

# ─────────────────────────────────────────────────────────────────────────────
# USER HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def create_user(name: str, email: str, password: str,
                phone: str = "", college: str = "", target_company: str = ""):
    """
    Register a new user with optional extra profile fields.
    Returns (True, "") on success, or (False, error_message) on failure.
    """
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (name, email, password, phone, college, target_company) VALUES (?, ?, ?, ?, ?, ?)",
            (name, email, _hash(password), phone, college, target_company)
        )
        conn.commit()
        return True, ""
    except sqlite3.IntegrityError:
        return False, "Email already registered."    # email must be unique
    finally:
        conn.close()

def get_user_by_email(email: str):
    """Find a user by their email address. Returns a dict or None."""
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_id(uid: int):
    """Find a user by their ID. Returns a dict or None."""
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_users():
    """Get all regular users (not admins) with their interview count and avg score."""
    conn = get_db()
    rows = conn.execute("""
        SELECT u.*, COUNT(i.id) as interview_count,
               ROUND(AVG(i.avg_score), 1) as avg_score
        FROM users u
        LEFT JOIN interviews i ON i.user_id = u.id
        WHERE u.role = 'user'
        GROUP BY u.id
        ORDER BY u.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_user(uid: int):
    """Delete a user and all their interviews (CASCADE takes care of related rows)."""
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit()
    conn.close()

# ─────────────────────────────────────────────────────────────────────────────
# INTERVIEW HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def save_interview(user_id, job_role, experience, test_type, avg_score, history):
    """Save a completed interview to the database. History is stored as JSON text."""
    import json
    conn = get_db()
    conn.execute(
        "INSERT INTO interviews (user_id, job_role, experience, test_type, avg_score, history) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, job_role, experience, test_type, avg_score, json.dumps(history))
    )
    conn.commit()
    conn.close()

def get_user_interviews(user_id: int):
    """Get all interviews for a user, newest first. Parses history JSON back to a list."""
    import json
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM interviews WHERE user_id=? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        d["history"] = json.loads(d["history"] or "[]")    # convert JSON string → list
        result.append(d)
    return result

def get_user_stats(user_id: int):
    """Return total interview count, average score, and last interview date for a user."""
    conn = get_db()
    row = conn.execute("""
        SELECT COUNT(*) as total,
               ROUND(AVG(avg_score), 1) as avg_score,
               MAX(created_at) as last_interview
        FROM interviews WHERE user_id=?
    """, (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else {"total": 0, "avg_score": None, "last_interview": None}
