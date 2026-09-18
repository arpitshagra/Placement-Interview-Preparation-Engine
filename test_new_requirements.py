import sys, os, requests, json

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

s = requests.Session()
s.post("http://127.0.0.1:5000/login", data={"email": "test@example.com", "password": "password123"})

print("=== 1. Testing Resume Upload WITHOUT JD (Optional JD) ===")
resume_path = os.path.join("uploads", "resume_7_2ff1789e.pdf")
with open(resume_path, "rb") as f:
    res = s.post(
        "http://127.0.0.1:5000/api/start-from-upload",
        files={"resume_file": ("resume.pdf", f, "application/pdf")},
        data={"experience": "mid"}  # NO jd_text or jd_file provided!
    )

assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
data = res.json()
print("Success:", data.get("success"))
print("Inferred Job Role:", data.get("job_role"))
print("Match Score:", data.get("match_score"))
print("Topics count:", len(data.get("topics_evidence", [])))
print("Question 1:", data.get("question"))
session_id = data.get("session_id")
total_q = data.get("total_q")
print(f"Total questions fixed at: {total_q}")
assert total_q == 5, f"Expected total_q=5, got {total_q}"

print("\n=== 2. Testing Strictly Fixed Question Count & Normalized Scoring ===")
q_count = 0
while True:
    q_count += 1
    # Even if answer is short or candidate struggles on Q3:
    if q_count == 3:
        ans_text = "I am not fully sure about the advanced internals of this, but I believe connection pooling helps limit overhead."
    else:
        ans_text = "In my project, we structured our API layer with clear separation of concerns, adding Redis caching and database indexing to handle concurrent spikes."

    print(f"\nSubmitting answer for Question {q_count}...")
    ans_res = s.post("http://127.0.0.1:5000/api/answer", json={"session_id": session_id, "text": ans_text})
    ans_data = ans_res.json()

    # Check 1: Interim responses do NOT expose live rubric scores
    if not ans_data.get("finished"):
        assert "technical_accuracy" not in ans_data, "Live evaluation should NOT be returned right after each question"
        print(f"-> Next Question {ans_data.get('question_num')} / {ans_data.get('total_q')}")
        assert ans_data.get("total_q") == 5, "Total questions must remain fixed at 5"
    else:
        print(f"-> Interview Finished! Total questions answered: {q_count}")
        assert q_count == 5, f"Expected exactly 5 questions answered, got {q_count}"
        print("Average Score:", ans_data.get("avg_score"))
        print("Readiness Index:", ans_data.get("readiness_index"), "%")
        print("Rubric scores count:", len(ans_data.get("rubric_scores", [])))
        for r in ans_data.get("rubric_scores", []):
            print(f"  - {r.get('topic')}: Quality={r.get('quality_score')}/10, Tech={r.get('technical_accuracy')}/10")
        assert ans_data.get("avg_score") >= 5.0, f"Normalized scoring should be fair, got {ans_data.get('avg_score')}"
        break

print("\n=== ALL 4 FIXES VERIFIED SUCCESSFULLY! ===")
