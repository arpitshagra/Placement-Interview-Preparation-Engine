"""
database.py — SQLite Database Setup & Helper Functions
=======================================================
This file handles all database operations:
- Creating tables (users, interviews)
- User registration and login
- Saving and loading interview records
"""

import sqlite3, hashlib, json
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
        phone          TEXT,
        college        TEXT,
        target_company TEXT,
        role           TEXT DEFAULT 'user',
        created_at     TEXT DEFAULT (datetime('now'))
    );

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

    CREATE TABLE IF NOT EXISTS resumes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER NOT NULL,
        filename    TEXT,
        file_type   TEXT,
        raw_text    TEXT,
        skills      TEXT DEFAULT '[]',
        projects    TEXT DEFAULT '[]',
        education   TEXT DEFAULT '[]',
        experience  TEXT DEFAULT '[]',
        strengths   TEXT DEFAULT '[]',
        weaknesses  TEXT DEFAULT '[]',
        summary     TEXT DEFAULT '',
        created_at  TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS job_descriptions (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id             INTEGER NOT NULL,
        jd_text             TEXT,
        role                TEXT DEFAULT '',
        required_skills     TEXT DEFAULT '[]',
        preferred_skills    TEXT DEFAULT '[]',
        experience_required TEXT DEFAULT '',
        created_at          TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS resume_jd_matches (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id           INTEGER NOT NULL,
        resume_id         INTEGER NOT NULL,
        jd_id             INTEGER NOT NULL,
        match_score       REAL DEFAULT 0,
        matched_skills    TEXT DEFAULT '[]',
        missing_skills    TEXT DEFAULT '[]',
        improvement_areas TEXT DEFAULT '[]',
        created_at        TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(user_id)   REFERENCES users(id)            ON DELETE CASCADE,
        FOREIGN KEY(resume_id) REFERENCES resumes(id)          ON DELETE CASCADE,
        FOREIGN KEY(jd_id)     REFERENCES job_descriptions(id) ON DELETE CASCADE
    );
    """)

    # Column migrations for existing databases
    for table, col_def in [
        ("interviews", "match_id INTEGER"),
        ("interviews", "resume_id INTEGER"),
        ("interviews", "jd_id INTEGER"),
        ("interviews", "feedback TEXT DEFAULT '{}'"),
        ("interviews", "rubric_scores TEXT DEFAULT '[]'"),
        ("interviews", "topics_evidence TEXT DEFAULT '[]'"),
        ("interviews", "weak_areas TEXT DEFAULT '[]'"),
        ("interviews", "action_plan TEXT DEFAULT '[]'"),
        ("resume_jd_matches", "tfidf_score REAL DEFAULT 0"),
        ("resume_jd_matches", "topics_evidence TEXT DEFAULT '[]'"),
        ("resume_jd_matches", "analytics_breakdown TEXT DEFAULT '{}'")
    ]:
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
        except Exception:
            pass

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

def save_interview(user_id, job_role, experience, test_type, avg_score, history,
                   match_id=None, resume_id=None, jd_id=None,
                   feedback=None, rubric_scores=None, topics_evidence=None,
                   weak_areas=None, action_plan=None) -> int:
    """Save a completed interview with auditable rubrics and topic evidence. Returns new row ID."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO interviews
           (user_id, job_role, experience, test_type, avg_score, history,
            match_id, resume_id, jd_id, feedback, rubric_scores, topics_evidence, weak_areas, action_plan)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id, job_role, experience, test_type, avg_score,
            json.dumps(history or []),
            match_id, resume_id, jd_id,
            json.dumps(feedback or {}),
            json.dumps(rubric_scores or []),
            json.dumps(topics_evidence or []),
            json.dumps(weak_areas or []),
            json.dumps(action_plan or [])
        )
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id

def get_user_interviews(user_id: int):
    """Get all interviews for a user, newest first. Parses JSON fields."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM interviews WHERE user_id=? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        d["history"] = json.loads(d.get("history") or "[]")
        d["feedback"] = json.loads(d.get("feedback") or "{}")
        d["rubric_scores"] = json.loads(d.get("rubric_scores") or "[]")
        d["topics_evidence"] = json.loads(d.get("topics_evidence") or "[]")
        d["weak_areas"] = json.loads(d.get("weak_areas") or "[]")
        d["action_plan"] = json.loads(d.get("action_plan") or "[]")
        result.append(d)
    return result

def get_interview_report(interview_id: int, user_id: int = None):
    """Retrieve full auditable report details for a specific interview session."""
    conn = get_db()
    query = "SELECT * FROM interviews WHERE id=?"
    params = [interview_id]
    if user_id is not None:
        query += " AND user_id=?"
        params.append(user_id)

    row = conn.execute(query, tuple(params)).fetchone()
    if not row:
        conn.close()
        return None

    report = dict(row)
    report["history"] = json.loads(report.get("history") or "[]")
    report["feedback"] = json.loads(report.get("feedback") or "{}")
    report["rubric_scores"] = json.loads(report.get("rubric_scores") or "[]")
    report["topics_evidence"] = json.loads(report.get("topics_evidence") or "[]")
    report["weak_areas"] = json.loads(report.get("weak_areas") or "[]")
    report["action_plan"] = json.loads(report.get("action_plan") or "[]")

    # If associated with a match, retrieve match details
    if report.get("match_id"):
        m_row = conn.execute("SELECT * FROM resume_jd_matches WHERE id=?", (report["match_id"],)).fetchone()
        if m_row:
            m_dict = dict(m_row)
            m_dict["matched_skills"] = json.loads(m_dict.get("matched_skills") or "[]")
            m_dict["missing_skills"] = json.loads(m_dict.get("missing_skills") or "[]")
            m_dict["improvement_areas"] = json.loads(m_dict.get("improvement_areas") or "[]")
            m_dict["analytics_breakdown"] = json.loads(m_dict.get("analytics_breakdown") or "{}")
            report["match_data"] = m_dict

    conn.close()
    return report

def get_user_performance_trends(user_id: int) -> dict:
    """Compute score progression timeline and weak area frequencies across multiple sessions."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, job_role, avg_score, created_at, weak_areas FROM interviews WHERE user_id=? ORDER BY created_at ASC",
        (user_id,)
    ).fetchall()
    conn.close()

    timeline = []
    weakness_counter = {}

    for r in rows:
        sc = r["avg_score"] or 0
        timeline.append({
            "interview_id": r["id"],
            "role": r["job_role"],
            "score": round(sc, 1),
            "date": r["created_at"][:10] if r["created_at"] else ""
        })
        try:
            w_list = json.loads(r["weak_areas"] or "[]")
            for w in w_list:
                w_str = str(w)
                weakness_counter[w_str] = weakness_counter.get(w_str, 0) + 1
        except Exception:
            pass

    top_weaknesses = sorted([{"area": k, "count": v} for k, v in weakness_counter.items()], key=lambda x: x["count"], reverse=True)[:5]

    return {
        "timeline": timeline,
        "total_sessions": len(timeline),
        "avg_score_overall": round(sum(t["score"] for t in timeline) / len(timeline), 1) if timeline else 0.0,
        "latest_score": timeline[-1]["score"] if timeline else 0.0,
        "frequent_weak_areas": top_weaknesses
    }

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



# ─────────────────────────────────────────────────────────────────────────────
# RESUME HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def save_resume(user_id: int, filename: str, file_type: str, raw_text: str, analysis: dict) -> int:
    """Persist a parsed resume. Returns the new row ID."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO resumes
           (user_id, filename, file_type, raw_text, skills, projects, education,
            experience, strengths, weaknesses, summary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, filename, file_type, raw_text,
         json.dumps(analysis.get("skills",     [])),
         json.dumps(analysis.get("projects",   [])),
         json.dumps(analysis.get("education",  [])),
         json.dumps(analysis.get("experience", [])),
         json.dumps(analysis.get("strengths",  [])),
         json.dumps(analysis.get("weaknesses", [])),
         analysis.get("summary", ""))
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def get_user_resume(user_id: int):
    """Return the most-recently uploaded resume for a user (or None)."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM resumes WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
        (user_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    for field in ("skills", "projects", "education", "experience", "strengths", "weaknesses"):
        d[field] = json.loads(d.get(field) or "[]")
    return d


def get_user_resumes(user_id: int):
    """Return all resumes for a user, newest first."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, filename, file_type, summary, created_at FROM resumes WHERE user_id=? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_resume_by_id(resume_id: int, user_id: int):
    """Fetch a specific resume row (verifies ownership). Returns raw dict (JSON strings unparsed)."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM resumes WHERE id=? AND user_id=?",
        (resume_id, user_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# JOB DESCRIPTION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def save_jd(user_id: int, jd_text: str, analysis: dict) -> int:
    """Persist a parsed job description. Returns the new row ID."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO job_descriptions
           (user_id, jd_text, role, required_skills, preferred_skills, experience_required)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, jd_text,
         analysis.get("role", ""),
         json.dumps(analysis.get("required_skills",  [])),
         json.dumps(analysis.get("preferred_skills", [])),
         analysis.get("experience_required", ""))
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def get_jd_by_id(jd_id: int, user_id: int):
    """Fetch a specific JD row (verifies ownership). Returns raw dict."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM job_descriptions WHERE id=? AND user_id=?",
        (jd_id, user_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_jds(user_id: int):
    """Return all JDs for a user, newest first."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, role, experience_required, created_at FROM job_descriptions WHERE user_id=? ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# MATCH HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def save_match(user_id: int, resume_id: int, jd_id: int, result: dict) -> int:
    """Persist a match result including NLP similarity and topic blueprint. Returns new row ID."""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO resume_jd_matches
           (user_id, resume_id, jd_id, match_score, matched_skills, missing_skills,
            improvement_areas, tfidf_score, topics_evidence, analytics_breakdown)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, resume_id, jd_id,
         result.get("match_score", 0),
         json.dumps(result.get("matched_skills",    [])),
         json.dumps(result.get("missing_skills",    [])),
         json.dumps(result.get("improvement_areas", [])),
         result.get("tfidf_score", 0.0),
         json.dumps(result.get("topics_evidence",   [])),
         json.dumps(result.get("analytics_breakdown", {})))
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def get_match_by_id(match_id: int, user_id: int = None):
    """Fetch a single match record with unparsed JSON fields converted back to dicts."""
    conn = get_db()
    query = """
        SELECT m.*,
               r.filename AS resume_filename, r.skills AS resume_skills,
               r.projects AS resume_projects, r.experience AS resume_experience,
               j.role     AS jd_role, j.required_skills AS jd_required,
               j.preferred_skills AS jd_preferred, j.experience_required AS jd_experience
        FROM resume_jd_matches m
        JOIN resumes r          ON r.id = m.resume_id
        JOIN job_descriptions j ON j.id = m.jd_id
        WHERE m.id = ?
    """
    params = [match_id]
    if user_id is not None:
        query += " AND m.user_id = ?"
        params.append(user_id)

    row = conn.execute(query, tuple(params)).fetchone()
    conn.close()
    if not row:
        return None

    d = dict(row)
    for field in ("matched_skills", "missing_skills", "improvement_areas", "topics_evidence",
                  "resume_skills", "resume_projects", "resume_experience", "jd_required", "jd_preferred"):
        try:
            d[field] = json.loads(d.get(field) or "[]")
        except Exception:
            d[field] = []
    try:
        d["analytics_breakdown"] = json.loads(d.get("analytics_breakdown") or "{}")
    except Exception:
        d["analytics_breakdown"] = {}
    return d


def get_user_matches(user_id: int):
    """Return all match results for a user with resume filename, JD role, and topic counts."""
    conn = get_db()
    rows = conn.execute("""
        SELECT m.id, m.match_score, m.tfidf_score, m.matched_skills, m.missing_skills,
               m.improvement_areas, m.topics_evidence, m.analytics_breakdown, m.created_at,
               r.filename AS resume_filename,
               j.role     AS jd_role
        FROM resume_jd_matches m
        JOIN resumes r          ON r.id = m.resume_id
        JOIN job_descriptions j ON j.id = m.jd_id
        WHERE m.user_id = ?
        ORDER BY m.created_at DESC
    """, (user_id,)).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        for field in ("matched_skills", "missing_skills", "improvement_areas", "topics_evidence"):
            try:
                d[field] = json.loads(d.get(field) or "[]")
            except Exception:
                d[field] = []
        try:
            d["analytics_breakdown"] = json.loads(d.get("analytics_breakdown") or "{}")
        except Exception:
            d["analytics_breakdown"] = {}
        result.append(d)
    return result

