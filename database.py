"""
database.py — Supabase PostgreSQL Database Setup & Helper Functions
===================================================================
This file handles all database and authentication operations using Supabase:
- PostgreSQL storage via Supabase Client (users, interviews, resumes, JDs, matches)
- Production-grade Supabase Auth and SHA-256 password hashing
- Native JSONB support for questions, skills, analysis, feedback, and rubrics
- Fully replaces legacy SQLite with enterprise cloud PostgreSQL
"""

import os
import json
import uuid
import hashlib
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "API_KEY.env"))

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

_client: Optional[Client] = None
_admin_client: Optional[Client] = None


def get_supabase() -> Client:
    """Return an initialized Supabase client (using anon key or service role key)."""
    global _client
    if _client is not None:
        return _client

    url = SUPABASE_URL
    key = SUPABASE_KEY or SUPABASE_SERVICE_ROLE_KEY

    if not url or not key:
        raise ValueError(
            "Supabase credentials not found. Please set SUPABASE_URL and SUPABASE_KEY in your .env file."
        )

    _client = create_client(url, key)
    return _client


def get_supabase_admin() -> Client:
    """
    Return an administrative Supabase client using SUPABASE_SERVICE_ROLE_KEY.
    Allows bypassing RLS for server-side management, auto-confirming signups, and admin actions.
    Falls back to the regular client if service role key is not provided.
    """
    global _admin_client
    if _admin_client is not None:
        return _admin_client

    url = SUPABASE_URL
    key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY

    if not url or not key:
        raise ValueError(
            "Supabase credentials not found. Please set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in your .env file."
        )

    _admin_client = create_client(url, key)
    return _admin_client


def _get_active_client() -> Client:
    """Return the admin client if available, else standard client."""
    try:
        return get_supabase_admin()
    except Exception:
        return get_supabase()


def _ensure_list_or_dict(val: Any, default_val: Any = None) -> Any:
    """Helper to deserialize JSON strings into Python objects if needed."""
    if default_val is None:
        default_val = []
    if val is None:
        return default_val
    if isinstance(val, (list, dict)):
        return val
    if isinstance(val, str):
        val_s = val.strip()
        if not val_s:
            return default_val
        try:
            return json.loads(val_s)
        except Exception:
            return val
    return val


# ─────────────────────────────────────────────────────────────────────────────
# PASSWORD HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _hash(password: str) -> str:
    """Hash a password using SHA-256."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def check_password(plain: str, hashed: str) -> bool:
    """Check if a plain password matches the stored hash."""
    if not hashed or not plain:
        return False
    if _hash(plain) == hashed:
        return True
    if hashed.startswith("$2") or hashed.startswith("$2b$"):
        try:
            import bcrypt
            return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            pass
    return plain == hashed


# ─────────────────────────────────────────────────────────────────────────────
# DATABASE INITIALIZATION & SEEDING
# ─────────────────────────────────────────────────────────────────────────────

def init_db():
    """
    Verify Supabase connection and ensure the default admin user exists.
    """
    if not SUPABASE_URL or not (SUPABASE_KEY or SUPABASE_SERVICE_ROLE_KEY):
        print("[Supabase] Warning: Missing SUPABASE_URL or SUPABASE_KEY in environment.")
        return

    admin_email = "admin@bot.com"
    try:
        sb = _get_active_client()
        res = sb.table("users").select("id, email, role").eq("email", admin_email).execute()
        admin = res.data[0] if res.data else None

        if not admin:
            user_id = None
            if SUPABASE_SERVICE_ROLE_KEY:
                try:
                    admin_res = sb.auth.admin.create_user({
                        "email": admin_email,
                        "password": "admin123",
                        "email_confirm": True,
                        "user_metadata": {"name": "Admin", "role": "admin"}
                    })
                    if admin_res and admin_res.user:
                        user_id = admin_res.user.id
                except Exception as auth_err:
                    print(f"[Supabase] Admin auth note: {auth_err}")

            if not user_id:
                user_id = str(uuid.uuid4())

            sb.table("users").upsert({
                "id": user_id,
                "name": "Admin",
                "email": admin_email,
                "password": _hash("admin123"),
                "role": "admin"
            }).execute()
            print("Default admin verified: admin@bot.com / admin123")
    except Exception as exc:
        print(f"[Supabase] Database init note (run supabase_schema.sql if tables are not yet created): {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# USER MANAGEMENT & AUTHENTICATION
# ─────────────────────────────────────────────────────────────────────────────

def create_user(name: str, email: str, password: str,
                phone: str = "", college: str = "", target_company: str = "") -> Tuple[bool, str]:
    """
    Register a new user using Supabase Auth and synchronize with public.users.
    Returns (True, "") on success, or (False, error_message) on failure.
    """
    email_clean = email.strip().lower()
    if len(password) < 6:
        return False, "Password must be at least 6 characters."

    sb = _get_active_client()
    user_id = None

    # Check if user already exists in public.users
    try:
        existing = sb.table("users").select("id").eq("email", email_clean).execute()
        if existing.data:
            return False, "Email already registered."
    except Exception:
        pass

    # Try creating user in Supabase Auth
    try:
        if SUPABASE_SERVICE_ROLE_KEY and hasattr(sb, "auth") and hasattr(sb.auth, "admin"):
            try:
                res = sb.auth.admin.create_user({
                    "email": email_clean,
                    "password": password,
                    "email_confirm": True,
                    "user_metadata": {
                        "name": name,
                        "phone": phone,
                        "college": college,
                        "target_company": target_company,
                        "role": "user"
                    }
                })
                if res and res.user:
                    user_id = res.user.id
            except Exception as admin_err:
                err_str = str(admin_err).lower()
                if "already registered" in err_str or "unique" in err_str:
                    return False, "Email already registered."

        if not user_id:
            auth_client = get_supabase()
            res = auth_client.auth.sign_up({
                "email": email_clean,
                "password": password,
                "options": {
                    "data": {
                        "name": name,
                        "phone": phone,
                        "college": college,
                        "target_company": target_company,
                        "role": "user"
                    }
                }
            })
            if res and res.user:
                user_id = res.user.id
    except Exception as auth_err:
        err_str = str(auth_err).lower()
        if "already registered" in err_str or "duplicate" in err_str or "unique" in err_str:
            return False, "Email already registered."

    if not user_id:
        user_id = str(uuid.uuid4())

    # Synchronize profile into public.users
    try:
        sb.table("users").upsert({
            "id": user_id,
            "name": name,
            "email": email_clean,
            "password": _hash(password),
            "phone": phone,
            "college": college,
            "target_company": target_company,
            "role": "user"
        }).execute()
        return True, ""
    except Exception as exc:
        err = str(exc)
        if "unique" in err.lower() or "duplicate" in err.lower():
            return False, "Email already registered."
        return False, f"Database error: {err}"


def authenticate_user(email: str, password: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Authenticate user credentials using Supabase Auth or database hash match.
    Returns (user_profile_dict, "") on success, or (None, error_message) on failure.
    """
    email_clean = email.strip().lower()
    sb = _get_active_client()

    # 1. Try Supabase Auth password sign-in
    try:
        auth_client = get_supabase()
        res = auth_client.auth.sign_in_with_password({
            "email": email_clean,
            "password": password
        })
        if res and res.user:
            user_id = res.user.id
            p_res = sb.table("users").select("*").eq("id", user_id).execute()
            if p_res.data:
                return p_res.data[0], ""
            metadata = res.user.user_metadata or {}
            profile = {
                "id": user_id,
                "email": email_clean,
                "name": metadata.get("name", email_clean.split("@")[0]),
                "role": metadata.get("role", "user"),
                "phone": metadata.get("phone", ""),
                "college": metadata.get("college", ""),
                "target_company": metadata.get("target_company", "")
            }
            try:
                sb.table("users").upsert(profile).execute()
            except Exception:
                pass
            return profile, ""
    except Exception:
        pass

    # 2. Fallback to direct public.users lookup and password hash check
    try:
        res = sb.table("users").select("*").eq("email", email_clean).execute()
        if res.data:
            user = res.data[0]
            if check_password(password, user.get("password", "")):
                return user, ""
    except Exception:
        pass

    return None, "Invalid email or password."


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Find a user by their email address. Returns a dict or None."""
    sb = _get_active_client()
    try:
        res = sb.table("users").select("*").eq("email", email.strip().lower()).execute()
        return res.data[0] if res.data else None
    except Exception as exc:
        print(f"[Supabase] Error in get_user_by_email: {exc}")
        return None


def get_user_by_id(uid: Any) -> Optional[Dict[str, Any]]:
    """Find a user by their ID. Returns a dict or None."""
    sb = _get_active_client()
    try:
        res = sb.table("users").select("*").eq("id", str(uid)).execute()
        return res.data[0] if res.data else None
    except Exception as exc:
        print(f"[Supabase] Error in get_user_by_id: {exc}")
        return None


def get_all_users() -> List[Dict[str, Any]]:
    """Get all regular users (not admins) with their interview count and avg score."""
    sb = _get_active_client()
    try:
        u_res = sb.table("users").select("*").eq("role", "user").order("created_at", desc=True).execute()
        users = u_res.data or []

        i_res = sb.table("interviews").select("id, user_id, avg_score").execute()
        interviews = i_res.data or []

        user_iv_map: Dict[str, List[Any]] = {}
        for iv in interviews:
            u_id = str(iv.get("user_id"))
            if u_id not in user_iv_map:
                user_iv_map[u_id] = []
            user_iv_map[u_id].append(iv)

        for u in users:
            uid_str = str(u.get("id"))
            u_ivs = user_iv_map.get(uid_str, [])
            u["interview_count"] = len(u_ivs)
            scores = [float(iv["avg_score"]) for iv in u_ivs if iv.get("avg_score") is not None]
            u["avg_score"] = round(sum(scores) / len(scores), 1) if scores else None

        return users
    except Exception as exc:
        print(f"[Supabase] Error in get_all_users: {exc}")
        return []


def delete_user(uid: Any):
    """Delete a user and cascade all their interviews, resumes, and matches."""
    uid_str = str(uid)
    sb = _get_active_client()
    try:
        sb.table("users").delete().eq("id", uid_str).execute()
    except Exception as e:
        print(f"[Supabase] Error deleting public.users row: {e}")

    if SUPABASE_SERVICE_ROLE_KEY and hasattr(sb, "auth") and hasattr(sb.auth, "admin"):
        try:
            sb.auth.admin.delete_user(uid_str)
        except Exception as e:
            print(f"[Supabase] Note deleting auth user: {e}")


def verify_supabase_token(access_token: str) -> Optional[Dict[str, Any]]:
    """
    Validate a Supabase JWT access token and return user details.
    Returns user dict with id, email, user_metadata if valid, or None if invalid/expired.
    """
    if not access_token or not isinstance(access_token, str):
        return None
    token = access_token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        return None

    try:
        sb = _get_active_client()
        user_response = sb.auth.get_user(token)
        if not user_response or not getattr(user_response, "user", None):
            return None
        user = user_response.user

        user_id = str(getattr(user, "id", "") or (user.get("id") if isinstance(user, dict) else ""))
        email = getattr(user, "email", "") or (user.get("email") if isinstance(user, dict) else "")
        metadata = getattr(user, "user_metadata", {}) or (user.get("user_metadata", {}) if isinstance(user, dict) else {})
        if not isinstance(metadata, dict):
            metadata = {}

        return {
            "id": user_id,
            "email": email,
            "user_metadata": metadata,
            "raw_user": user
        }
    except Exception as exc:
        print(f"[Supabase Auth] Token verification failed: {exc}")
        return None


def sync_oauth_user(user_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Synchronize an authenticated OAuth user (e.g. from Google) into public.users.
    Extracts user id, email, and user_metadata (name, full_name, avatar_url),
    upserting into public.users without requiring a password.
    Returns the profile dictionary from public.users.
    """
    user_id = str(user_info.get("id", "")).strip()
    email = str(user_info.get("email", "")).strip().lower()
    metadata = user_info.get("user_metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    if not user_id or not email:
        return None

    # Derive display name from metadata or email prefix
    name = (
        metadata.get("full_name")
        or metadata.get("name")
        or metadata.get("given_name")
        or (email.split("@")[0].capitalize() if email else "User")
    )

    sb = _get_active_client()
    try:
        # Check if user already exists by id
        res = sb.table("users").select("*").eq("id", user_id).execute()
        if res.data:
            existing_user = res.data[0]
            updates = {}
            if not existing_user.get("name") and name:
                updates["name"] = name
            if updates:
                sb.table("users").update(updates).eq("id", user_id).execute()
                existing_user.update(updates)
            return existing_user

        # If not found by id, check if existing by email
        email_res = sb.table("users").select("*").eq("email", email).execute()
        if email_res.data:
            existing_by_email = email_res.data[0]
            return existing_by_email

        # User is brand new — create in public.users
        profile = {
            "id": user_id,
            "name": name,
            "email": email,
            "password": "",
            "phone": metadata.get("phone", ""),
            "college": metadata.get("college", ""),
            "target_company": metadata.get("target_company", ""),
            "role": metadata.get("role", "user")
        }
        sb.table("users").insert(profile).execute()
        return profile
    except Exception as exc:
        print(f"[Supabase Auth] Error syncing OAuth user {email}: {exc}")
        fallback = get_user_by_email(email)
        if fallback:
            return fallback
        return {
            "id": user_id,
            "name": name,
            "email": email,
            "role": "user"
        }



# ─────────────────────────────────────────────────────────────────────────────
# INTERVIEW HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def save_interview(user_id: Any, job_role: str, experience: str, test_type: str, avg_score: float, history: Any,
                   match_id=None, resume_id=None, jd_id=None,
                   feedback=None, rubric_scores=None, topics_evidence=None,
                   weak_areas=None, action_plan=None) -> int:
    """Save a completed interview with auditable rubrics and topic evidence to PostgreSQL. Returns new row ID."""
    sb = _get_active_client()

    payload = {
        "user_id": str(user_id),
        "job_role": job_role,
        "experience": experience,
        "test_type": test_type,
        "avg_score": float(avg_score) if avg_score is not None else None,
        "history": _ensure_list_or_dict(history, []),
        "match_id": int(match_id) if match_id is not None else None,
        "resume_id": int(resume_id) if resume_id is not None else None,
        "jd_id": int(jd_id) if jd_id is not None else None,
        "feedback": _ensure_list_or_dict(feedback, {}),
        "rubric_scores": _ensure_list_or_dict(rubric_scores, []),
        "topics_evidence": _ensure_list_or_dict(topics_evidence, []),
        "weak_areas": _ensure_list_or_dict(weak_areas, []),
        "action_plan": _ensure_list_or_dict(action_plan, [])
    }

    try:
        res = sb.table("interviews").insert(payload).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]["id"]
        return 0
    except Exception as exc:
        print(f"[Supabase] Error saving interview: {exc}")
        # Retry with minimal schema if optional columns are pending migration
        try:
            minimal_payload = {
                "user_id": str(user_id),
                "job_role": job_role,
                "experience": experience,
                "test_type": test_type,
                "avg_score": float(avg_score) if avg_score is not None else None,
                "history": _ensure_list_or_dict(history, [])
            }
            res = sb.table("interviews").insert(minimal_payload).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]["id"]
        except Exception as retry_exc:
            print(f"[Supabase] Retry minimal interview insert failed: {retry_exc}")
        return 0


def get_user_interviews(user_id: Any) -> List[Dict[str, Any]]:
    """Get all interviews for a user, newest first. Parses JSON fields."""
    sb = _get_active_client()
    try:
        res = sb.table("interviews").select("*").eq("user_id", str(user_id)).order("created_at", desc=True).execute()
        rows = res.data or []
        for r in rows:
            r["history"] = _ensure_list_or_dict(r.get("history"), [])
            r["feedback"] = _ensure_list_or_dict(r.get("feedback"), {})
            r["rubric_scores"] = _ensure_list_or_dict(r.get("rubric_scores"), [])
            r["topics_evidence"] = _ensure_list_or_dict(r.get("topics_evidence"), [])
            r["weak_areas"] = _ensure_list_or_dict(r.get("weak_areas"), [])
            r["action_plan"] = _ensure_list_or_dict(r.get("action_plan"), [])
            if r.get("created_at") and isinstance(r["created_at"], str):
                r["created_at"] = r["created_at"].replace("T", " ")[:19]
        return rows
    except Exception as exc:
        print(f"[Supabase] Error in get_user_interviews: {exc}")
        return []


def get_interview_report(interview_id: Any, user_id: Any = None) -> Optional[Dict[str, Any]]:
    """Retrieve full auditable report details for a specific interview session."""
    sb = _get_active_client()
    try:
        query = sb.table("interviews").select("*").eq("id", int(interview_id))
        if user_id is not None:
            query = query.eq("user_id", str(user_id))
        res = query.execute()
        if not res.data:
            return None

        report = res.data[0]
        report["history"] = _ensure_list_or_dict(report.get("history"), [])
        report["feedback"] = _ensure_list_or_dict(report.get("feedback"), {})
        report["rubric_scores"] = _ensure_list_or_dict(report.get("rubric_scores"), [])
        report["topics_evidence"] = _ensure_list_or_dict(report.get("topics_evidence"), [])
        report["weak_areas"] = _ensure_list_or_dict(report.get("weak_areas"), [])
        report["action_plan"] = _ensure_list_or_dict(report.get("action_plan"), [])

        if report.get("match_id"):
            report["match_data"] = get_match_by_id(report["match_id"], user_id)

        return report
    except Exception as exc:
        print(f"[Supabase] Error in get_interview_report: {exc}")
        return None


def get_user_performance_trends(user_id: Any) -> Dict[str, Any]:
    """Compute score progression timeline and weak area frequencies across multiple sessions."""
    sb = _get_active_client()
    try:
        res = sb.table("interviews").select("id, job_role, avg_score, created_at, weak_areas").eq(
            "user_id", str(user_id)
        ).order("created_at", desc=False).execute()
        rows = res.data or []

        timeline = []
        weakness_counter: Dict[str, int] = {}

        for r in rows:
            sc = r.get("avg_score") or 0
            created_str = r.get("created_at") or ""
            timeline.append({
                "interview_id": r["id"],
                "role": r.get("job_role", ""),
                "score": round(float(sc), 1),
                "date": created_str.replace("T", " ")[:10]
            })
            w_list = _ensure_list_or_dict(r.get("weak_areas"), [])
            for w in w_list:
                w_str = str(w).strip()
                if w_str:
                    weakness_counter[w_str] = weakness_counter.get(w_str, 0) + 1

        top_weaknesses = sorted(
            [{"area": k, "count": v} for k, v in weakness_counter.items()],
            key=lambda x: x["count"],
            reverse=True
        )[:5]

        return {
            "timeline": timeline,
            "total_sessions": len(timeline),
            "avg_score_overall": round(sum(t["score"] for t in timeline) / len(timeline), 1) if timeline else 0.0,
            "latest_score": timeline[-1]["score"] if timeline else 0.0,
            "frequent_weak_areas": top_weaknesses
        }
    except Exception as exc:
        print(f"[Supabase] Error in get_user_performance_trends: {exc}")
        return {
            "timeline": [],
            "total_sessions": 0,
            "avg_score_overall": 0.0,
            "latest_score": 0.0,
            "frequent_weak_areas": []
        }


def get_user_stats(user_id: Any) -> Dict[str, Any]:
    """Return total interview count, average score, and last interview date for a user."""
    sb = _get_active_client()
    try:
        res = sb.table("interviews").select("avg_score, created_at").eq("user_id", str(user_id)).order("created_at", desc=True).execute()
        rows = res.data or []

        total = len(rows)
        scores = [float(r["avg_score"]) for r in rows if r.get("avg_score") is not None]
        avg_score = round(sum(scores) / len(scores), 1) if scores else None
        last_interview = rows[0]["created_at"] if rows else None
        if last_interview and isinstance(last_interview, str):
            last_interview = last_interview.replace("T", " ")[:19]

        return {
            "total": total,
            "avg_score": avg_score,
            "last_interview": last_interview
        }
    except Exception as exc:
        print(f"[Supabase] Error in get_user_stats: {exc}")
        return {"total": 0, "avg_score": None, "last_interview": None}


# ─────────────────────────────────────────────────────────────────────────────
# SUPABASE STORAGE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def upload_file_to_storage(bucket_name: str, file_path_or_bytes: Any, destination_filename: str, content_type: str = None) -> Optional[str]:
    """
    Upload a document, image, or audio recording to Supabase Storage.
    Returns the permanent public URL on Supabase.
    """
    sb = _get_active_client()
    try:
        data = file_path_or_bytes
        if isinstance(file_path_or_bytes, str):
            if not os.path.exists(file_path_or_bytes):
                return None
            with open(file_path_or_bytes, "rb") as f:
                data = f.read()

        file_options = {"upsert": "true"}
        if content_type:
            file_options["content-type"] = content_type

        # Ensure bucket exists
        try:
            sb.storage.get_bucket(bucket_name)
        except Exception:
            try:
                sb.storage.create_bucket(bucket_name, options={"public": True})
            except Exception:
                pass

        sb.storage.from_(bucket_name).upload(destination_filename, data, file_options)
        public_url = sb.storage.from_(bucket_name).get_public_url(destination_filename)
        return public_url
    except Exception as exc:
        print(f"[Supabase Storage] Upload error to {bucket_name}/{destination_filename}: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# RESUME HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def save_resume(user_id: Any, filename: str, file_type: str, raw_text: str, analysis: dict, local_filepath: str = None) -> int:
    """Persist a parsed resume and upload file to Supabase Storage. Returns the new row ID."""
    sb = _get_active_client()

    file_url = ""
    if local_filepath and os.path.exists(local_filepath):
        storage_name = f"{user_id}/{filename}"
        mime = "application/pdf" if file_type.lower() == "pdf" else "application/octet-stream"
        file_url = upload_file_to_storage("resumes", local_filepath, storage_name, content_type=mime) or ""

    payload = {
        "user_id": str(user_id),
        "filename": filename,
        "file_type": file_type,
        "raw_text": raw_text,
        "file_url": file_url,
        "skills": _ensure_list_or_dict(analysis.get("skills"), []),
        "projects": _ensure_list_or_dict(analysis.get("projects"), []),
        "education": _ensure_list_or_dict(analysis.get("education"), []),
        "experience": _ensure_list_or_dict(analysis.get("experience"), []),
        "strengths": _ensure_list_or_dict(analysis.get("strengths"), []),
        "weaknesses": _ensure_list_or_dict(analysis.get("weaknesses"), []),
        "summary": analysis.get("summary", "")
    }

    try:
        res = sb.table("resumes").insert(payload).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]["id"]
        return 0
    except Exception as exc:
        print(f"[Supabase] Error in save_resume: {exc}")
        # Retry without optional file_url if pending migration
        try:
            payload.pop("file_url", None)
            res = sb.table("resumes").insert(payload).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]["id"]
        except Exception:
            pass
        return 0



def get_user_resume(user_id: Any) -> Optional[Dict[str, Any]]:
    """Return the most-recently uploaded resume for a user (or None)."""
    sb = _get_active_client()
    try:
        res = sb.table("resumes").select("*").eq("user_id", str(user_id)).order("created_at", desc=True).limit(1).execute()
        if not res.data:
            return None

        row = res.data[0]
        for field in ("skills", "projects", "education", "experience", "strengths", "weaknesses"):
            row[field] = _ensure_list_or_dict(row.get(field), [])
        return row
    except Exception as exc:
        print(f"[Supabase] Error in get_user_resume: {exc}")
        return None


def get_user_resumes(user_id: Any) -> List[Dict[str, Any]]:
    """Return all resumes for a user, newest first."""
    sb = _get_active_client()
    try:
        res = sb.table("resumes").select("id, filename, file_type, summary, created_at").eq(
            "user_id", str(user_id)
        ).order("created_at", desc=True).execute()
        rows = res.data or []
        for r in rows:
            if r.get("created_at") and isinstance(r["created_at"], str):
                r["created_at"] = r["created_at"].replace("T", " ")[:19]
        return rows
    except Exception as exc:
        print(f"[Supabase] Error in get_user_resumes: {exc}")
        return []


def get_resume_by_id(resume_id: Any, user_id: Any) -> Optional[Dict[str, Any]]:
    """Fetch a specific resume row (verifies ownership). Returns dict."""
    sb = _get_active_client()
    try:
        res = sb.table("resumes").select("*").eq("id", int(resume_id)).eq("user_id", str(user_id)).execute()
        if not res.data:
            return None
        row = res.data[0]
        for field in ("skills", "projects", "education", "experience", "strengths", "weaknesses"):
            row[field] = _ensure_list_or_dict(row.get(field), [])
        return row
    except Exception as exc:
        print(f"[Supabase] Error in get_resume_by_id: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# JOB DESCRIPTION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def save_jd(user_id: Any, jd_text: str, analysis: dict, local_filepath: str = None) -> int:
    """Persist a parsed job description and upload file to Supabase Storage if provided. Returns the new row ID."""
    sb = _get_active_client()

    file_url = ""
    if local_filepath and os.path.exists(local_filepath):
        storage_name = f"{user_id}/jd_{uuid.uuid4().hex[:8]}"
        file_url = upload_file_to_storage("documents", local_filepath, storage_name) or ""

    payload = {
        "user_id": str(user_id),
        "jd_text": jd_text,
        "file_url": file_url,
        "role": analysis.get("role", ""),
        "required_skills": _ensure_list_or_dict(analysis.get("required_skills"), []),
        "preferred_skills": _ensure_list_or_dict(analysis.get("preferred_skills"), []),
        "experience_required": analysis.get("experience_required", "")
    }

    try:
        res = sb.table("job_descriptions").insert(payload).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]["id"]
        return 0
    except Exception as exc:
        print(f"[Supabase] Error in save_jd: {exc}")
        try:
            payload.pop("file_url", None)
            res = sb.table("job_descriptions").insert(payload).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]["id"]
        except Exception:
            pass
        return 0



def get_jd_by_id(jd_id: Any, user_id: Any) -> Optional[Dict[str, Any]]:
    """Fetch a specific JD row (verifies ownership). Returns dict."""
    sb = _get_active_client()
    try:
        res = sb.table("job_descriptions").select("*").eq("id", int(jd_id)).eq("user_id", str(user_id)).execute()
        if not res.data:
            return None
        row = res.data[0]
        row["required_skills"] = _ensure_list_or_dict(row.get("required_skills"), [])
        row["preferred_skills"] = _ensure_list_or_dict(row.get("preferred_skills"), [])
        return row
    except Exception as exc:
        print(f"[Supabase] Error in get_jd_by_id: {exc}")
        return None


def get_user_jds(user_id: Any) -> List[Dict[str, Any]]:
    """Return all JDs for a user, newest first."""
    sb = _get_active_client()
    try:
        res = sb.table("job_descriptions").select("id, role, experience_required, created_at").eq(
            "user_id", str(user_id)
        ).order("created_at", desc=True).execute()
        rows = res.data or []
        for r in rows:
            if r.get("created_at") and isinstance(r["created_at"], str):
                r["created_at"] = r["created_at"].replace("T", " ")[:19]
        return rows
    except Exception as exc:
        print(f"[Supabase] Error in get_user_jds: {exc}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# RESUME x JD MATCH HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def save_match(user_id: Any, resume_id: Any, jd_id: Any, result: dict) -> int:
    """Persist a match result including NLP similarity and topic blueprint. Returns new row ID."""
    sb = _get_active_client()

    payload = {
        "user_id": str(user_id),
        "resume_id": int(resume_id),
        "jd_id": int(jd_id),
        "match_score": result.get("match_score", 0),
        "tfidf_score": result.get("tfidf_score", 0.0),
        "matched_skills": _ensure_list_or_dict(result.get("matched_skills"), []),
        "missing_skills": _ensure_list_or_dict(result.get("missing_skills"), []),
        "improvement_areas": _ensure_list_or_dict(result.get("improvement_areas"), []),
        "topics_evidence": _ensure_list_or_dict(result.get("topics_evidence"), []),
        "analytics_breakdown": _ensure_list_or_dict(result.get("analytics_breakdown"), {})
    }

    try:
        res = sb.table("resume_jd_matches").insert(payload).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]["id"]
        return 0
    except Exception as exc:
        print(f"[Supabase] Error saving match: {exc}")
        # Retry with minimal payload if advanced columns are not yet migrated
        try:
            minimal_payload = {
                "user_id": str(user_id),
                "resume_id": int(resume_id),
                "jd_id": int(jd_id),
                "match_score": result.get("match_score", 0),
                "matched_skills": _ensure_list_or_dict(result.get("matched_skills"), []),
                "missing_skills": _ensure_list_or_dict(result.get("missing_skills"), []),
                "improvement_areas": _ensure_list_or_dict(result.get("improvement_areas"), [])
            }
            res = sb.table("resume_jd_matches").insert(minimal_payload).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]["id"]
        except Exception as retry_exc:
            print(f"[Supabase] Retry minimal match insert failed: {retry_exc}")
        return 0


def get_match_by_id(match_id: Any, user_id: Any = None) -> Optional[Dict[str, Any]]:
    """Fetch a single match record with associated resume and JD details."""
    sb = _get_active_client()
    try:
        query = sb.table("resume_jd_matches").select(
            "*, resumes(filename, skills, projects, experience), job_descriptions(role, required_skills, preferred_skills, experience_required)"
        ).eq("id", int(match_id))
        if user_id is not None:
            query = query.eq("user_id", str(user_id))
        res = query.execute()

        if not res.data:
            # Fallback if join syntax is not supported
            query_plain = sb.table("resume_jd_matches").select("*").eq("id", int(match_id))
            if user_id is not None:
                query_plain = query_plain.eq("user_id", str(user_id))
            res_plain = query_plain.execute()
            if not res_plain.data:
                return None
            row = res_plain.data[0]
            # Fetch resume and JD separately
            r_res = sb.table("resumes").select("*").eq("id", row.get("resume_id")).execute()
            j_res = sb.table("job_descriptions").select("*").eq("id", row.get("jd_id")).execute()
            row["resumes"] = r_res.data[0] if r_res.data else {}
            row["job_descriptions"] = j_res.data[0] if j_res.data else {}
        else:
            row = res.data[0]

        d = dict(row)
        for field in ("matched_skills", "missing_skills", "improvement_areas", "topics_evidence"):
            d[field] = _ensure_list_or_dict(d.get(field), [])
        d["analytics_breakdown"] = _ensure_list_or_dict(d.get("analytics_breakdown"), {})

        resume_obj = d.pop("resumes", {}) or {}
        jd_obj = d.pop("job_descriptions", {}) or {}

        d["resume_filename"] = resume_obj.get("filename", "Resume")
        d["resume_skills"] = _ensure_list_or_dict(resume_obj.get("skills"), [])
        d["resume_projects"] = _ensure_list_or_dict(resume_obj.get("projects"), [])
        d["resume_experience"] = _ensure_list_or_dict(resume_obj.get("experience"), [])

        d["jd_role"] = jd_obj.get("role", "Role")
        d["jd_required"] = _ensure_list_or_dict(jd_obj.get("required_skills"), [])
        d["jd_preferred"] = _ensure_list_or_dict(jd_obj.get("preferred_skills"), [])
        d["jd_experience"] = jd_obj.get("experience_required", "")

        return d
    except Exception as exc:
        print(f"[Supabase] Error in get_match_by_id: {exc}")
        return None


def get_user_matches(user_id: Any) -> List[Dict[str, Any]]:
    """Return all match results for a user with resume filename, JD role, and topic counts."""
    sb = _get_active_client()
    try:
        res = sb.table("resume_jd_matches").select(
            "id, match_score, tfidf_score, matched_skills, missing_skills, improvement_areas, topics_evidence, analytics_breakdown, created_at, resume_id, jd_id, resumes(filename), job_descriptions(role)"
        ).eq("user_id", str(user_id)).order("created_at", desc=True).execute()

        rows = res.data or []
        result = []
        for row in rows:
            d = dict(row)
            d["matched_skills"] = _ensure_list_or_dict(d.get("matched_skills"), [])
            d["missing_skills"] = _ensure_list_or_dict(d.get("missing_skills"), [])
            d["improvement_areas"] = _ensure_list_or_dict(d.get("improvement_areas"), [])
            d["topics_evidence"] = _ensure_list_or_dict(d.get("topics_evidence"), [])
            d["analytics_breakdown"] = _ensure_list_or_dict(d.get("analytics_breakdown"), {})

            resume_obj = d.pop("resumes", None) or {}
            jd_obj = d.pop("job_descriptions", None) or {}

            d["resume_filename"] = resume_obj.get("filename") if isinstance(resume_obj, dict) else f"Resume #{d.get('resume_id')}"
            d["jd_role"] = jd_obj.get("role") if isinstance(jd_obj, dict) else f"Role #{d.get('jd_id')}"

            if d.get("created_at") and isinstance(d["created_at"], str):
                d["created_at"] = d["created_at"].replace("T", " ")[:19]
            result.append(d)
        return result
    except Exception as exc:
        print(f"[Supabase] Error in get_user_matches join, falling back: {exc}")
        try:
            res = sb.table("resume_jd_matches").select("*").eq("user_id", str(user_id)).order("created_at", desc=True).execute()
            rows = res.data or []
            result = []
            for row in rows:
                d = dict(row)
                d["matched_skills"] = _ensure_list_or_dict(d.get("matched_skills"), [])
                d["missing_skills"] = _ensure_list_or_dict(d.get("missing_skills"), [])
                d["improvement_areas"] = _ensure_list_or_dict(d.get("improvement_areas"), [])
                d["topics_evidence"] = _ensure_list_or_dict(d.get("topics_evidence"), [])
                d["analytics_breakdown"] = _ensure_list_or_dict(d.get("analytics_breakdown"), {})
                d["resume_filename"] = f"Resume #{d.get('resume_id')}"
                d["jd_role"] = f"Role #{d.get('jd_id')}"
                if d.get("created_at") and isinstance(d["created_at"], str):
                    d["created_at"] = d["created_at"].replace("T", " ")[:19]
                result.append(d)
            return result
        except Exception as fallback_exc:
            print(f"[Supabase] Fallback get_user_matches failed: {fallback_exc}")
            return []
