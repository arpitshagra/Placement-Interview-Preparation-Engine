-- =============================================================================
-- IntervIQ 2.0 — Supabase PostgreSQL Database Schema
-- =============================================================================
-- Run this script in your Supabase Project's SQL Editor (Dashboard -> SQL Editor).
-- It configures the tables, foreign keys, indexes, and Row Level Security policies.

-- 1. Enable UUID Extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 2. Users Table (Public Profiles)
-- Synced with auth.users (Supabase Auth)
CREATE TABLE IF NOT EXISTS public.users (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name           TEXT NOT NULL,
    email          TEXT NOT NULL UNIQUE,
    password       TEXT DEFAULT '',
    phone          TEXT DEFAULT '',
    college        TEXT DEFAULT '',
    target_company TEXT DEFAULT '',
    role           TEXT DEFAULT 'user', -- 'user' or 'admin'
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Resumes Table
CREATE TABLE IF NOT EXISTS public.resumes (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    file_type   TEXT NOT NULL,
    raw_text    TEXT,
    file_url    TEXT DEFAULT '',
    skills      JSONB DEFAULT '[]'::jsonb,
    projects    JSONB DEFAULT '[]'::jsonb,
    education   JSONB DEFAULT '[]'::jsonb,
    experience  JSONB DEFAULT '[]'::jsonb,
    strengths   JSONB DEFAULT '[]'::jsonb,
    weaknesses  JSONB DEFAULT '[]'::jsonb,
    summary     TEXT DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Job Descriptions Table
CREATE TABLE IF NOT EXISTS public.job_descriptions (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    jd_text             TEXT NOT NULL,
    file_url            TEXT DEFAULT '',
    role                TEXT DEFAULT '',
    required_skills     JSONB DEFAULT '[]'::jsonb,
    preferred_skills    JSONB DEFAULT '[]'::jsonb,
    experience_required TEXT DEFAULT '',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);


-- 5. Resume x JD Matches Table
CREATE TABLE IF NOT EXISTS public.resume_jd_matches (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    resume_id           BIGINT NOT NULL REFERENCES public.resumes(id) ON DELETE CASCADE,
    jd_id               BIGINT NOT NULL REFERENCES public.job_descriptions(id) ON DELETE CASCADE,
    match_score         NUMERIC(5, 2) DEFAULT 0,
    tfidf_score         NUMERIC(5, 2) DEFAULT 0,
    matched_skills      JSONB DEFAULT '[]'::jsonb,
    missing_skills      JSONB DEFAULT '[]'::jsonb,
    improvement_areas   JSONB DEFAULT '[]'::jsonb,
    topics_evidence     JSONB DEFAULT '[]'::jsonb,
    analytics_breakdown JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 6. Interviews Table
CREATE TABLE IF NOT EXISTS public.interviews (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    job_role        TEXT,
    experience      TEXT,
    test_type       TEXT,
    avg_score       NUMERIC(4, 1),
    history         JSONB DEFAULT '[]'::jsonb,
    match_id        BIGINT REFERENCES public.resume_jd_matches(id) ON DELETE SET NULL,
    resume_id       BIGINT REFERENCES public.resumes(id) ON DELETE SET NULL,
    jd_id           BIGINT REFERENCES public.job_descriptions(id) ON DELETE SET NULL,
    feedback        JSONB DEFAULT '{}'::jsonb,
    rubric_scores   JSONB DEFAULT '[]'::jsonb,
    topics_evidence JSONB DEFAULT '[]'::jsonb,
    weak_areas      JSONB DEFAULT '[]'::jsonb,
    action_plan     JSONB DEFAULT '[]'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 7. Add columns if tables already exist (Safe Migrations)
DO $$
BEGIN
    -- users table columns
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='users' AND column_name='password') THEN
        ALTER TABLE public.users ADD COLUMN password TEXT DEFAULT '';
    END IF;

    -- resume_jd_matches columns
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='resume_jd_matches' AND column_name='tfidf_score') THEN
        ALTER TABLE public.resume_jd_matches ADD COLUMN tfidf_score NUMERIC(5, 2) DEFAULT 0;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='resume_jd_matches' AND column_name='topics_evidence') THEN
        ALTER TABLE public.resume_jd_matches ADD COLUMN topics_evidence JSONB DEFAULT '[]'::jsonb;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='resume_jd_matches' AND column_name='analytics_breakdown') THEN
        ALTER TABLE public.resume_jd_matches ADD COLUMN analytics_breakdown JSONB DEFAULT '{}'::jsonb;
    END IF;

    -- resumes table file_url
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='resumes' AND column_name='file_url') THEN
        ALTER TABLE public.resumes ADD COLUMN file_url TEXT DEFAULT '';
    END IF;

    -- job_descriptions table file_url
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='job_descriptions' AND column_name='file_url') THEN
        ALTER TABLE public.job_descriptions ADD COLUMN file_url TEXT DEFAULT '';
    END IF;

    -- interviews table columns
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='interviews' AND column_name='match_id') THEN
        ALTER TABLE public.interviews ADD COLUMN match_id BIGINT REFERENCES public.resume_jd_matches(id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='interviews' AND column_name='resume_id') THEN
        ALTER TABLE public.interviews ADD COLUMN resume_id BIGINT REFERENCES public.resumes(id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='interviews' AND column_name='jd_id') THEN
        ALTER TABLE public.interviews ADD COLUMN jd_id BIGINT REFERENCES public.job_descriptions(id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='interviews' AND column_name='feedback') THEN
        ALTER TABLE public.interviews ADD COLUMN feedback JSONB DEFAULT '{}'::jsonb;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='interviews' AND column_name='rubric_scores') THEN
        ALTER TABLE public.interviews ADD COLUMN rubric_scores JSONB DEFAULT '[]'::jsonb;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='interviews' AND column_name='topics_evidence') THEN
        ALTER TABLE public.interviews ADD COLUMN topics_evidence JSONB DEFAULT '[]'::jsonb;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='interviews' AND column_name='weak_areas') THEN
        ALTER TABLE public.interviews ADD COLUMN weak_areas JSONB DEFAULT '[]'::jsonb;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='interviews' AND column_name='action_plan') THEN
        ALTER TABLE public.interviews ADD COLUMN action_plan JSONB DEFAULT '[]'::jsonb;
    END IF;
END $$;

-- 8. Supabase Storage Buckets (for Resume files, JD files, and Voice Audio)
INSERT INTO storage.buckets (id, name, public)
VALUES ('resumes', 'resumes', true), ('audio', 'audio', true), ('documents', 'documents', true)
ON CONFLICT (id) DO NOTHING;


-- 8. Performance Indexes
CREATE INDEX IF NOT EXISTS idx_users_email ON public.users(email);
CREATE INDEX IF NOT EXISTS idx_interviews_user_id ON public.interviews(user_id);
CREATE INDEX IF NOT EXISTS idx_interviews_created_at ON public.interviews(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_resumes_user_id ON public.resumes(user_id);
CREATE INDEX IF NOT EXISTS idx_jds_user_id ON public.job_descriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_matches_user_id ON public.resume_jd_matches(user_id);

-- 9. Row Level Security (RLS) Configuration
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.interviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.resumes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.job_descriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.resume_jd_matches ENABLE ROW LEVEL SECURITY;

-- Service Role full access policies (for backend Python server with service role key)
DROP POLICY IF EXISTS "Service role full access on users" ON public.users;
CREATE POLICY "Service role full access on users" ON public.users
    FOR ALL USING (auth.role() = 'service_role');

DROP POLICY IF EXISTS "Service role full access on interviews" ON public.interviews;
CREATE POLICY "Service role full access on interviews" ON public.interviews
    FOR ALL USING (auth.role() = 'service_role');

DROP POLICY IF EXISTS "Service role full access on resumes" ON public.resumes;
CREATE POLICY "Service role full access on resumes" ON public.resumes
    FOR ALL USING (auth.role() = 'service_role');

DROP POLICY IF EXISTS "Service role full access on job_descriptions" ON public.job_descriptions;
CREATE POLICY "Service role full access on job_descriptions" ON public.job_descriptions
    FOR ALL USING (auth.role() = 'service_role');

DROP POLICY IF EXISTS "Service role full access on resume_jd_matches" ON public.resume_jd_matches;
CREATE POLICY "Service role full access on resume_jd_matches" ON public.resume_jd_matches
    FOR ALL USING (auth.role() = 'service_role');

-- Authenticated User ownership policies
DROP POLICY IF EXISTS "Users can manage their own profile" ON public.users;
CREATE POLICY "Users can manage their own profile" ON public.users
    FOR ALL USING (auth.uid() = id);

DROP POLICY IF EXISTS "Users can manage their own interviews" ON public.interviews;
CREATE POLICY "Users can manage their own interviews" ON public.interviews
    FOR ALL USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can manage their own resumes" ON public.resumes;
CREATE POLICY "Users can manage their own resumes" ON public.resumes
    FOR ALL USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can manage their own job descriptions" ON public.job_descriptions;
CREATE POLICY "Users can manage their own job descriptions" ON public.job_descriptions
    FOR ALL USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can manage their own matches" ON public.resume_jd_matches;
CREATE POLICY "Users can manage their own matches" ON public.resume_jd_matches
    FOR ALL USING (auth.uid() = user_id);

