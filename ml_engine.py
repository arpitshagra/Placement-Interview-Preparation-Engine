"""
ml_engine.py — NLP TF-IDF Similarity, Pandas Skill Analytics & Topic Evidence Engine
=====================================================================================
Provides:
1. TF-IDF Cosine Similarity between Resume and Job Description.
2. Pandas-based multi-dimensional skill gap scoring and taxonomy classification.
3. Rule + Data-driven Topic Selection Engine with explicit verifiable evidence.
"""

import re
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# ─────────────────────────────────────────────────────────────────────────────
# SKILL NORMALIZATION & TAXONOMY
# ─────────────────────────────────────────────────────────────────────────────

SKILL_ALIASES = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "py3": "python",
    "golang": "go",
    "postgres": "postgresql",
    "psql": "postgresql",
    "mongo": "mongodb",
    "react.js": "react",
    "reactjs": "react",
    "vue.js": "vue",
    "vuejs": "vue",
    "node.js": "node",
    "nodejs": "nodejs",
    "next.js": "nextjs",
    "nextjs": "nextjs",
    "express.js": "express",
    "expressjs": "express",
    "k8s": "kubernetes",
    "aws ec2": "aws",
    "amazon web services": "aws",
    "gcp": "google cloud",
    "google cloud platform": "google cloud",
    "ms azure": "azure",
    "microsoft azure": "azure",
    "ml": "machine learning",
    "dl": "deep learning",
    "nlp": "natural language processing",
    "cv": "computer vision",
    "ci/cd": "cicd",
    "ci cd": "cicd",
    "rest api": "restful apis",
    "rest apis": "restful apis",
    "graphql api": "graphql",
    "git / github": "git",
}

SKILL_CATEGORIES = {
    "Languages": ["python", "javascript", "typescript", "java", "c++", "c#", "go", "rust", "ruby", "php", "sql", "html", "css", "r", "scala", "kotlin", "swift"],
    "Frameworks & Libs": ["react", "vue", "angular", "nextjs", "django", "fastapi", "flask", "spring boot", "express", "nodejs", "pytorch", "tensorflow", "scikit-learn", "pandas", "numpy", "tailwind", "bootstrap"],
    "Databases": ["postgresql", "mysql", "mongodb", "redis", "sqlite", "oracle", "dynamodb", "cassandra", "elasticsearch", "neo4j", "supabase"],
    "Cloud & DevOps": ["aws", "azure", "google cloud", "docker", "kubernetes", "terraform", "cicd", "jenkins", "github actions", "linux", "nginx", "ansible"],
    "System & Concepts": ["restful apis", "graphql", "microservices", "system design", "data structures", "algorithms", "oop", "multithreading", "async io", "distributed systems", "caching", "oauth", "jwt"],
    "Testing & Tools": ["git", "postman", "pytest", "jest", "junit", "jira", "selenium", "cypress", "webpack", "vite"],
    "Soft Skills": ["communication", "team leadership", "problem solving", "agile", "scrum", "code review", "collaboration", "ownership"]
}


def normalize_skill(skill: str) -> str:
    """Clean and normalize skill strings to avoid false mismatches."""
    if not skill or not isinstance(skill, str):
        return ""
    s = skill.lower().strip()
    s = re.sub(r"[\(\)\[\],;]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return SKILL_ALIASES.get(s, s)


def categorize_skill(skill_normalized: str) -> str:
    """Categorize a normalized skill into a tech domain taxonomy."""
    for category, skills in SKILL_CATEGORIES.items():
        if any(skill_normalized == s or skill_normalized in s or s in skill_normalized for s in skills):
            return category
    return "Other Technical"


# ─────────────────────────────────────────────────────────────────────────────
# 1. TF-IDF COSINE SIMILARITY
# ─────────────────────────────────────────────────────────────────────────────

def compute_tfidf_similarity(resume_text: str, jd_text: str) -> dict:
    """
    Compute mathematical text similarity between raw Resume text and Job Description
    using TF-IDF Vectorizer with unigrams + bigrams and Cosine Similarity.
    """
    if not resume_text or not jd_text:
        return {"similarity_score": 0.0, "similarity_percentage": 0.0, "top_shared_terms": []}

    try:
        vectorizer = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2),
            max_features=500,
            sublinear_tf=True
        )
        tfidf_matrix = vectorizer.fit_transform([resume_text, jd_text])
        sim = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
        sim_score = max(0.0, min(1.0, float(sim)))

        # Find top shared significant terms
        feature_names = vectorizer.get_feature_names_out()
        v_resume = tfidf_matrix[0].toarray()[0]
        v_jd = tfidf_matrix[1].toarray()[0]
        product = v_resume * v_jd
        top_indices = np.argsort(product)[::-1]

        shared_terms = []
        for idx in top_indices:
            if product[idx] > 0 and len(shared_terms) < 10:
                shared_terms.append(feature_names[idx])

        return {
            "similarity_score": round(sim_score, 4),
            "similarity_percentage": round(sim_score * 100, 1),
            "top_shared_terms": shared_terms
        }
    except Exception as e:
        print(f"[ml_engine] TF-IDF error: {e}")
        return {"similarity_score": 0.0, "similarity_percentage": 0.0, "top_shared_terms": []}


# ─────────────────────────────────────────────────────────────────────────────
# 2. PANDAS SKILL GAP ANALYTICS
# ─────────────────────────────────────────────────────────────────────────────

def analyze_skills_with_pandas(resume_data: dict, jd_data: dict, tfidf_result: dict = None) -> dict:
    """
    Construct a structured Pandas DataFrame to analyze skill matches, missing skills,
    category distribution, and weighted match metrics.
    """
    if tfidf_result is None:
        tfidf_result = {"similarity_score": 0.0, "similarity_percentage": 0.0}

    resume_skills_raw = resume_data.get("skills", []) or []
    jd_required_raw = jd_data.get("required_skills", []) or []
    jd_preferred_raw = jd_data.get("preferred_skills", []) or []

    resume_skills_norm = {normalize_skill(s) for s in resume_skills_raw if normalize_skill(s)}
    jd_required_norm = {normalize_skill(s) for s in jd_required_raw if normalize_skill(s)}
    jd_preferred_norm = {normalize_skill(s) for s in jd_preferred_raw if normalize_skill(s)}

    # Build rows for DataFrame
    records = []
    all_jd_skills = list(jd_required_norm) + [s for s in jd_preferred_norm if s not in jd_required_norm]

    for s in all_jd_skills:
        importance = "Required (Must-Have)" if s in jd_required_norm else "Preferred (Nice-to-Have)"
        is_matched = s in resume_skills_norm or any(s in rs or rs in s for rs in resume_skills_norm)
        records.append({
            "skill": s,
            "importance": importance,
            "category": categorize_skill(s),
            "is_matched": is_matched,
            "source": "Job Description"
        })

    # Add extra candidate strengths (bonus skills)
    for s in resume_skills_norm:
        if not any(s == js or s in js or js in s for js in all_jd_skills):
            records.append({
                "skill": s,
                "importance": "Bonus / Resume Strength",
                "category": categorize_skill(s),
                "is_matched": True,
                "source": "Resume Only"
            })

    if records:
        df = pd.DataFrame(records)
    else:
        df = pd.DataFrame(columns=["skill", "importance", "category", "is_matched", "source"])

    # Compute metrics using Pandas
    req_mask = df["importance"] == "Required (Must-Have)"
    pref_mask = df["importance"] == "Preferred (Nice-to-Have)"

    req_total = int(req_mask.sum())
    req_matched = int((req_mask & df["is_matched"]).sum())
    req_rate = round((req_matched / req_total * 100) if req_total > 0 else 100.0, 1)

    pref_total = int(pref_mask.sum())
    pref_matched = int((pref_mask & df["is_matched"]).sum())
    pref_rate = round((pref_matched / pref_total * 100) if pref_total > 0 else 100.0, 1)

    # Matched / Missing lists
    matched_skills = df[df["is_matched"] & (df["source"] == "Job Description")]["skill"].tolist()
    missing_skills = df[~df["is_matched"] & req_mask]["skill"].tolist()
    missing_preferred = df[~df["is_matched"] & pref_mask]["skill"].tolist()
    bonus_skills = df[df["source"] == "Resume Only"]["skill"].tolist()

    # Category Breakdown via Pandas groupby
    category_summary = []
    if not df.empty and (req_mask | pref_mask).any():
        cat_group = df[req_mask | pref_mask].groupby("category")
        for cat, group in cat_group:
            c_tot = len(group)
            c_mat = int(group["is_matched"].sum())
            category_summary.append({
                "category": cat,
                "total": c_tot,
                "matched": c_mat,
                "percentage": round(c_mat / c_tot * 100 if c_tot > 0 else 0, 1)
            })

    # Weighted Overall Match Score
    # 40% Required Skills, 15% Preferred Skills, 25% TF-IDF Text Alignment, 20% Baseline Depth
    tfidf_contrib = tfidf_result.get("similarity_percentage", 0.0)
    overall_score = round(
        (0.40 * req_rate) +
        (0.15 * pref_rate) +
        (0.25 * tfidf_contrib) +
        (0.20 * min(100.0, (req_rate * 0.7 + 30.0))),
        1
    )
    overall_score = max(5.0, min(99.0, overall_score))

    return {
        "overall_match_score": int(round(overall_score)),
        "tfidf_similarity_pct": tfidf_contrib,
        "must_have_total": req_total,
        "must_have_matched": req_matched,
        "must_have_rate": req_rate,
        "preferred_total": pref_total,
        "preferred_matched": pref_matched,
        "preferred_rate": pref_rate,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "missing_preferred": missing_preferred,
        "bonus_skills": bonus_skills[:8],
        "category_breakdown": category_summary,
        "skill_count_total": len(df)
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. TOPIC SELECTION WITH EXPLICIT EVIDENCE JUSTIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def select_topics_with_evidence(
    resume_data: dict,
    jd_data: dict,
    skill_analytics: dict,
    num_topics: int = 5
) -> list:
    """
    Select 5 adaptive interview topics grounded strictly in candidate resume claims,
    job description requirements, and identified skill gaps.
    Every topic includes a verifiable 'evidence_reason' string explaining why it was chosen.
    """
    role = jd_data.get("role") or "Software Engineer"
    projects = resume_data.get("projects") or []
    experience = resume_data.get("experience") or []
    matched_skills = skill_analytics.get("matched_skills") or []
    missing_skills = skill_analytics.get("missing_skills") or []
    bonus_skills = skill_analytics.get("bonus_skills") or []

    topics = []

    # ── Topic 1: Core Technical Claim (Resume Project) ─────────────────────────
    proj_name = "Key Technical Project"
    proj_tech = "Core Framework"
    if projects and isinstance(projects, list) and len(projects) > 0:
        p0 = projects[0]
        if isinstance(p0, dict):
            proj_name = p0.get("name") or proj_name
            techs = p0.get("technologies") or []
            proj_tech = ", ".join(techs[:3]) if techs else "claimed technologies"
        elif isinstance(p0, str):
            proj_name = p0

    skill_focus_1 = matched_skills[0] if matched_skills else "Core Architecture"
    topics.append({
        "topic_number": 1,
        "topic_name": f"Core Technical Claim: {proj_name}",
        "topic_type": "core_claim",
        "focus_area": f"Deep dive into candidate's project '{proj_name}' and mastery of {skill_focus_1}",
        "evidence_reason": (
            f"Candidate claims '{proj_name}' using {proj_tech} on resume. "
            f"Target JD for '{role}' requires practical {skill_focus_1} experience."
        ),
        "target_skills": [skill_focus_1, proj_tech],
        "difficulty": "medium"
    })

    # ── Topic 2: Experience Depth & System Scalability ─────────────────────────
    exp_summary = "Professional background"
    company_name = "prior projects/work"
    years_exp = jd_data.get("experience_required") or "Industry Standard"
    if experience and isinstance(experience, list) and len(experience) > 0:
        e0 = experience[0]
        if isinstance(e0, dict):
            company_name = e0.get("company") or company_name
            exp_summary = f"{e0.get('role', 'Developer')} at {company_name}"

    skill_focus_2 = matched_skills[1] if len(matched_skills) > 1 else (matched_skills[0] if matched_skills else "Data Flow & APIs")
    topics.append({
        "topic_number": 2,
        "topic_name": f"System Architecture & Experience Depth ({skill_focus_2})",
        "topic_type": "experience_depth",
        "focus_area": "System design trade-offs, state management, caching, and concurrency",
        "evidence_reason": (
            f"Candidate has background as {exp_summary}. "
            f"JD requires {years_exp} with high-reliability system practices in {skill_focus_2}."
        ),
        "target_skills": [skill_focus_2, "System Architecture", "Performance"],
        "difficulty": "medium"
    })

    # ── Topic 3: Missing Skill / Skill-Gap Adaptability Probe ─────────────────
    if missing_skills:
        missing_target = missing_skills[0]
        evidence_gap = (
            f"JD explicitly lists '{missing_target}' as a must-have requirement, but it is not listed on candidate's resume. "
            f"Testing fundamental concepts, transferrable skills, and adaptability."
        )
    else:
        missing_target = "Advanced Optimization & Edge Cases"
        evidence_gap = (
            f"Candidate matches primary requirements. Probing advanced edge cases and deep optimization in {role}."
        )

    topics.append({
        "topic_number": 3,
        "topic_name": f"Skill Gap & Adaptability Probe: {missing_target}",
        "topic_type": "skill_gap",
        "focus_area": f"Core mechanics and transferrable knowledge regarding {missing_target}",
        "evidence_reason": evidence_gap,
        "target_skills": [missing_target, "Problem Solving", "Adaptability"],
        "difficulty": "hard"
    })

    # ── Topic 4: Applied Problem Solving & Root Cause Analysis ────────────────
    skill_focus_4 = matched_skills[2] if len(matched_skills) > 2 else "Database & API Resiliency"
    topics.append({
        "topic_number": 4,
        "topic_name": f"Applied Debugging & Resiliency ({skill_focus_4})",
        "topic_type": "problem_solving",
        "focus_area": "Debugging production outages, race conditions, query optimization, or security pitfalls",
        "evidence_reason": (
            f"Target role '{role}' requires robust error handling and fault tolerance in {skill_focus_4}. "
            f"Testing analytical methodology and root-cause discovery."
        ),
        "target_skills": [skill_focus_4, "Debugging", "Security/Error Handling"],
        "difficulty": "hard"
    })

    # ── Topic 5: Technical Ownership & Trade-offs ─────────────────────────────
    topics.append({
        "topic_number": 5,
        "topic_name": "Technical Ownership, Trade-offs & Code Quality",
        "topic_type": "ownership",
        "focus_area": "Technical debt resolution, architectural trade-offs, and engineering rigor",
        "evidence_reason": (
            f"Evaluating candidate's engineering maturity and ownership for the '{role}' position "
            f"when balancing delivery deadlines versus architectural cleanliness."
        ),
        "target_skills": ["Code Quality", "Architectural Trade-offs", "Ownership"],
        "difficulty": "medium"
    })

    return topics[:num_topics]
