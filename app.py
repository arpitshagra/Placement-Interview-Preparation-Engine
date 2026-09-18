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

# ── App Setup ─────────────────────────────────────────────────────────────────
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "API_KEY.env"))

app = Flask(__name__)
app.secret_key = "interview-bot-secret"          # used to sign session cookies

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
# AUTH DECORATORS
# ─────────────────────────────────────────────────────────────────────────────

def login_required(f):
    """Redirect to login page if user is not logged in."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    """Only allow admin users to access this route."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            return redirect(url_for("user_dashboard"))
        return f(*args, **kwargs)
    return decorated

# ─────────────────────────────────────────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────────────────────────────────────────

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


def generate_question(sess: dict) -> str:
    """Ask the LLM to generate one interview question based on job role and difficulty."""
    system = ("You are a professional interviewer. "
              "Generate exactly ONE interview question. "
              "Return only the question — no preamble, no numbering.")
    user   = (f"Role: {sess['job_role']}\nExperience: {sess['experience']}\n"
              f"Test type: {sess['test_type']}\nDifficulty: {sess['difficulty']}\n"
              "Ask a focused question appropriate for this role.")
    return llm(system, user, temperature=0.6)

def analyse_answer(sess: dict, question: str, answer: str) -> dict:
    """
    Send the current Q&A to the LLM for evaluation.
    Returns a JSON dict with score, sentiment, emotion, plagiarism risk, etc.
    """
    asked   = len(sess["history"])
    total_q = sess["total_q"]

    system = """You are an expert AI interview evaluator and AI-content detector.
Return ONLY valid JSON — no markdown, no extra text.
Schema:
{
  "quality_score": <1-10>,
  "sentiment": "positive"|"neutral"|"negative",
  "emotion": "confident"|"nervous"|"confused"|"enthusiastic"|"unsure",
  "plagiarism_risk": "low"|"medium"|"high",
  "plagiarism_reason": "<1 sentence explaining why you flagged this level>",
  "next_difficulty": "easy"|"medium"|"hard",
  "done": true|false,
  "next_question": "<next question or empty string if done>",
  "brief_acknowledgement": "<1 short sentence response to the answer>"
}
emotion: detect how the candidate sounds based on word choice and structure.

PLAGIARISM / AI-DETECTION RULES (very important):
Analyse the answer carefully for signs it was generated by an AI (ChatGPT, Gemini, etc.) or copy-pasted from the internet.
- "high": The answer reads like AI-generated text — overly structured, uses filler phrases like "In conclusion", "It's important to note", "There are several key aspects", unnaturally comprehensive, bullet-point-like enumeration in prose, or textbook-perfect with no personal voice.
- "medium": The answer is partially original but contains some generic/memorised phrasing that could be from a textbook or AI. Mixed signals.
- "low": The answer sounds genuinely human — has personal phrasing, casual tone, minor imperfections, specific personal experiences, or natural conversational style.
Look for: unnatural fluency, overly balanced pros/cons, generic examples, lack of personal anecdotes, perfect grammar with no filler words, and suspiciously well-organized structure.

Raise difficulty if score>=7, lower if <=4. Set done=true when asked equals total.
CRITICAL: Always generate a NEW, different question for 'next_question'. Never repeat the same question or ask the user to try again, even if their answer was incorrect or incomplete."""

    user = (f"Role: {sess['job_role']} | Experience: {sess['experience']}\n"
            f"Question {asked}/{total_q}: {question}\n"
            f"Answer: {answer}\n\nReturn JSON only.")

    raw = llm(system, user, temperature=0.3)
    raw = re.sub(r"```[a-z]*", "", raw).strip("` \n")   # remove markdown code fences if any

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fallback if LLM returns invalid JSON
        return {
            "quality_score": 5,
            "sentiment": "neutral",
            "emotion": "unsure",
            "plagiarism_risk": "low",
            "next_difficulty": sess["difficulty"],
            "done": asked >= total_q,
            "next_question": "",
            "brief_acknowledgement": "Thank you."
        }

def generate_feedback(sess: dict) -> dict:
    """Generate a final structured feedback and spoken summary for the whole interview."""
    # Build a summary of all questions + scores
    summary = "".join(
        f"Q{i}: {h['question']}\nScore: {(h.get('analysis') or {}).get('quality_score', '?')}/10\n\n"
        for i, h in enumerate(sess["history"], 1)
    )
    system = """You are a professional interview coach.
Return ONLY valid JSON — no markdown, no extra text.
Schema:
{
  "strong_points": ["point 1", "point 2"],
  "weak_points": ["point 1", "point 2"],
  "improvements": ["point 1", "point 2"],
  "spoken_summary": "A 5-7 sentence spoken summary. Cover strengths, one area to improve, and one specific resource. Speak naturally."
}"""
    raw = llm(
        system,
        f"Role: {sess['job_role']} ({sess['experience']}) | Type: {sess['test_type']}\n\n{summary}",
        temperature=0.5
    )
    raw = re.sub(r"```[a-z]*", "", raw).strip("` \n")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "strong_points": ["Good effort overall."],
            "weak_points": ["Some answers lacked detail."],
            "improvements": ["Practice structuring answers using the STAR method."],
            "spoken_summary": "Thank you for completing the interview. You made a good effort overall, but some answers lacked detail. I recommend practicing the STAR method for structuring your responses. Good luck!"
        }

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
    """Convert text to an .mp3 audio file using Microsoft Edge neural TTS."""
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
    return filepath

# ─────────────────────────────────────────────────────────────────────────────
# INTERVIEW API ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/start", methods=["POST"])
@login_required
def api_start():
    """
    Start a new interview session.
    Expects JSON: { job_role, experience, test_type, total_q }
    Returns: { session_id, question, audio_url }
    """
    data = request.get_json() or {}
    if not data.get("job_role"):
        return jsonify({"error": "job_role is required"}), 400

    # Create a new session dict to track this interview
    sess = {
        "id":         str(uuid.uuid4()),          # unique ID for this interview
        "user_id":    session["user_id"],
        "job_role":   data.get("job_role"),
        "experience": data.get("experience", "mid"),
        "test_type":  data.get("test_type", "mixed"),
        "total_q":    int(data.get("total_q", 6)),
        "history":    [],                          # list of {question, answer, analysis}
        "difficulty": "medium",
        "finished":   False,
    }
    interview_sessions[sess["id"]] = sess

    # Generate the first question
    question = generate_question(sess)
    sess["history"].append({"question": question, "answer": None, "analysis": None})

    # Speak the welcome message + first question
    audio_file = f"{sess['id']}_q0.mp3"
    speak(f"Welcome. Let us begin your {sess['test_type']} interview "
          f"for the role of {sess['job_role']}. Here is your first question. {question}",
          audio_file)

    return jsonify({
        "session_id":   sess["id"],
        "question":     question,
        "question_num": 1,
        "total_q":      sess["total_q"],
        "audio_url":    f"/audio/{audio_file}"
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
    Submit an answer (text) for the current question.
    The LLM evaluates it and either returns the next question or final feedback.
    Expects JSON: { session_id, text }
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

    # Save the answer to history
    current_q = sess["history"][-1]["question"]
    sess["history"][-1]["answer"] = text

    # Check if this was the last question
    asked      = len(sess["history"])
    force_done = asked >= sess["total_q"]

    # Evaluate the answer with LLM
    analysis = analyse_answer(sess, current_q, text)
    if force_done:
        analysis["done"] = True    # force end even if LLM says otherwise

    sess["history"][-1]["analysis"] = analysis
    sess["difficulty"] = analysis.get("next_difficulty", sess["difficulty"])

    # ── Interview Finished ────────────────────────────────────────────────────
    if analysis.get("done"):
        sess["finished"] = True
        feedback   = generate_feedback(sess)

        # Speak the feedback
        audio_file = f"{session_id}_feedback.mp3"
        speak(feedback.get("spoken_summary", "Thank you."), audio_file)

        # Calculate average score across all questions
        scores = [h["analysis"].get("quality_score", 5)
                  for h in sess["history"] if h.get("analysis")]
        avg = round(sum(scores) / max(len(scores), 1), 1)

        # Save interview to the database
        db.save_interview(
            user_id    = sess["user_id"],
            job_role   = sess["job_role"],
            experience = sess["experience"],
            test_type  = sess["test_type"],
            avg_score  = avg,
            history    = sess["history"],
        )

        return jsonify({
            "transcription":    text,
            "finished":         True,
            "feedback":         feedback,
            "avg_score":        avg,
            "scores":           [h["analysis"].get("quality_score", 0) for h in sess["history"] if h.get("analysis")],
            "plagiarism_risks":   [h["analysis"].get("plagiarism_risk", "low") for h in sess["history"] if h.get("analysis")],
            "plagiarism_reasons": [h["analysis"].get("plagiarism_reason", "") for h in sess["history"] if h.get("analysis")],
            "audio_url":          f"/audio/{audio_file}"
        })

    # ── Next Question ─────────────────────────────────────────────────────────
    next_q = analysis.get("next_question") or generate_question(sess)
    sess["history"].append({"question": next_q, "answer": None, "analysis": None})

    # Speak acknowledgement + next question
    ack        = analysis.get("brief_acknowledgement", "Thank you.")
    q_index    = len(sess["history"])
    audio_file = f"{session_id}_q{q_index}.mp3"
    speak(f"{ack} {next_q}", audio_file)

    return jsonify({
        "transcription": text,
        "finished":      False,
        "next_question": next_q,
        "question_num":  q_index,
        "total_q":       sess["total_q"],
        "difficulty":    sess["difficulty"],
        "audio_url":     f"/audio/{audio_file}"
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

def analyze_resume_with_llm(raw_text: str) -> dict:
    """Use Groq LLM to extract structured information from raw resume text."""
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

    raw = llm(system, f"Resume text:\n\n{raw_text[:5000]}", temperature=0.2)
    raw = re.sub(r"```[a-z]*", "", raw).strip("` \n")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"skills": [], "projects": [], "education": [],
                "experience": [], "strengths": [], "weaknesses": [], "summary": ""}


def analyze_jd_with_llm(jd_text: str) -> dict:
    """Use Groq LLM to extract structured information from a job description."""
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

    raw = llm(system, f"Job Description:\n\n{jd_text[:5000]}", temperature=0.2)
    raw = re.sub(r"```[a-z]*", "", raw).strip("` \n")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"role": "", "required_skills": [], "preferred_skills": [], "experience_required": ""}


def run_match_engine(resume_data: dict, jd_data: dict) -> dict:
    """
    Use Groq LLM to compare resume against JD and produce a match report.
    resume_data and jd_data are dicts with Python lists (already parsed from JSON).
    """
    system = """You are an expert ATS (Applicant Tracking System) and senior career coach.
Analyse the resume data versus the job description data and return ONLY valid JSON — no markdown.
Schema:
{
  "match_score": <integer 0-100>,
  "matched_skills":    ["skill that appears in both"],
  "missing_skills":    ["required skill absent from resume"],
  "improvement_areas": [
    {"area": "Short title", "suggestion": "Specific, actionable 1-2 sentence advice"}
  ]
}
Rules:
- match_score: percentage of required JD skills found in resume (weighted by experience depth).
- matched_skills: skills that appear in both the resume and the JD (required OR preferred).
- missing_skills: required JD skills completely absent from resume.
- improvement_areas: 3-5 concrete suggestions to close the gap or strengthen the application."""

    user_payload = (
        f"RESUME SKILLS: {json.dumps(resume_data.get('skills', []))}\n"
        f"RESUME EXPERIENCE: {json.dumps(resume_data.get('experience', []))}\n"
        f"RESUME EDUCATION: {json.dumps(resume_data.get('education', []))}\n"
        f"RESUME PROJECTS: {json.dumps(resume_data.get('projects', []))}\n\n"
        f"JD ROLE: {jd_data.get('role', '')}\n"
        f"JD REQUIRED SKILLS: {json.dumps(jd_data.get('required_skills', []))}\n"
        f"JD PREFERRED SKILLS: {json.dumps(jd_data.get('preferred_skills', []))}\n"
        f"JD EXPERIENCE REQUIRED: {jd_data.get('experience_required', '')}"
    )

    raw = llm(system, user_payload, temperature=0.2)
    raw = re.sub(r"```[a-z]*", "", raw).strip("` \n")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"match_score": 0, "matched_skills": [], "missing_skills": [], "improvement_areas": []}


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
        os.remove(filepath)
        return jsonify({"error": f"Could not parse file: {exc}"}), 500

    if not raw_text.strip():
        os.remove(filepath)
        return jsonify({"error": "No text could be extracted. Try a text-based PDF or DOCX."}), 400

    # LLM analysis
    analysis   = analyze_resume_with_llm(raw_text)
    resume_id  = db.save_resume(uid, file.filename, ext, raw_text, analysis)

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

    # Support both JSON body and multipart upload
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
    jd_id    = db.save_jd(uid, jd_text, analysis)

    return jsonify({"success": True, "jd_id": jd_id, "analysis": analysis})


# ── Match Engine ──────────────────────────────────────────────────────────────

@app.route("/api/match", methods=["POST"])
@login_required
def api_match():
    """
    Run the Resume × JD match engine.
    Expects JSON: { resume_id, jd_id }
    Returns: match_score, matched_skills, missing_skills, improvement_areas
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

    result   = run_match_engine(resume_data, jd_data)
    match_id = db.save_match(uid, resume_id, jd_id, result)

    return jsonify({
        "success":           True,
        "match_id":          match_id,
        "match_score":       result["match_score"],
        "matched_skills":    result["matched_skills"],
        "missing_skills":    result["missing_skills"],
        "improvement_areas": result["improvement_areas"],
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

