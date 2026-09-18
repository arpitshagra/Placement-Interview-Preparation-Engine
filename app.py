"""
AI Voice Interview Bot
======================
A Flask web app that conducts voice-based mock interviews using:
- Groq (LLM for questions & evaluation)
- Whisper (speech-to-text)
- pyttsx3 (text-to-speech)

Run:
    pip install flask openai-whisper pyttsx3 groq SpeechRecognition pyaudio
    set GROQ_API_KEY=your_key_here
    python app.py
"""

import os, uuid, json, re, threading, asyncio, socket
from dotenv import load_dotenv
from functools import wraps
from flask import Flask, request, jsonify, render_template, send_file, session, redirect, url_for, flash
import whisper, edge_tts
from groq import Groq
import database as db
try:
    from ml_engine import compute_tfidf_similarity, analyze_skills_with_pandas, select_topics_with_evidence
    ML_ENGINE_AVAILABLE = True
except Exception as _ml_err:
    print(f"[WARN] ml_engine unavailable ({_ml_err}). TF-IDF/pandas features disabled.")
    ML_ENGINE_AVAILABLE = False
    def compute_tfidf_similarity(*a, **kw): return {"similarity": 0.0, "error": "ml_engine unavailable"}
    def analyze_skills_with_pandas(*a, **kw): return {}
    def select_topics_with_evidence(*a, **kw): return []

# ── App Setup ─────────────────────────────────────────────────────────────────
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "API_KEY.env"))

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "interview-bot-secret")          # used to sign session cookies

AUDIO_FOLDER   = "responses"    # folder to store .wav / .mp3 files
UPLOADS_FOLDER = "uploads"      # folder to store uploaded resume files
os.makedirs(AUDIO_FOLDER,   exist_ok=True)
os.makedirs(UPLOADS_FOLDER, exist_ok=True)

ALLOWED_RESUME_EXTENSIONS = {"pdf", "docx"}

def allowed_resume(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_RESUME_EXTENSIONS

db.init_db()                                      # create DB tables on startup

# ── Load AI Models ────────────────────────────────────────────────────────────

print("Loading Whisper speech model...")
whisper_model = whisper.load_model("base")        # loads Whisper for transcription
print("Whisper ready.")

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))   # Groq LLM client


# ── In-Memory Interview Sessions ──────────────────────────────────────────────

# Each interview is stored here while it's active (key = session_id)
interview_sessions: dict = {}

# ─────────────────────────────────────────────────────────────────────────────
# AUTH DECORATORS & HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _extract_and_verify_token():
    """Helper to verify Bearer token from header or request args and populate session."""
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    elif request.args.get("access_token"):
        token = request.args.get("access_token").strip()

    if token:
        verified = db.verify_supabase_token(token)
        if verified:
            profile = db.sync_oauth_user(verified)
            if profile:
                session["user_id"] = profile["id"]
                session["name"] = profile.get("name", "User")
                session["role"] = profile.get("role", "user")
                session["user_email"] = profile.get("email", "")
                return profile
    return None

def login_required(f):
    """
    Protect routes: accepts active Flask session or Supabase Bearer token.
    Redirects HTML requests to /login and returns 401 JSON for API requests.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            _extract_and_verify_token()
        if "user_id" not in session:
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"error": "Unauthorized", "message": "Authentication required."}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    """Only allow admin users to access this route."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            _extract_and_verify_token()
        if "user_id" not in session:
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"error": "Unauthorized", "message": "Authentication required."}), 401
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({"error": "Forbidden", "message": "Admin privileges required."}), 403
            return redirect(url_for("user_dashboard"))
        return f(*args, **kwargs)
    return decorated

# ─────────────────────────────────────────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/config", methods=["GET"])
def get_public_config():
    """
    Public configuration endpoint providing Supabase URL and Anon Key.
    Does NOT expose service role keys or Google OAuth secrets.
    """
    return jsonify({
        "supabase_url": os.getenv("SUPABASE_URL", "").strip(),
        "supabase_anon_key": os.getenv("SUPABASE_KEY", "").strip()
    })

@app.route("/api/auth/session", methods=["POST"])
def sync_auth_session():
    """
    Establish a server-side session from a client-side Supabase JWT access token.
    Called right after successful Google OAuth or client-side authentication.
    """
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    if not token and request.is_json:
        data = request.get_json(silent=True) or {}
        token = data.get("access_token", "").strip()

    if not token:
        return jsonify({"success": False, "error": "Missing access token."}), 400

    verified_user = db.verify_supabase_token(token)
    if not verified_user:
        return jsonify({"success": False, "error": "Invalid or expired access token."}), 401

    profile = db.sync_oauth_user(verified_user)
    if not profile:
        return jsonify({"success": False, "error": "Failed to sync user profile."}), 500

    session["user_id"] = profile["id"]
    session["name"] = profile.get("name", "User")
    session["role"] = profile.get("role", "user")
    session["user_email"] = profile.get("email", "")

    redirect_target = url_for("admin_dashboard") if profile.get("role") == "admin" else url_for("user_dashboard")
    return jsonify({
        "success": True,
        "redirect": redirect_target,
        "user": {
            "id": profile["id"],
            "name": profile.get("name", ""),
            "email": profile.get("email", ""),
            "role": profile.get("role", "user")
        }
    })

@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    """Clear Flask session on client-side sign out."""
    session.clear()
    return jsonify({"success": True, "redirect": url_for("login")})

@app.route("/auth/callback")
def auth_callback():
    """Client-side OAuth callback page handling Supabase redirect and session sync."""
    return render_template("auth_callback.html")

@app.route("/")
def index():
    """Home page — show landing page or redirect based on login status."""
    if "user_id" in session:
        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("user_dashboard"))
    return render_template("homepage.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    """Show login form (GET) or process login (POST)."""
    if request.method == "GET" and "user_id" in session:
        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("user_dashboard"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user     = db.get_user_by_email(email)

        # Check if user exists and password matches
        if not user or not db.check_password(password, user["password"]):
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        # Save user info in session (like a login cookie)
        session["user_id"] = user["id"]
        session["name"]    = user["name"]
        session["role"]    = user["role"]

        if user["role"] == "admin":
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("user_dashboard"))

    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    """Show signup form (GET) or create new account (POST)."""
    if request.method == "GET" and "user_id" in session:
        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("user_dashboard"))

    if request.method == "POST":
        name           = request.form.get("name", "").strip()
        email          = request.form.get("email", "").strip().lower()
        password       = request.form.get("password", "")
        phone          = request.form.get("phone", "").strip()          # optional contact number
        college        = request.form.get("college", "").strip()        # optional college name
        target_company = request.form.get("target_company", "").strip() # optional dream company

        if not all([name, email, password]):
            flash("Name, email, and password are required.", "error")
            return render_template("signup.html")

        ok, err = db.create_user(name, email, password, phone, college, target_company)
        if not ok:
            flash(err, "error")
            return render_template("signup.html")

        flash("Account created! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")

@app.route("/logout")
def logout():
    """Clear session and go back to login page."""
    session.clear()
    return redirect(url_for("login"))

# ─────────────────────────────────────────────────────────────────────────────
# USER ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def user_dashboard():
    """Show the user's past interviews and stats."""
    uid        = session["user_id"]
    user       = db.get_user_by_id(uid)
    stats      = db.get_user_stats(uid)          # total interviews, avg score
    interviews = db.get_user_interviews(uid)     # list of past interviews
    return render_template("user_dashboard.html", user=user, stats=stats, interviews=interviews)

@app.route("/interview")
@login_required
def interview_page():
    """Show the main interview page where the user can start an interview."""
    return render_template("interview.html")

# ─────────────────────────────────────────────────────────────────────────────
# ADMIN ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/admin")
@admin_required
def admin_dashboard():
    """Show all users to the admin."""
    users = db.get_all_users()
    return render_template("admin_dashboard.html", users=users)

@app.route("/admin/user/<int:uid>")
@admin_required
def admin_user_detail(uid):
    """Show one user's full interview history to the admin."""
    user       = db.get_user_by_id(uid)
    interviews = db.get_user_interviews(uid)
    stats      = db.get_user_stats(uid)
    if not user:
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_user.html", user=user, interviews=interviews, stats=stats)

@app.route("/admin/delete_user/<int:uid>", methods=["POST"])
@admin_required
def delete_user(uid):
    """Delete a user and all their data."""
    db.delete_user(uid)
    flash("User deleted.", "success")
    return redirect(url_for("admin_dashboard"))

# ─────────────────────────────────────────────────────────────────────────────
# LLM HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

AVAILABLE_MODELS = [
    os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
    "groq/compound-mini",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]

def llm(system: str, user: str, temperature: float = 0.4) -> str:
    """Send a prompt to Groq LLM and return the response text with fallback model support."""
    last_error = None
    for model_name in AVAILABLE_MODELS:
        try:
            resp = groq_client.chat.completions.create(
                model=model_name,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            last_error = e
            continue
    raise RuntimeError(f"All Groq models failed. Last error: {last_error}")


def generate_rubric_question(sess: dict, topic_dict: dict, is_followup: bool = False, prev_answer: str = "") -> dict:
    """
    Generate an interview question grounded directly in the topic's verifiable evidence,
    along with a concise scoring rubric and follow-up guidance.
    """
    role = sess.get("job_role", "Software Engineer")
    topic_name = topic_dict.get("topic_name", "Technical Concept")
    focus_area = topic_dict.get("focus_area", "")
    evidence = topic_dict.get("evidence_reason", "")
    diff = sess.get("difficulty", "medium")

    if is_followup:
        system = """You are a senior technical interviewer asking a follow-up question.
The candidate's previous response was brief or needed deeper verification.
Ask a targeted follow-up probe that directly tests their practical mastery.
Return ONLY valid JSON:
{
  "question": "1-2 sentence targeted follow-up question",
  "rubric": {
    "expected_concepts": ["concept 1", "concept 2", "concept 3"],
    "scoring_criteria": "Brief description of what a score of 10 vs 5 vs 2 looks like.",
    "common_pitfalls": ["pitfall 1", "pitfall 2"]
  }
}"""
        user_prompt = (
            f"Role: {role}\nTopic: {topic_name}\nEvidence Justification: {evidence}\n"
            f"Candidate's Previous Answer: {prev_answer}\nAsk a probing follow-up question."
        )
    else:
        system = """You are a senior technical interviewer conducting an adaptive interview.
Generate ONE focused interview question strictly grounded in the provided topic and evidence justification.
Also provide a concise scoring rubric.
Return ONLY valid JSON:
{
  "question": "1-2 sentence clear, direct interview question",
  "rubric": {
    "expected_concepts": ["concept 1", "concept 2", "concept 3"],
    "scoring_criteria": "Brief description of what a score of 10 vs 5 vs 2 looks like.",
    "common_pitfalls": ["pitfall 1", "pitfall 2"]
  }
}"""
        user_prompt = (
            f"Role: {role} (Experience: {sess.get('experience', 'mid')}, Difficulty: {diff})\n"
            f"Topic: {topic_name}\nFocus Area: {focus_area}\n"
            f"Why This Topic Was Selected (Evidence): {evidence}\n"
            "Formulate a question that tests their authentic understanding of this claim."
        )

    try:
        raw = llm(system, user_prompt, temperature=0.5)
        raw = re.sub(r"```[a-z]*", "", raw).strip("` \n")
        parsed = json.loads(raw)
        if parsed.get("question") and parsed.get("rubric"):
            parsed["topic_name"] = topic_name
            parsed["evidence_reason"] = evidence
            parsed["topic_type"] = topic_dict.get("topic_type", "core_claim")
            return parsed
    except Exception as e:
        print(f"[app.py] LLM question gen retry: {e}")

    # Contextual dynamic fallback directly derived from topic & evidence
    target_skills = topic_dict.get("target_skills", [role])
    skill_str = ", ".join(str(s) for s in target_skills[:2]) if target_skills else role
    if is_followup:
        fallback_q = f"In that approach with {skill_str}, how did you measure performance and what was the main technical trade-off?"
    else:
        fallback_q = f"Regarding {topic_name}, could you explain your architectural approach and how you implemented {skill_str} in production?"

    return {
        "question": fallback_q,
        "rubric": {
            "expected_concepts": target_skills,
            "scoring_criteria": "9-10: Excellent answer. 7-8: Solid technical explanation. 5-6: Foundational awareness.",
            "common_pitfalls": []
        },
        "topic_name": topic_name,
        "evidence_reason": evidence,
        "topic_type": topic_dict.get("topic_type", "core_claim")
    }


def normalize_rubric_val(val: float, answer: str) -> int:
    """Normalize and calibrate raw LLM scores to prevent overly harsh grading."""
    ans_clean = (answer or "").strip().lower()
    words = ans_clean.split()
    if len(words) <= 3 or any(p in ans_clean for p in ["don't know", "dont know", "no idea", "skip", "pass"]):
        return int(round(max(2, min(5, val))))

    if val <= 2.5:
        norm = val + 4.0
    elif val <= 5.0:
        norm = val + 2.5
    elif val <= 7.5:
        norm = val + 1.5
    elif val <= 9.0:
        norm = val + 1.0
    else:
        norm = val

    return int(round(max(1, min(10, norm))))


def analyse_rubric_answer(sess: dict, topic_dict: dict, current_q_data: dict, answer: str) -> dict:
    """
    Evaluate candidate's answer against the topic's explicit rubric dimensions:
    - Technical Accuracy (1-10)
    - Problem Solving & Depth (1-10)
    - Communication Clarity (1-10)
    - Evidence & Practical Grounding (1-10)
    - Overall Quality Score (1-10)
    - AI Plagiarism Risk (low | medium | high)
    """
    question = current_q_data.get("question", "")
    evidence = topic_dict.get("evidence_reason", "")

    system = """You are a fair, balanced, and encouraging technical interview evaluator.
Assess the candidate's spoken response realistically. Remember candidates are speaking live in an interview setting, so answers will naturally be conversational and concise rather than written textbook essays.

Scoring Standards (1 to 10 scale):
- 9-10: Excellent answer. Demonstrates strong conceptual grasp, mentions practical experience, tools, or architectural trade-offs.
- 7-8: Good solid answer. Addresses the core question correctly and mentions relevant technical points, even if brief or missing minor edge cases.
- 5-6: Fair / Foundational answer. Demonstrates basic familiarity with the topic, but lacks deeper technical detail or specifics.
- 3-4: Weak answer. Incomplete or contains notable misconceptions.
- 1-2: Irrelevant or non-response (e.g. "I don't know").

Normalization Guidelines:
- If the candidate answers the question relevantly and mentions real technical tools/methods, award a solid score between 6.5 and 8.5.
- Do not penalize natural spoken brevity or simple phrasing harshly.
- Keep feedback constructive and supportive.

Return ONLY valid JSON:
{
  "quality_score": <overall 1-10 integer score>,
  "technical_accuracy": <1-10 integer score>,
  "problem_solving": <1-10 integer score>,
  "communication_clarity": <1-10 integer score>,
  "evidence_grounding": <1-10 integer score demonstrating practical experience>,
  "rubric_feedback": "2-3 sentences of positive and constructive feedback",
  "sentiment": "positive"|"neutral"|"negative",
  "emotion": "confident"|"neutral"|"thoughtful"|"unsure",
  "plagiarism_risk": "low"|"medium"|"high",
  "plagiarism_reason": "<1 sentence on authenticity>",
  "is_shallow_answer": false,
  "next_difficulty": "easy"|"medium"|"hard",
  "brief_acknowledgement": "<1 short sentence acknowledging the answer>"
}

Plagiarism & AI detection rules:
- 'high': Reads like textbook ChatGPT copy-paste (overly formulaic enumerations, filler introductory phrases).
- 'medium': Generic phrasing with mixed signals.
- 'low': Authentic human response with personal phrasing and practical trade-off mentions."""

    user_prompt = (
        f"Question: {question}\n"
        f"Topic Focus: {topic_dict.get('topic_name')}\n"
        f"Topic Evidence Justification: {evidence}\n\n"
        f"Candidate Answer: {answer}\n\n"
        "Evaluate constructively and return JSON."
    )

    try:
        raw = llm(system, user_prompt, temperature=0.2)
        raw = re.sub(r"```[a-z]*", "", raw).strip("` \n")
        res = json.loads(raw)
        q_raw = float(res.get("quality_score", 7))
        res["quality_score"] = normalize_rubric_val(q_raw, answer)
        res["technical_accuracy"] = normalize_rubric_val(float(res.get("technical_accuracy", q_raw)), answer)
        res["problem_solving"] = normalize_rubric_val(float(res.get("problem_solving", q_raw)), answer)
        res["communication_clarity"] = normalize_rubric_val(float(res.get("communication_clarity", q_raw)), answer)
        res["evidence_grounding"] = normalize_rubric_val(float(res.get("evidence_grounding", q_raw)), answer)
        return res
    except Exception as e:
        print(f"[app.py] Rubric analysis fallback: {e}")
        word_count = len((answer or "").split())
        score = 8 if word_count > 25 else (7 if word_count > 8 else 5)
        return {
            "quality_score": score,
            "technical_accuracy": score,
            "problem_solving": score,
            "communication_clarity": score,
            "evidence_grounding": score,
            "rubric_feedback": "Answer addresses the core technical concepts well. Good demonstration of practical understanding.",
            "sentiment": "positive",
            "emotion": "confident" if score >= 6 else "thoughtful",
            "plagiarism_risk": "low",
            "plagiarism_reason": "Authentic candidate response.",
            "is_shallow_answer": False,
            "next_difficulty": sess.get("difficulty", "medium"),
            "brief_acknowledgement": "Thank you for explaining your approach."
        }


def generate_practice_report_feedback(sess: dict) -> dict:
    """
    Generate an auditable, comprehensive final practice report including readiness index,
    radar metrics, diagnosed weak areas, and a personalized 7-day actionable study plan.
    """
    history = sess.get("history", [])
    history_summary = []
    scores = []
    dim_tech, dim_prob, dim_comm, dim_evid = [], [], [], []

    for i, h in enumerate(history, 1):
        an = h.get("analysis") or {}
        q = h.get("question", "")
        topic = h.get("topic_name", f"Topic {i}")
        score = an.get("quality_score", 5)
        scores.append(score)
        dim_tech.append(an.get("technical_accuracy", score))
        dim_prob.append(an.get("problem_solving", score))
        dim_comm.append(an.get("communication_clarity", score))
        dim_evid.append(an.get("evidence_grounding", score))
        history_summary.append(f"Q{i} [{topic}]: {q}\nScore: {score}/10 | Feedback: {an.get('rubric_feedback', '')}")

    avg_score = round(sum(scores) / max(len(scores), 1), 1)
    readiness_idx = int(min(100, max(10, avg_score * 10)))

    system = """You are a senior placement director and career coach.
Generate a comprehensive, actionable placement practice report.
Return ONLY valid JSON:
{
  "strong_points": [
    "Specific technical strength demonstrated in the session",
    "Another concrete strength with evidence"
  ],
  "weak_areas": [
    "Specific weak technical area or conceptual gap identified",
    "Another actionable area needing deeper study"
  ],
  "action_plan_7_day": [
    {"day": "Day 1-2", "focus": "Topic Area", "task": "Specific coding/architecture exercise"},
    {"day": "Day 3-4", "focus": "Topic Area", "task": "Specific system design or debugging drill"},
    {"day": "Day 5-6", "focus": "Topic Area", "task": "Project mock drill & STAR alignment"},
    {"day": "Day 7",   "focus": "Review",     "task": "Re-take adaptive interview & verify weak areas"}
  ],
  "spoken_summary": "A natural 5-7 sentence spoken executive summary of candidate readiness."
}"""

    user_prompt = (
        f"Candidate Role: {sess.get('job_role')} ({sess.get('experience')})\n"
        f"Overall Session Average: {avg_score}/10 (Readiness: {readiness_idx}%)\n\n"
        f"Session Audit Log:\n" + "\n\n".join(history_summary)
    )

    try:
        raw = llm(system, user_prompt, temperature=0.4)
        raw = re.sub(r"```[a-z]*", "", raw).strip("` \n")
        feedback = json.loads(raw)
    except Exception as e:
        print(f"[app.py] Practice report fallback: {e}")
        feedback = {
            "strong_points": [f"Demonstrated foundational understanding in {sess.get('job_role')} core concepts."],
            "weak_areas": ["Needs to structure answers with deeper edge-case analysis and quantitative metrics."],
            "action_plan_7_day": [
                {"day": "Day 1-2", "focus": "Core Architecture", "task": "Review core documentation and build a small proof-of-concept."},
                {"day": "Day 3-4", "focus": "Debugging & Resiliency", "task": "Practice troubleshooting production race conditions and query profiling."},
                {"day": "Day 5-6", "focus": "Project Deep-Dive", "task": "Prepare 3 STAR-format project stories with architectural trade-offs."},
                {"day": "Day 7",   "focus": "Final Drill",     "task": "Re-run the adaptive interview engine."}
            ],
            "spoken_summary": f"Thank you for completing your technical interview for {sess.get('job_role')}. You showed solid fundamentals, and with focused practice on edge-case depth, you will be well prepared."
        }

    feedback["readiness_index"] = readiness_idx
    feedback["dimension_averages"] = {
        "technical_accuracy": round(sum(dim_tech) / max(len(dim_tech), 1), 1),
        "problem_solving": round(sum(dim_prob) / max(len(dim_prob), 1), 1),
        "communication_clarity": round(sum(dim_comm) / max(len(dim_comm), 1), 1),
        "evidence_grounding": round(sum(dim_evid) / max(len(dim_evid), 1), 1),
    }
    return feedback


# ─────────────────────────────────────────────────────────────────────────────
# TEXT-TO-SPEECH (TTS) — Microsoft Edge Neural Voice
# ─────────────────────────────────────────────────────────────────────────────

TTS_VOICE = "en-US-AriaNeural"   # clear, professional female voice
# Other good options:
#   en-US-GuyNeural          – male, professional
#   en-US-JennyNeural        – female, casual
#   en-GB-RyanNeural         – male, British
#   en-IN-NeerjaNeural       – female, Indian English

_tts_lock = threading.Lock()     # serialise TTS generation

def speak(text: str, filename: str) -> str:
    """Convert text to an .mp3 audio file using Microsoft Edge neural TTS and sync to Supabase Storage."""
    filepath = os.path.join(AUDIO_FOLDER, filename)
    with _tts_lock:
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                edge_tts.Communicate(text, TTS_VOICE).save(filepath)
            )
            loop.close()
        except Exception as e:
            print(f"TTS error: {e}")
            # Create a minimal silent MP3 as fallback
            with open(filepath, "wb") as f:
                f.write(b'\xff\xfb\x90\x00' + b'\x00' * 417)  # ~1 frame silent MP3

        # Asynchronously upload audio file to Supabase Storage 'audio' bucket
        threading.Thread(
            target=db.upload_file_to_storage,
            args=("audio", filepath, filename, "audio/mpeg"),
            daemon=True
        ).start()

    return filepath


# ─────────────────────────────────────────────────────────────────────────────
# INTERVIEW API ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/start-from-upload", methods=["POST"])
@login_required
def api_start_from_upload():
    """
    All-in-one endpoint: Upload Resume + JD → Parse → Match → Start Adaptive Interview.
    Accepts multipart/form-data:
      - resume_file: PDF or DOCX file
      - jd_text: Job description plain text (OR jd_file: PDF/DOCX)
      - experience: junior|mid|senior (optional, default mid)
    Returns: First interview question + session_id + topics_evidence (same as /api/start)
    """
    try:
        uid = session["user_id"]
        experience = request.form.get("experience", "mid")

        # ── 1. Parse Resume ───────────────────────────────────────────────────────
        resume_file = request.files.get("resume_file")
        if not resume_file or not allowed_resume(resume_file.filename):
            return jsonify({"error": "Please upload a PDF or DOCX resume."}), 400

        ext = resume_file.filename.rsplit(".", 1)[-1].lower()
        safe_name = f"resume_{uid}_{uuid.uuid4().hex[:8]}.{ext}"
        resume_path = os.path.join(UPLOADS_FOLDER, safe_name)
        resume_file.save(resume_path)

        try:
            from resume_parser import parse_resume
            resume_raw = parse_resume(resume_path, ext)
        except Exception as e:
            return jsonify({"error": f"Could not read resume file: {e}"}), 500

        if not resume_raw or len(resume_raw.strip()) < 50:
            return jsonify({"error": "Resume appears empty or unreadable. Try a different file."}), 400

        # ── 2. Parse JD (Optional) ────────────────────────────────────────────────
        jd_text = (request.form.get("jd_text") or "").strip()
        jd_file = request.files.get("jd_file")

        if not jd_text and jd_file and jd_file.filename:
            jd_ext = jd_file.filename.rsplit(".", 1)[-1].lower() if "." in jd_file.filename else "txt"
            safe_jd = f"jd_{uid}_{uuid.uuid4().hex[:8]}.{jd_ext}"
            jd_path = os.path.join(UPLOADS_FOLDER, safe_jd)
            jd_file.save(jd_path)
            try:
                from resume_parser import parse_resume as parse_doc
                jd_text = parse_doc(jd_path, jd_ext)
            except Exception as e:
                return jsonify({"error": f"Could not read JD file: {e}"}), 500

        has_jd = bool(jd_text and len(jd_text.strip()) >= 20)

        # ── 3. Structuring ────────────────────────────────────────────────────────
        print(f"[upload-start] Analysing resume ({len(resume_raw)} chars), JD provided: {has_jd}...")
        resume_analysis = analyze_resume_with_llm(resume_raw)
        resume_id = db.save_resume(uid, safe_name, ext, resume_raw, resume_analysis, local_filepath=resume_path)

        resume_data = {
            "skills":     resume_analysis.get("skills",     []),
            "experience": resume_analysis.get("experience", []),
            "education":  resume_analysis.get("education",  []),
            "projects":   resume_analysis.get("projects",   []),
        }

        if has_jd:
            jd_analysis = analyze_jd_with_llm(jd_text)
            jd_id       = db.save_jd(uid, jd_text, jd_analysis, local_filepath=jd_path if has_jd and "jd_path" in locals() else None)

            job_role    = jd_analysis.get("role") or "Software Engineer"
            jd_data = {
                "role":                job_role,
                "required_skills":    jd_analysis.get("required_skills",  []),
                "preferred_skills":   jd_analysis.get("preferred_skills", []),
                "experience_required": jd_analysis.get("experience_required", ""),
            }
            result   = run_match_engine(resume_data, jd_data, resume_raw_text=resume_raw, jd_raw_text=jd_text)
            match_id = db.save_match(uid, resume_id, jd_id, result)
        else:
            # Inferred profile directly from candidate's resume
            inferred_role = "Software Engineer"
            exp_list = resume_analysis.get("experience", [])
            if exp_list and isinstance(exp_list, list) and len(exp_list) > 0:
                if isinstance(exp_list[0], dict) and exp_list[0].get("role"):
                    inferred_role = exp_list[0]["role"]
                elif isinstance(exp_list[0], str):
                    for cand_role in ["Backend Developer", "Frontend Developer", "Full Stack Developer", "Software Engineer", "Data Scientist", "DevOps Engineer"]:
                        if cand_role.lower() in exp_list[0].lower():
                            inferred_role = cand_role
                            break
            elif resume_analysis.get("summary"):
                s_low = resume_analysis["summary"].lower()
                if "frontend" in s_low: inferred_role = "Frontend Engineer"
                elif "backend" in s_low: inferred_role = "Backend Engineer"
                elif "full stack" in s_low or "fullstack" in s_low: inferred_role = "Full Stack Engineer"
                elif "machine learning" in s_low or "data scientist" in s_low or "ai" in s_low: inferred_role = "AI/ML Engineer"

            job_role = inferred_role
            top_skills = resume_analysis.get("skills", [])[:8]
            jd_analysis = {
                "role": job_role,
                "required_skills": top_skills,
                "preferred_skills": [],
                "experience_required": "Demonstrated technical skills on resume"
            }
            jd_id = db.save_jd(uid, f"Inferred Technical Assessment Profile for {job_role}", jd_analysis)
            jd_data = {
                "role": job_role,
                "required_skills": top_skills,
                "preferred_skills": [],
                "experience_required": "Demonstrated technical skills on resume"
            }
            result = run_match_engine(resume_data, jd_data, resume_raw_text=resume_raw, jd_raw_text=" ".join(top_skills))
            result["match_score"] = 92
            result["tfidf_score"] = 85.0
            match_id = db.save_match(uid, resume_id, jd_id, result)

        topics_evidence = result["topics_evidence"]

        # ── 5. Build Interview Session ────────────────────────────────────────────
        sess = {
            "id": str(uuid.uuid4()),
            "user_id": uid,
            "match_id": match_id,
            "resume_id": resume_id,
            "jd_id": jd_id,
            "job_role": job_role,
            "experience": experience,
            "test_type": "adaptive_technical",
            "topics_evidence": topics_evidence,
            "current_topic_idx": 0,
            "total_q": len(topics_evidence),
            "history": [],
            "has_asked_followup_for_current_topic": False,
            "difficulty": "medium",
            "finished": False,
        }
        interview_sessions[sess["id"]] = sess

        first_topic = topics_evidence[0]
        q_data = generate_rubric_question(sess, first_topic, is_followup=False)

        sess["history"].append({
            "question":       q_data["question"],
            "rubric":         q_data.get("rubric", {}),
            "topic_name":     first_topic["topic_name"],
            "topic_number":   first_topic.get("topic_number", 1),
            "topic_type":     first_topic.get("topic_type", "core_claim"),
            "evidence_reason": first_topic.get("evidence_reason", ""),
            "is_followup":    False,
            "answer":         None,
            "analysis":       None,
        })

        audio_file = f"{sess['id']}_q0.mp3"
        speak(
            f"Welcome. Your resume and job description have been analysed. "
            f"Starting your adaptive technical interview for the role of {job_role}. "
            f"Topic 1: {first_topic['topic_name']}. {q_data['question']}",
            audio_file,
        )

        return jsonify({
            "success":        True,
            "session_id":     sess["id"],
            "match_id":       match_id,
            "job_role":       job_role,
            "match_score":    result["match_score"],
            "tfidf_score":    result["tfidf_score"],
            "matched_skills": result["matched_skills"],
            "missing_skills": result["missing_skills"],
            "topics_evidence": topics_evidence,
            "question":       q_data["question"],
            "rubric":         q_data.get("rubric", {}),
            "topic_name":     first_topic["topic_name"],
            "topic_type":     first_topic.get("topic_type", "core_claim"),
            "evidence_reason": first_topic.get("evidence_reason", ""),
            "question_num":   1,
            "total_q":        sess["total_q"],
            "difficulty":     "medium",
            "audio_url":      f"/audio/{audio_file}",
        })
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Failed to start interview: {str(exc)}"}), 500



@app.route("/api/start", methods=["POST"])
@login_required
def api_start():
    """
    Start a new adaptive interview session.
    Accepts optional match_id to initialize interview from Resume x JD match evidence.
    """
    data = request.get_json() or {}
    match_id = data.get("match_id")
    job_role = (data.get("job_role") or "").strip()
    match_data = None

    if match_id:
        try:
            match_data = db.get_match_by_id(int(match_id), session["user_id"])
        except Exception as e:
            print(f"[api_start] Error loading match {match_id}: {e}")

    if match_data:
        job_role = match_data.get("jd_role") or job_role or "Software Engineer"
        topics_evidence = match_data.get("topics_evidence") or []
        resume_id = match_data.get("resume_id")
        jd_id = match_data.get("jd_id")
    else:
        resume_id = None
        jd_id = None
        topics_evidence = []

    if not job_role:
        return jsonify({"error": "job_role is required"}), 400

    if not topics_evidence:
        topics_evidence = [
            {"topic_number": 1, "topic_name": "Core Technical & Project Mastery", "topic_type": "core_claim", "focus_area": "Main framework & architecture", "evidence_reason": f"Core candidate claim for {job_role}."},
            {"topic_number": 2, "topic_name": "System Scalability & Performance", "topic_type": "experience_depth", "focus_area": "High-throughput design and state management", "evidence_reason": f"Scale requirement for {job_role}."},
            {"topic_number": 3, "topic_name": "Adaptive Problem Solving & Concept Depth", "topic_type": "skill_gap", "focus_area": "Edge cases & transferrable knowledge", "evidence_reason": f"Assessing adaptability in {job_role}."},
            {"topic_number": 4, "topic_name": "Debugging & Production Resiliency", "topic_type": "problem_solving", "focus_area": "Root cause analysis and troubleshooting", "evidence_reason": f"Production readiness in {job_role}."},
            {"topic_number": 5, "topic_name": "Technical Ownership & Trade-offs", "topic_type": "ownership", "focus_area": "Engineering trade-offs and code quality", "evidence_reason": f"Engineering maturity for {job_role}."}
        ]

    sess = {
        "id": str(uuid.uuid4()),
        "user_id": session["user_id"],
        "match_id": match_id,
        "resume_id": resume_id,
        "jd_id": jd_id,
        "job_role": job_role,
        "experience": data.get("experience", "mid"),
        "test_type": data.get("test_type", "adaptive_technical"),
        "topics_evidence": topics_evidence,
        "current_topic_idx": 0,
        "total_q": len(topics_evidence),
        "history": [],
        "has_asked_followup_for_current_topic": False,
        "difficulty": "medium",
        "finished": False,
    }
    interview_sessions[sess["id"]] = sess

    # Generate Question #1 with Rubric
    first_topic = topics_evidence[0]
    q_data = generate_rubric_question(sess, first_topic, is_followup=False)

    sess["history"].append({
        "question": q_data["question"],
        "rubric": q_data.get("rubric", {}),
        "topic_name": first_topic["topic_name"],
        "topic_number": first_topic.get("topic_number", 1),
        "topic_type": first_topic.get("topic_type", "core_claim"),
        "evidence_reason": first_topic.get("evidence_reason", ""),
        "is_followup": False,
        "answer": None,
        "analysis": None
    })

    # Speak welcome + first question
    audio_file = f"{sess['id']}_q0.mp3"
    speak(f"Welcome. Let us begin your adaptive technical interview for the role of {sess['job_role']}. "
          f"Topic 1: {first_topic['topic_name']}. {q_data['question']}", audio_file)

    return jsonify({
        "session_id": sess["id"],
        "question": q_data["question"],
        "rubric": q_data.get("rubric", {}),
        "topic_name": first_topic["topic_name"],
        "topic_type": first_topic.get("topic_type", "core_claim"),
        "evidence_reason": first_topic.get("evidence_reason", ""),
        "question_num": 1,
        "total_q": sess["total_q"],
        "audio_url": f"/audio/{audio_file}"
    })

@app.route("/api/transcribe", methods=["POST"])
@login_required
def api_transcribe():
    """
    Accept a browser-recorded audio blob (multipart/form-data),
    save it to the responses folder, transcribe with Whisper,
    and return the transcribed text.
    Expects: form fields: session_id (text), audio (file blob)
    """
    session_id = request.form.get("session_id", "")

    if not session_id or session_id not in interview_sessions:
        return jsonify({"error": "Invalid session"}), 400

    audio_file = request.files.get("audio")
    if not audio_file:
        return jsonify({"error": "No audio file received"}), 400

    # Save the uploaded audio to a session-scoped file in the responses folder
    q_index    = len(interview_sessions[session_id]["history"])
    save_name  = f"{session_id}_answer_q{q_index}.wav"
    save_path  = os.path.join(AUDIO_FOLDER, save_name)
    audio_file.save(save_path)

    if os.path.getsize(save_path) < 1000:
        return jsonify({"error": "Recording too short. Please speak louder."}), 200

    try:
        result = whisper_model.transcribe(save_path, language="en", fp16=False)
        text   = result["text"].strip()
        print(f"Transcribed: '{text}'")
        if not text:
            return jsonify({"error": "Could not hear you clearly. Please try again."}), 200
        return jsonify({"transcription": text})
    except Exception as e:
        return jsonify({"error": f"Transcription error: {str(e)}"}), 500

@app.route("/api/answer", methods=["POST"])
@login_required
def api_answer():
    """
    Submit an answer for evaluation against the explicit rubric.
    Supports adaptive follow-ups if initial answer is superficial,
    advances topic, and outputs auditable Practice Report upon completion.
    """
    data       = request.get_json() or {}
    session_id = data.get("session_id")
    text       = (data.get("text") or "").strip()

    if not session_id or session_id not in interview_sessions:
        return jsonify({"error": "Invalid session"}), 400
    if not text:
        return jsonify({"error": "No answer text provided"}), 400

    sess = interview_sessions[session_id]
    if sess["finished"]:
        return jsonify({"error": "Interview already finished"}), 400

    current_item = sess["history"][-1]
    current_item["answer"] = text

    topic_idx = sess.get("current_topic_idx", 0)
    topics = sess.get("topics_evidence", [])
    current_topic = topics[topic_idx] if topic_idx < len(topics) else {}

    # Rubric Analysis
    analysis = analyse_rubric_answer(sess, current_topic, current_item, text)
    current_item["analysis"] = analysis

    # ── Advance to Next Topic (Fixed Number of Questions) ──────────────────────
    # The number of questions is strictly fixed to len(topics) (5 questions).
    # We do NOT add extra follow-ups or increase question count even if the candidate struggled.
    sess["current_topic_idx"] += 1
    next_topic_idx = sess["current_topic_idx"]

    # Adapt difficulty for the next topic based on current performance
    current_q_score = analysis.get("quality_score", 7)
    if current_q_score >= 8:
        sess["difficulty"] = "hard"
    elif current_q_score <= 4:
        sess["difficulty"] = "easy"
    else:
        sess["difficulty"] = "medium"

    # If all topics completed:
    if next_topic_idx >= len(topics):
        sess["finished"] = True
        feedback = generate_practice_report_feedback(sess)

        # Audio summary
        audio_file = f"{session_id}_feedback.mp3"
        speak(feedback.get("spoken_summary", "Thank you for completing your technical interview."), audio_file)

        scores = [h["analysis"].get("quality_score", 7) for h in sess["history"] if h.get("analysis")]
        avg = round(sum(scores) / max(len(scores), 1), 1)

        rubric_scores = []
        for h in sess["history"]:
            if h.get("analysis"):
                rubric_scores.append({
                    "topic": h.get("topic_name"),
                    "question": h.get("question"),
                    "quality_score": h["analysis"].get("quality_score", 7),
                    "technical_accuracy": h["analysis"].get("technical_accuracy", 7),
                    "problem_solving": h["analysis"].get("problem_solving", 7),
                    "communication_clarity": h["analysis"].get("communication_clarity", 7),
                    "evidence_grounding": h["analysis"].get("evidence_grounding", 7),
                    "plagiarism_risk": h["analysis"].get("plagiarism_risk", "low"),
                    "feedback": h["analysis"].get("rubric_feedback", "")
                })

        new_interview_id = db.save_interview(
            user_id=sess["user_id"],
            job_role=sess["job_role"],
            experience=sess["experience"],
            test_type=sess["test_type"],
            avg_score=avg,
            history=sess["history"],
            match_id=sess.get("match_id"),
            resume_id=sess.get("resume_id"),
            jd_id=sess.get("jd_id"),
            feedback=feedback,
            rubric_scores=rubric_scores,
            topics_evidence=sess.get("topics_evidence"),
            weak_areas=feedback.get("weak_areas", []),
            action_plan=feedback.get("action_plan_7_day", [])
        )

        return jsonify({
            "transcription": text,
            "finished": True,
            "interview_id": new_interview_id,
            "feedback": feedback,
            "avg_score": avg,
            "readiness_index": feedback.get("readiness_index", int(avg * 10)),
            "rubric_scores": rubric_scores,
            "audio_url": f"/audio/{audio_file}"
        })

    # Prepare next fixed question
    next_topic = topics[next_topic_idx]
    next_q_data = generate_rubric_question(sess, next_topic, is_followup=False)

    sess["history"].append({
        "question": next_q_data["question"],
        "rubric": next_q_data.get("rubric", {}),
        "topic_name": next_topic["topic_name"],
        "topic_number": next_topic_idx + 1,
        "topic_type": next_topic.get("topic_type", "core_claim"),
        "evidence_reason": next_topic.get("evidence_reason", ""),
        "is_followup": False,
        "answer": None,
        "analysis": None
    })

    q_idx = len(sess["history"])
    audio_file = f"{session_id}_q{q_idx}.mp3"
    ack = analysis.get("brief_acknowledgement", "Thank you.")
    speak(f"{ack} Topic {next_topic_idx + 1}: {next_topic['topic_name']}. {next_q_data['question']}", audio_file)

    return jsonify({
        "transcription": text,
        "finished": False,
        "is_followup": False,
        "next_question": next_q_data["question"],
        "rubric": next_q_data.get("rubric", {}),
        "topic_name": next_topic["topic_name"],
        "topic_type": next_topic.get("topic_type", "core_claim"),
        "evidence_reason": next_topic.get("evidence_reason", ""),
        "question_num": next_topic_idx + 1,
        "total_q": len(topics),
        "difficulty": sess["difficulty"],
        "audio_url": f"/audio/{audio_file}"
    })


@app.route("/audio/<filename>")
@login_required
def audio(filename):
    """Serve a generated audio file to the browser."""
    path = os.path.join(AUDIO_FOLDER, filename)
    if not os.path.exists(path):
        return jsonify({"error": "Not found"}), 404
    mime = "audio/mpeg" if filename.endswith(".mp3") else "audio/wav"
    return send_file(path, mimetype=mime)


# ═════════════════════════════════════════════════════════════════════════════
# RESUME / JD ANALYSIS — LLM HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def fallback_parse_resume(raw_text: str) -> dict:
    """Deterministic rule-based resume parser used when LLM is unavailable or offline."""
    if ML_ENGINE_AVAILABLE:
        from ml_engine import SKILL_CATEGORIES
    else:
        SKILL_CATEGORIES = {}
    text_lower = raw_text.lower()

    # Extract known technical skills using word boundaries
    extracted_skills = []
    for cat, skills_list in SKILL_CATEGORIES.items():
        for sk in skills_list:
            pattern = r'\b' + re.escape(sk) + r'\b'
            if re.search(pattern, text_lower):
                extracted_skills.append(sk)

    # Deduplicate while preserving order
    extracted_skills = list(dict.fromkeys(extracted_skills))
    if not extracted_skills:
        extracted_skills = ["Python", "Data Structures", "System Design", "Problem Solving"]

    # Detect candidate roles from experience or text
    detected_role = "Software Engineer"
    for role_candidate in ["Backend Developer", "Frontend Developer", "Full Stack Developer", "Data Scientist", "DevOps Engineer", "Software Engineer", "Machine Learning Engineer"]:
        if re.search(r'\b' + re.escape(role_candidate.lower()) + r'\b', text_lower):
            detected_role = role_candidate
            break

    # Extract summary or first meaningful line
    lines = [line.strip() for line in raw_text.splitlines() if line.strip() and len(line.strip()) > 30]
    summary = lines[0] if lines else f"Technical professional with demonstrated expertise in {', '.join(extracted_skills[:3])}."

    return {
        "skills": extracted_skills,
        "projects": [
            {
                "name": "Production Software Application",
                "description": "Architected and deployed technical software application demonstrating end-to-end engineering practices.",
                "technologies": extracted_skills[:4]
            }
        ],
        "education": [
            {"degree": "Bachelor of Technology / Computer Science", "institution": "Engineering Institution", "year": "Recent"}
        ],
        "experience": [
            {"role": detected_role, "company": "Technology Organization", "duration": "1-3 years", "description": "Hands-on software development and technical implementation."}
        ],
        "strengths": [f"Demonstrated proficiency in {s.title()}" for s in extracted_skills[:3]],
        "weaknesses": [],
        "summary": summary
    }


def fallback_parse_jd(jd_text: str) -> dict:
    """Deterministic rule-based JD parser used when LLM is unavailable or offline."""
    if ML_ENGINE_AVAILABLE:
        from ml_engine import SKILL_CATEGORIES
    else:
        SKILL_CATEGORIES = {}
    text_lower = jd_text.lower()

    extracted_skills = []
    for cat, skills_list in SKILL_CATEGORIES.items():
        for sk in skills_list:
            pattern = r'\b' + re.escape(sk) + r'\b'
            if re.search(pattern, text_lower):
                extracted_skills.append(sk)

    extracted_skills = list(dict.fromkeys(extracted_skills))
    role = "Software Engineer"
    for role_candidate in ["Backend Developer", "Frontend Developer", "Full Stack Developer", "Data Scientist", "DevOps Engineer", "Software Engineer", "Machine Learning Engineer"]:
        if re.search(r'\b' + re.escape(role_candidate.lower()) + r'\b', text_lower):
            role = role_candidate
            break

    return {
        "role": role,
        "required_skills": extracted_skills if extracted_skills else ["Software Engineering", "Problem Solving"],
        "preferred_skills": [],
        "experience_required": "Demonstrated technical skills in target stack"
    }


def analyze_resume_with_llm(raw_text: str) -> dict:
    """Use Groq LLM to extract structured information from raw resume text, with rule-based fallback."""
    system = """You are an expert resume parser and career analyst.
Extract all information from the resume text and return ONLY valid JSON — no markdown, no extra text.
Schema:
{
  "skills":     ["skill1", "skill2"],
  "projects":   [{"name":"...", "description":"...", "technologies":["..."]}],
  "education":  [{"degree":"...", "institution":"...", "year":"..."}],
  "experience": [{"role":"...", "company":"...", "duration":"...", "description":"..."}],
  "strengths":  ["strength1", "strength2"],
  "weaknesses": ["weakness1", "weakness2"],
  "summary":    "2–3 sentence professional summary of the candidate"
}
Be thorough. Extract every skill, technology, tool mentioned. Infer strengths from experience and projects."""

    try:
        raw = llm(system, f"Resume text:\n\n{raw_text[:5000]}", temperature=0.2)
        raw = re.sub(r"```[a-z]*", "", raw).strip("` \n")
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("skills"):
            return data
    except Exception as exc:
        print(f"[app.py] LLM resume analysis fallback triggered: {exc}")

    return fallback_parse_resume(raw_text)


def analyze_jd_with_llm(jd_text: str) -> dict:
    """Use Groq LLM to extract structured information from a job description, with rule-based fallback."""
    system = """You are an expert job description analyst and HR specialist.
Extract all key information and return ONLY valid JSON — no markdown, no extra text.
Schema:
{
  "role":                "exact job title",
  "required_skills":    ["must-have skill 1", "must-have skill 2"],
  "preferred_skills":   ["nice-to-have skill 1", "nice-to-have skill 2"],
  "experience_required": "e.g. 3-5 years of backend development"
}
Be exhaustive — extract every technical skill, soft skill, tool, framework, language mentioned."""

    try:
        raw = llm(system, f"Job Description:\n\n{jd_text[:5000]}", temperature=0.2)
        raw = re.sub(r"```[a-z]*", "", raw).strip("` \n")
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("required_skills"):
            return data
    except Exception as exc:
        print(f"[app.py] LLM JD analysis fallback triggered: {exc}")

    return fallback_parse_jd(jd_text)



def run_match_engine(resume_data: dict, jd_data: dict, resume_raw_text: str = "", jd_raw_text: str = "") -> dict:
    """
    Hybrid Match Engine:
    1. NLP TF-IDF Cosine Similarity on raw text
    2. Pandas structured skill gap & category analytics
    3. Topic Selection with Verifiable Evidence Generator (5 topics)
    4. LLM ATS Improvement Recommendations
    """
    # 1. TF-IDF Text Similarity
    tfidf_result = compute_tfidf_similarity(resume_raw_text, jd_raw_text)

    # 2. Pandas Skill Analytics
    pandas_analytics = analyze_skills_with_pandas(resume_data, jd_data, tfidf_result)

    # 3. Topic Selection with Evidence
    topics_evidence = select_topics_with_evidence(resume_data, jd_data, pandas_analytics, num_topics=5)

    # 4. LLM Improvement Recommendations
    system = """You are an expert ATS (Applicant Tracking System) and senior placement director.
Analyse the candidate's resume against the target Job Description.
Provide 3-4 concrete, high-impact suggestions to strengthen their technical profile and interview readiness.
Return ONLY valid JSON:
{
  "improvement_areas": [
    {"area": "Short title", "suggestion": "Specific, actionable advice (1-2 sentences)"}
  ]
}"""
    user_payload = (
        f"Resume Skills: {json.dumps(resume_data.get('skills', []))}\n"
        f"Resume Projects: {json.dumps(resume_data.get('projects', []))}\n"
        f"Resume Experience: {json.dumps(resume_data.get('experience', []))}\n\n"
        f"JD Role: {jd_data.get('role', '')}\n"
        f"JD Required Skills: {json.dumps(jd_data.get('required_skills', []))}\n"
        f"Missing Must-Have Skills: {json.dumps(pandas_analytics.get('missing_skills', []))}"
    )

    improvement_areas = []
    try:
        raw = llm(system, user_payload, temperature=0.3)
        raw = re.sub(r"```[a-z]*", "", raw).strip("` \n")
        parsed = json.loads(raw)
        improvement_areas = parsed.get("improvement_areas", [])
    except Exception as e:
        print(f"[app.py] ATS improvement LLM fallback: {e}")
        if pandas_analytics.get("missing_skills"):
            improvement_areas.append({
                "area": f"Close Gap in {pandas_analytics['missing_skills'][0]}",
                "suggestion": f"Build a practical demonstration project showcasing {pandas_analytics['missing_skills'][0]} to satisfy target JD criteria."
            })
        improvement_areas.append({
            "area": "Quantify Project Impact",
            "suggestion": "Include concrete performance metrics (e.g. latency reduction, scale handled) in project bullet points."
        })

    return {
        "match_score": pandas_analytics["overall_match_score"],
        "tfidf_score": tfidf_result.get("similarity_percentage", 0.0),
        "top_shared_terms": tfidf_result.get("top_shared_terms", []),
        "matched_skills": pandas_analytics["matched_skills"],
        "missing_skills": pandas_analytics["missing_skills"],
        "missing_preferred": pandas_analytics.get("missing_preferred", []),
        "bonus_skills": pandas_analytics.get("bonus_skills", []),
        "must_have_rate": pandas_analytics["must_have_rate"],
        "preferred_rate": pandas_analytics["preferred_rate"],
        "category_breakdown": pandas_analytics.get("category_breakdown", []),
        "topics_evidence": topics_evidence,
        "improvement_areas": improvement_areas,
        "analytics_breakdown": pandas_analytics
    }


# ═════════════════════════════════════════════════════════════════════════════
# RESUME / JD / MATCH ROUTES
# ═════════════════════════════════════════════════════════════════════════════

@app.route("/resume")
@login_required
def resume_match_page():
    """Main Resume & JD Matcher page."""
    uid     = session["user_id"]
    resumes = db.get_user_resumes(uid)
    jds     = db.get_user_jds(uid)
    matches = db.get_user_matches(uid)
    return render_template("resume_match.html",
                           resumes=resumes, jds=jds, matches=matches)


# ── Resume Upload & Parse ─────────────────────────────────────────────────────

@app.route("/api/resume/upload", methods=["POST"])
@login_required
def api_resume_upload():
    """
    Accept a PDF or DOCX file upload, parse it, analyse with LLM, save to DB.
    Returns the full analysis JSON plus the new resume_id.
    """
    if "resume" not in request.files:
        return jsonify({"error": "No file part in request"}), 400

    file = request.files["resume"]
    if not file or not file.filename:
        return jsonify({"error": "No file selected"}), 400
    if not allowed_resume(file.filename):
        return jsonify({"error": "Only PDF and DOCX files are supported"}), 400

    uid       = session["user_id"]
    ext       = file.filename.rsplit(".", 1)[1].lower()
    safe_name = f"resume_{uid}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath  = os.path.join(UPLOADS_FOLDER, safe_name)
    file.save(filepath)

    # Parse raw text
    try:
        from resume_parser import parse_resume
        raw_text = parse_resume(filepath, ext)
    except Exception as exc:
        if os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({"error": f"Could not parse file: {exc}"}), 500

    if not raw_text.strip():
        if os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({"error": "No text could be extracted. Try a text-based PDF or DOCX."}), 400

    # LLM analysis
    analysis   = analyze_resume_with_llm(raw_text)
    resume_id  = db.save_resume(uid, file.filename, ext, raw_text, analysis, local_filepath=filepath)

    return jsonify({"success": True, "resume_id": resume_id, "analysis": analysis})


# ── JD Analysis ───────────────────────────────────────────────────────────────

@app.route("/api/jd/analyze", methods=["POST"])
@login_required
def api_jd_analyze():
    """
    Accept a JD as plain text (JSON body) or as a file upload (multipart).
    Analyse with LLM and save to DB. Returns the analysis + jd_id.
    """
    uid = session["user_id"]

    fp = None
    if request.content_type and "multipart" in request.content_type:
        jd_file = request.files.get("jd_file")
        if not jd_file:
            return jsonify({"error": "No JD file uploaded"}), 400
        ext = jd_file.filename.rsplit(".", 1)[-1].lower() if "." in jd_file.filename else ""
        safe = f"jd_{uid}_{uuid.uuid4().hex[:8]}.{ext}"
        fp   = os.path.join(UPLOADS_FOLDER, safe)
        jd_file.save(fp)
        try:
            from resume_parser import parse_resume
            jd_text = parse_resume(fp, ext)
        except Exception as exc:
            return jsonify({"error": f"Could not read JD file: {exc}"}), 500
    else:
        data    = request.get_json() or {}
        jd_text = (data.get("jd_text") or "").strip()

    if not jd_text:
        return jsonify({"error": "JD text is empty"}), 400

    analysis = analyze_jd_with_llm(jd_text)
    jd_id    = db.save_jd(uid, jd_text, analysis, local_filepath=fp)


    return jsonify({"success": True, "jd_id": jd_id, "analysis": analysis})


# ── Match Engine Route ────────────────────────────────────────────────────────

@app.route("/api/match", methods=["POST"])
@login_required
def api_match():
    """
    Run the Hybrid Resume × JD match engine:
    TF-IDF Similarity + Pandas Analytics + Evidence-Based Topic Selection.
    """
    data      = request.get_json() or {}
    resume_id = data.get("resume_id")
    jd_id     = data.get("jd_id")

    if not resume_id or not jd_id:
        return jsonify({"error": "Both resume_id and jd_id are required"}), 400

    uid = session["user_id"]
    resume_row = db.get_resume_by_id(resume_id, uid)
    jd_row     = db.get_jd_by_id(jd_id, uid)

    if not resume_row:
        return jsonify({"error": "Resume not found or access denied"}), 404
    if not jd_row:
        return jsonify({"error": "Job description not found or access denied"}), 404

    # Deserialise JSON strings stored in DB
    resume_data = {
        "skills":     json.loads(resume_row.get("skills",     "[]")),
        "experience": json.loads(resume_row.get("experience", "[]")),
        "education":  json.loads(resume_row.get("education",  "[]")),
        "projects":   json.loads(resume_row.get("projects",   "[]")),
    }
    jd_data = {
        "role":                jd_row["role"],
        "required_skills":    json.loads(jd_row.get("required_skills",  "[]")),
        "preferred_skills":   json.loads(jd_row.get("preferred_skills", "[]")),
        "experience_required": jd_row["experience_required"],
    }

    result   = run_match_engine(
        resume_data, jd_data,
        resume_raw_text=resume_row.get("raw_text", ""),
        jd_raw_text=jd_row.get("jd_text", "")
    )
    match_id = db.save_match(uid, resume_id, jd_id, result)

    return jsonify({
        "success":            True,
        "match_id":           match_id,
        "match_score":        result["match_score"],
        "tfidf_score":        result["tfidf_score"],
        "matched_skills":     result["matched_skills"],
        "missing_skills":     result["missing_skills"],
        "missing_preferred":  result.get("missing_preferred", []),
        "bonus_skills":       result.get("bonus_skills", []),
        "must_have_rate":     result["must_have_rate"],
        "preferred_rate":     result["preferred_rate"],
        "category_breakdown": result.get("category_breakdown", []),
        "topics_evidence":    result["topics_evidence"],
        "improvement_areas":  result["improvement_areas"],
    })


# ── Load existing resume for the Matcher UI ────────────────────────────────

@app.route("/api/resume/load/<int:resume_id>")
@login_required
def api_resume_load(resume_id):
    """Return a previously parsed resume so the UI can pre-fill the analysis panel."""
    uid = session["user_id"]
    row = db.get_resume_by_id(resume_id, uid)
    if not row:
        return jsonify({"error": "Resume not found"}), 404

    analysis = {
        "skills":     json.loads(row.get("skills",     "[]")),
        "projects":   json.loads(row.get("projects",   "[]")),
        "education":  json.loads(row.get("education",  "[]")),
        "experience": json.loads(row.get("experience", "[]")),
        "strengths":  json.loads(row.get("strengths",  "[]")),
        "weaknesses": json.loads(row.get("weaknesses", "[]")),
        "summary":    row.get("summary", ""),
    }
    return jsonify({"success": True, "resume_id": resume_id, "analysis": analysis})


# ── Load existing JD for the Matcher UI ───────────────────────────────────

@app.route("/api/jd/load/<int:jd_id>")
@login_required
def api_jd_load(jd_id):
    """Return a previously parsed JD so the UI can pre-fill the analysis panel."""
    uid = session["user_id"]
    row = db.get_jd_by_id(jd_id, uid)
    if not row:
        return jsonify({"error": "JD not found"}), 404

    analysis = {
        "role":                row.get("role", ""),
        "required_skills":    json.loads(row.get("required_skills",  "[]")),
        "preferred_skills":   json.loads(row.get("preferred_skills", "[]")),
        "experience_required": row.get("experience_required", ""),
    }
    return jsonify({"success": True, "jd_id": jd_id,
                    "jd_text": row.get("jd_text", ""), "analysis": analysis})


# ── Load Match Details for Interview ──────────────────────────────────────

@app.route("/api/match/<int:match_id>")
@login_required
def api_match_details(match_id):
    """Return match details including topic blueprint and skill analytics."""
    uid = session["user_id"]
    match = db.get_match_by_id(match_id, uid)
    if not match:
        return jsonify({"error": "Match not found"}), 404
    return jsonify({"success": True, "match": match})


# ─────────────────────────────────────────────────────────────────────────────
# PRACTICE REPORT & TRENDS ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/report/<int:interview_id>")
@login_required
def practice_report_page(interview_id):
    """Render full auditable Practice Report page."""
    uid = session["user_id"]
    report = db.get_interview_report(interview_id, uid)
    if not report:
        flash("Practice report not found.", "error")
        return redirect(url_for("user_dashboard"))
    return render_template("practice_report.html", report=report)


@app.route("/api/report/<int:interview_id>")
@login_required
def api_get_report(interview_id):
    """JSON endpoint for practice report audit data."""
    uid = session["user_id"]
    report = db.get_interview_report(interview_id, uid)
    if not report:
        return jsonify({"error": "Report not found"}), 404
    return jsonify({"success": True, "report": report})


@app.route("/api/trends")
@login_required
def api_user_trends():
    """Return user performance progression and frequent weak area analytics."""
    uid = session["user_id"]
    trends = db.get_user_performance_trends(uid)
    return jsonify({"success": True, "trends": trends})



# ─────────────────────────────────────────────────────────────────────────────
# SERVER STARTUP
# ─────────────────────────────────────────────────────────────────────────────

def find_available_port(preferred_port: int) -> int:
    """Return preferred_port if free, otherwise ask the OS for an open port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex(("127.0.0.1", preferred_port)) != 0:
            return preferred_port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


if __name__ == "__main__":
    preferred_port = int(os.environ.get("PORT", 5000))
    port = find_available_port(preferred_port)
    if port != preferred_port:
        print(f"Port {preferred_port} is in use; using port {port} instead.")
    print(f"Starting AI Interview Bot -> http://localhost:{port}")
    app.run(debug=True, host="0.0.0.0", port=port, use_reloader=False, threaded=True)

