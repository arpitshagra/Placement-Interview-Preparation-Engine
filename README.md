# IntervIQ — Adaptive AI Placement & Interview Preparation Engine

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.3+-000000?style=for-the-badge&logo=flask&logoColor=white)](https://palletsprojects.com/p/flask/)
[![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white)](https://supabase.com/)
[![Groq](https://img.shields.io/badge/Groq-LLM_Inference-F05A28?style=for-the-badge)](https://groq.com/)
[![OpenAI Whisper](https://img.shields.io/badge/Whisper-Speech_to_Text-412991?style=for-the-badge&logo=openai&logoColor=white)](https://github.com/openai/whisper)
[![Scikit-Learn](https://img.shields.io/badge/Scikit_Learn-ML_Engine-F7931E?style=for-the-badge&logo=scikit-learn&logoColor=white)](https://scikit-learn.org/)

**IntervIQ** is an enterprise-ready, AI-driven placement preparation and mock interview platform. It simulates real-world technical and behavioral interviews using dynamic voice agents, analyzes candidate resumes against target job descriptions using NLP, adapts questions based on candidate performance, and provides multi-rubric feedback with actionable improvement plans.

---

## Table of Contents

- [Key Features](#key-features)
- [Architecture & Tech Stack](#architecture--tech-stack)
- [Project Directory Structure](#project-directory-structure)
- [Prerequisites](#prerequisites)
- [Quick Start Guide](#quick-start-guide)
  - [1. Clone and Create Virtual Environment](#1-clone-and-create-virtual-environment)
  - [2. Install Dependencies](#2-install-dependencies)
  - [3. Configure Environment Variables](#3-configure-environment-variables)
  - [4. Supabase Database & Storage Setup](#4-supabase-database--storage-setup)
  - [5. Launch the Application](#5-launch-the-application)
- [Google OAuth Setup (Supabase)](#google-oauth-setup-supabase)
- [Environment Variables](#environment-variables)
- [Core Workflow & Features](#core-workflow--features)
  - [AI Voice Mock Interviews](#1-ai-voice-mock-interviews)
  - [Resume & Job Description Matcher](#2-resume--job-description-matcher)
  - [Multi-Rubric Evaluation & Reporting](#3-multi-rubric-evaluation--reporting)
  - [Candidate & Admin Dashboards](#4-candidate--admin-dashboards)
- [API Reference](#api-reference)
- [License](#license)

---

## Key Features

- **Adaptive AI Voice Interviews**:
  - Live voice interaction powered by OpenAI Whisper (speech-to-text) and Microsoft Edge-TTS (neural text-to-speech).
  - Conversational AI powered by Groq LLM (`openai/gpt-oss-120b`) generates contextual follow-up questions in real time.
- **Resume & Job Description Analysis**:
  - Automated PDF/DOCX parsing using PyMuPDF (`fitz`) and `python-docx`.
  - Machine learning keyword extraction and TF-IDF cosine similarity calculations via Scikit-Learn.
  - Skill-gap identification highlighting missing technical and soft skills.
- **Direct "Start Interview from Upload"**:
  - Upload a resume and job description to instantly generate tailored interview topics aligned with the candidate's actual projects and company requirements.
- **Enterprise Cloud Storage & PostgreSQL**:
  - Full relational PostgreSQL database hosted on Supabase.
  - Native JSONB columns for audit logs, rubrics, candidate histories, and skill matrices.
  - Supabase Storage buckets for persistent resumes, job descriptions, and interview audio recordings.
- **Dual Authentication**:
  - One-click **Google OAuth (SSO)** via Supabase Auth with automatic profile synchronization into `public.users`.
  - Traditional email/password authentication with SHA-256 password hashing.
  - Role-Based Access Control (Admin vs. Candidate).
- **Candidate & Admin Analytics**:
  - Historical interview transcripts, score trends, and audio playback.
  - Admin view for managing users, monitoring interview scores, and tracking candidate performance.

---

## Architecture & Tech Stack

```
 candidate (Browser)
      │
      ├── Google OAuth / Supabase Auth
      │       │
      │       ▼
      │   Supabase Cloud (Users, Auth, Buckets)
      │
      ├── Audio Input / Speech Output
      │       │
      │       ▼
 Flask Application (app.py)
      ├── Speech Processing: Whisper (STT) & Edge-TTS (TTS)
      ├── LLM Reasoning: Groq API (gpt-oss-120b)
      ├── ML Engine (ml_engine.py): TF-IDF, Cosine Similarity, Skill Gap
      └── Storage & DB Layer (database.py): Supabase PostgreSQL & Buckets
```

| Layer | Technologies |
| :--- | :--- |
| **Backend** | Python 3.10+, Flask, Flask-CORS |
| **LLM Inference** | Groq API (`openai/gpt-oss-120b` / `llama-3.3-70b-versatile`) |
| **Voice & Speech** | OpenAI Whisper, Microsoft Edge-TTS, Soundfile |
| **Machine Learning** | Scikit-Learn (TF-IDF Vectorizer), Pandas, NumPy |
| **Document Parsing** | PyMuPDF (fitz), Python-Docx |
| **Database & Auth** | Supabase (PostgreSQL 15+, Supabase Auth, Row Level Security) |
| **Cloud Storage** | Supabase Storage (`resumes`, `documents`, `audio` buckets) |
| **Frontend** | Jinja2 Templates, HTML5, Vanilla CSS3, JavaScript, Supabase JS SDK v2 |

---

## Project Directory Structure

```
Placement-Interview-Preparation-Engine/
├── app.py                      # Core Flask web server, API routes, and interview session manager
├── database.py                 # Supabase PostgreSQL database helper functions, auth & storage
├── ml_engine.py                # ML algorithms: TF-IDF similarity, skill analysis & rubric scoring
├── resume_parser.py            # Resume/JD text extraction and structural analysis
├── supabase_schema.sql         # SQL schema definitions, foreign keys, indexes, and RLS policies
├── requirements.txt            # Python dependencies
├── .env.example                # Example environment variables template
├── static/
│   └── js/
│       └── supabaseAuth.js     # Client-side Supabase SDK & Google OAuth integration
├── templates/
│   ├── base.html               # Main layout template with navigation and Supabase SDK
│   ├── homepage.html           # Landing page
│   ├── login.html              # Sign-in page with Google OAuth button
│   ├── signup.html             # Account registration page with Google OAuth
│   ├── auth_callback.html      # OAuth token exchange and session synchronizer
│   ├── user_dashboard.html     # Candidate analytics and interview history
│   ├── admin_dashboard.html    # Administrative overview and candidate management
│   ├── interview.html          # Interactive AI voice interview interface
│   ├── interview_report.html   # Comprehensive multi-rubric assessment report
│   └── resume_match.html       # Resume vs. Job Description parser and matching tool
├── uploads/                    # Temporary local storage for parsed resumes/JDs
└── responses/                  # Temporary local storage for recorded audio responses
```

---

## Prerequisites

Before setting up the project, make sure you have:

1. **Python 3.10 or higher** installed.
2. A **Supabase** account and project ([supabase.com](https://supabase.com)).
3. A **Groq** API key ([console.groq.com](https://console.groq.com)).
4. (Optional) A **Google Cloud Console** project for Google OAuth credentials.

---

## Quick Start Guide

### 1. Clone and Create Virtual Environment

```bash
# Clone repository
git clone https://github.com/arpitshagra/Placement-Interview-Preparation-Engine.git
cd Placement-Interview-Preparation-Engine

# Create a virtual environment
python3 -m venv venv

# Activate virtual environment
# On macOS / Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the project root by copying `.env.example`:

```bash
cp .env.example .env
```

Open `.env` and fill in your credentials:

```ini
# Supabase Configuration (from Supabase Dashboard -> Settings -> API)
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-supabase-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-supabase-service-role-key

# Groq API Configuration (from console.groq.com)
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-120b

# Flask App Secrets
SECRET_KEY=generate-a-secure-random-secret-key
PORT=5000
```

### 4. Supabase Database & Storage Setup

1. Log in to your **Supabase Project Dashboard**.
2. Open the **SQL Editor** on the left menu.
3. Open `supabase_schema.sql` from this repository, paste the entire contents into the SQL Editor, and click **Run**.
4. In your Supabase Dashboard, go to **Storage** and ensure the following 3 buckets exist:
   - `resumes` (Private)
   - `documents` (Private)
   - `audio` (Public or authenticated access)

### 5. Launch the Application

```bash
python app.py
```

The application will start on **`http://localhost:5000`** (or your configured `PORT`).

---

## Google OAuth Setup (Supabase)

To enable **"Continue with Google"** single sign-on:

1. In the **Google Cloud Console**:
   - Go to **APIs & Services** > **Credentials**.
   - Create an **OAuth 2.0 Client ID** (Web application).
   - In **Authorized redirect URIs**, add your Supabase Auth callback URL:
     `https://<your-supabase-project-id>.supabase.co/auth/v1/callback`
2. In the **Supabase Dashboard**:
   - Go to **Authentication** > **Providers** > **Google**.
   - Toggle **Enable Google provider**.
   - Paste your **Client ID** and **Client Secret** from Google Cloud.
   - Click **Save**.
3. In the **Supabase Dashboard**:
   - Go to **Authentication** > **URL Configuration**.
   - Under **Redirect URLs**, add:
     - `http://localhost:5000/auth/callback`
     - `http://127.0.0.1:5000/auth/callback`
     - *(and your production domain's `/auth/callback` if deploying to the cloud)*
   - Click **Save**.

---

## Environment Variables

| Variable | Required | Description |
| :--- | :---: | :--- |
| `SUPABASE_URL` | **Yes** | Your Supabase project URL (`https://<project-ref>.supabase.co`) |
| `SUPABASE_KEY` | **Yes** | Supabase anonymous / public API key |
| `SUPABASE_SERVICE_ROLE_KEY` | **Yes** | Supabase service role key (for server-side DB operations & admin tasks) |
| `GROQ_API_KEY` | **Yes** | API key from Groq Cloud for fast LLM inference |
| `GROQ_MODEL` | No | Groq LLM model name (default: `openai/gpt-oss-120b`) |
| `SECRET_KEY` | **Yes** | Secret key for Flask encrypted session cookies |
| `PORT` | No | Application port (default: `5000`) |

---

## Core Workflow & Features

### 1. AI Voice Mock Interviews
- The candidate selects their desired job role (e.g., *Frontend Engineer*, *Data Scientist*, *Backend Engineer*), experience level, and test type (*Technical*, *Behavioral*, or *Mixed*).
- The candidate can speak naturally via microphone or type answers.
- Whisper transcribes the candidate's speech.
- Groq evaluates the response, assigns an instant score (1–10), provides constructive feedback, and dynamically formulates the next question.

### 2. Resume & Job Description Matcher
- Upload a candidate's resume (PDF/DOCX) and paste or upload a target job description.
- The ML engine computes:
  - **Overall Match Score** (0–100%) based on TF-IDF cosine similarity and skill overlap.
  - **Matched Skills**: Hard and soft skills found in both documents.
  - **Missing Skills**: Crucial qualifications demanded by the JD but absent in the resume.
- Candidate can click **"Start Tailored Interview"** to immediately begin an interview focused on bridging the identified skill gaps.

### 3. Multi-Rubric Evaluation & Reporting
Upon completing an interview, an audit report is generated detailing:
- Overall Score and Grade.
- Rubric Breakdown: Technical Accuracy, Problem Solving, Communication, and Confidence.
- Detailed question-by-question transcripts, audio recordings, scores, and evaluator suggestions.
- Actionable study recommendations and key areas for improvement.

### 4. Candidate & Admin Dashboards
- **Candidate Dashboard (`/dashboard`)**: Track improvement over time, review historical interview scores, and download full assessment reports.
- **Admin Dashboard (`/admin`)**: High-level view of all registered candidates, total interviews completed, and average cohort performance.

---

## API Reference

### Authentication Endpoints
- `GET /api/config`: Exposes public Supabase URL and Anon Key for client SDK initialization.
- `POST /api/auth/session`: Validates Supabase JWTs, syncs the user profile with `public.users`, and sets Flask session cookies.
- `POST /api/auth/logout`: Clears the server session upon client sign-out.
- `GET /auth/callback`: Handles client-side OAuth token exchange and redirects to `/dashboard`.

### Interview Endpoints
- `POST /api/start`: Initializes a new in-memory interview session.
- `POST /api/transcribe`: Accepts an audio blob and returns the Whisper STT transcription.
- `POST /api/answer`: Submits a candidate's answer, queries Groq for evaluation, and returns the next question.
- `GET /api/report/<interview_id>`: Fetches the finalized multi-rubric evaluation report.

### Resume & Job Description Endpoints
- `POST /api/resume/upload`: Parses an uploaded resume and saves extracted skills and experience to Supabase.
- `POST /api/jd/analyze`: Analyzes job description requirements.
- `POST /api/match`: Computes TF-IDF similarity, matched skills, and missing skills between a resume and JD.
- `POST /api/start-from-upload`: Direct pipeline to parse resume + JD and initialize a tailored interview session in one step.

---

## Verification & Testing

To run the automated verification suite:

```bash
python -m unittest test_new_requirements.py
python -m unittest test_pipeline.py
python -m unittest test_upload_flow.py
```

---

## License

This project is licensed under the [MIT License](LICENSE).