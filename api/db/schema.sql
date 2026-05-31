-- FixFinance — PostgreSQL schema (LLD §3)
-- Auto-run by the pgvector/pgvector:pg16 image on first boot.
-- One DB holds: relational data + vectors (pgvector) + trace store.
-- LangGraph's PostgresSaver creates its own checkpoint tables at app startup (.setup()).

CREATE EXTENSION IF NOT EXISTS vector;        -- pgvector

-- ---------------------------------------------------------------------------
-- Auth (temporary admin-provisioned; FR4.6)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username      TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_by    TEXT NOT NULL DEFAULT 'admin',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
  token      TEXT PRIMARY KEY,
  user_id    UUID NOT NULL REFERENCES users(id),
  expires_at TIMESTAMPTZ NOT NULL
);

-- ---------------------------------------------------------------------------
-- Interview
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS interview_sessions (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES users(id),
  phase      TEXT NOT NULL DEFAULT 'greeting',   -- greeting|interviewing|confirming|done
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Proformas (append-only versioned; FR2.5)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS proformas (
  id          UUID NOT NULL,                 -- logical profile id (stable across versions)
  version     INT  NOT NULL,
  user_id     UUID NOT NULL REFERENCES users(id),
  source      TEXT NOT NULL,                 -- ai_extracted | user_edited
  data        JSONB NOT NULL,                -- validated against Proforma schema (LLD §4)
  derived     JSONB NOT NULL,                -- computed metrics (LLD §9.3)
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (id, version)
);

-- ---------------------------------------------------------------------------
-- Reports (async)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS report_jobs (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  proforma_id  UUID NOT NULL,
  proforma_ver INT  NOT NULL,
  status       TEXT NOT NULL DEFAULT 'pending',  -- pending|running|done|failed
  error        TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reports (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id      UUID NOT NULL REFERENCES report_jobs(id),
  content     JSONB NOT NULL,                -- ReportContent schema (LLD §11.4)
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- RAG knowledge base
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS principles (
  id            TEXT PRIMARY KEY,            -- e.g. 'emergency_fund'
  statement     TEXT NOT NULL,
  rule_of_thumb TEXT NOT NULL,
  what_to_check TEXT NOT NULL,
  sources       JSONB NOT NULL               -- [{title, url}]
);

CREATE TABLE IF NOT EXISTS principle_chunks (
  id           BIGSERIAL PRIMARY KEY,
  principle_id TEXT NOT NULL REFERENCES principles(id),
  chunk_text   TEXT NOT NULL,
  embedding    VECTOR(768)                   -- Gemini text-embedding-004 dim (OQ-L1 resolved); matches EMBEDDINGS_DIM
);
CREATE INDEX IF NOT EXISTS idx_principle_chunks_embedding
  ON principle_chunks USING hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- Observability (SG4)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS llm_calls (
  id             BIGSERIAL PRIMARY KEY,
  prompt_name    TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  model          TEXT NOT NULL,
  tokens_in      INT,
  tokens_out     INT,
  latency_ms     INT,
  outcome        TEXT NOT NULL,              -- success|repaired|validation_failed|error
  retries        INT NOT NULL DEFAULT 0,
  session_id     UUID,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
