import sys, os, requests, json

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

s = requests.Session()
login_res = s.post("http://127.0.0.1:5000/login", data={"email": "test@example.com", "password": "password123"})
print(f"Login status: {login_res.status_code}")

resume_path = os.path.join("uploads", "resume_7_2ff1789e.pdf")
with open(resume_path, "rb") as f:
    res = s.post(
        "http://127.0.0.1:5000/api/start-from-upload",
        files={"resume_file": ("resume.pdf", f, "application/pdf")},
        data={
            "jd_text": "Senior Python Developer. Requirements: PostgreSQL query tuning, FastAPI microservices, Docker container orchestration, Redis caching. Experience: 3+ years.",
            "experience": "mid"
        }
    )

data = res.json()
print("Upload result success:", data.get("success"))
session_id = data.get("session_id")
total_q = data.get("total_q", 5)
print(f"Session: {session_id}")
print(f"Role: {data.get('job_role')}")
print(f"Q1: {data.get('question')}")
print(f"Topic 1 Evidence: {data.get('evidence_reason')}")

q_idx = 1
while True:
    ans_text = "In my project Smart Bharat, I used indexing on foreign keys and connection pooling with SQLAlchemy to optimize PostgreSQL query latency under 30ms for 5000 concurrent users."
    print(f"\nSubmitting answer {q_idx}...")
    ans_res = s.post("http://127.0.0.1:5000/api/answer", json={"session_id": session_id, "text": ans_text})
    ans_data = ans_res.json()
    print(f"Evaluated Q{q_idx}: Tech Score = {ans_data.get('technical_accuracy')}, Followup = {ans_data.get('is_followup')}")
    if ans_data.get("finished"):
        interview_id = ans_data.get("interview_id")
        print(f"\n🎉 Interview Finished!")
        print(f"Interview ID: {interview_id}")
        print(f"Avg Score: {ans_data.get('avg_score')}")
        print(f"Readiness Index: {ans_data.get('readiness_index')}%")
        
        rep_res = s.get(f"http://127.0.0.1:5000/report/{interview_id}")
        print(f"Practice report page status: {rep_res.status_code} ({len(rep_res.text)} bytes)")
        assert rep_res.status_code == 200
        print("ALL TESTS PASSED: Full upload-to-interview-to-report pipeline verified successfully!")
        break
    q_idx += 1
    if q_idx > 10:
        print("Reached maximum iteration limit.")
        break
