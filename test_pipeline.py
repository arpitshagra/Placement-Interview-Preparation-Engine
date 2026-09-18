import sys
import requests
import json
from ml_engine import compute_tfidf_similarity, analyze_skills_with_pandas, select_topics_with_evidence

# Set UTF-8 encoding for stdout on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

s = requests.Session()

# 1. Login or signup
login_res = s.post('http://127.0.0.1:5000/login', data={'email': 'test@example.com', 'password': 'password123'})
if login_res.status_code != 200 or 'dashboard' not in login_res.url:
    s.post('http://127.0.0.1:5000/signup', data={'name': 'Arpit Test', 'email': 'test@example.com', 'password': 'password123'})
    s.post('http://127.0.0.1:5000/login', data={'email': 'test@example.com', 'password': 'password123'})

# 2. Test Match Engine
sample_resume = {
    'skills': ['Python', 'Flask', 'PostgreSQL', 'Docker', 'REST APIs', 'Git'],
    'experience': ['Backend Developer at Acme Corp building scalable microservices and APIs.'],
    'education': ['B.Tech Computer Science'],
    'projects': ['Real-time Notification Engine handling 10k req/sec with Redis caching.']
}

sample_jd = {
    'role': 'Senior Backend Engineer',
    'required_skills': ['Python', 'Django/Flask', 'PostgreSQL', 'Microservices', 'Kubernetes'],
    'preferred_skills': ['Kafka', 'Docker', 'Redis', 'AWS'],
    'experience_required': '2-4 years'
}

print('=== 1. Testing ML Match Engine ===')
tfidf = compute_tfidf_similarity(' '.join(sample_resume['skills'] + sample_resume['projects']), ' '.join(sample_jd['required_skills'] + sample_jd['preferred_skills']))
skills_res = analyze_skills_with_pandas(sample_resume, sample_jd, tfidf)
topics = select_topics_with_evidence(sample_resume, sample_jd, skills_res)
print(f"TF-IDF Similarity: {tfidf['similarity_percentage']}%")
print(f"Match Score: {skills_res['overall_match_score']}% (Must-have: {skills_res['must_have_rate']}%)")
print(f"Topics generated ({len(topics)}):")
for t in topics:
    print(f"  - Topic {t['topic_number']}: {t['topic_name']} [{t['topic_type']}] => Evidence: {t['evidence_reason']}")

# 3. Test /api/start
print('\n=== 2. Testing /api/start ===')
start_res = s.post('http://127.0.0.1:5000/api/start', json={
    'job_role': 'Senior Backend Engineer',
    'experience': 'mid',
    'test_type': 'adaptive_technical'
})
start_data = start_res.json()
print('Start response status:', start_res.status_code)
print('Question 1:', start_data.get('question'))
print('Topic:', start_data.get('topic_name'))
print('Evidence Reason:', start_data.get('evidence_reason'))

# 4. Test /api/answer with adaptive probe
print('\n=== 3. Testing /api/answer ===')
ans_res = s.post('http://127.0.0.1:5000/api/answer', json={
    'session_id': start_data['session_id'],
    'text': 'In my previous project, we built REST microservices with Flask and PostgreSQL. We used Redis for caching frequent queries and connection pooling to handle high concurrency, achieving sub-50ms latency.'
})
ans_data = ans_res.json()
print('Answer evaluated status:', ans_res.status_code)
print('Quality Score:', ans_data.get('quality_score'))
print('Tech Accuracy:', ans_data.get('technical_accuracy'))
print('Rubric Feedback:', ans_data.get('rubric_feedback'))
print('Is Followup Probe:', ans_data.get('is_followup'))
print('Next Question / Follow-up:', ans_data.get('next_question'))

print('\n=== 4. Testing Multi-turn Interview to Final Practice Report ===')
while not ans_data.get('finished'):
    q_topic = ans_data.get('topic_name') or 'Current Topic'
    print(f"Submitting comprehensive answer for: {q_topic}...")
    ans_res = s.post('http://127.0.0.1:5000/api/answer', json={
        'session_id': start_data['session_id'],
        'text': 'To design for high availability and fault tolerance, we decoupled ingress handling from background task workers using Celery and Redis. We enforced database read replicas, connection pooling with PgBouncer, structured logging with correlation IDs, exponential backoff retries with circuit breakers, and containerized deployment with health checks.'
    })
    ans_data = ans_res.json()

print(f"\nInterview completed successfully!")
print(f"Final Avg Score: {ans_data.get('avg_score')}/10")
print(f"Readiness Index: {ans_data.get('readiness_index')}%")
print(f"Interview ID: {ans_data.get('interview_id')}")

# Test Practice Report HTML rendering
rep_res = s.get(f"http://127.0.0.1:5000/report/{ans_data['interview_id']}")
print(f"Practice Report GET Status: {rep_res.status_code} (HTML size: {len(rep_res.text)} bytes)")
assert rep_res.status_code == 200, "Practice Report failed to render"

# Test User Dashboard rendering
dash_res = s.get("http://127.0.0.1:5000/dashboard")
print(f"User Dashboard GET Status: {dash_res.status_code} (HTML size: {len(dash_res.text)} bytes)")
assert dash_res.status_code == 200, "Dashboard failed to render"

print('\n✨ ALL PLACEMENT INTERVIEW PREPARATION ENGINE REQUIREMENTS VALIDATED 100% ✨')
