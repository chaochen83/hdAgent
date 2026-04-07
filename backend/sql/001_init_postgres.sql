-- =========================================================
-- Makerfabs Agent bootstrap SQL
-- Target: PostgreSQL 15+ with pgvector
-- Usage:
--   1. Run the role/database statements as a superuser.
--   2. Connect to the new database.
--   3. Install/enable pgvector and run the schema statements.
-- =========================================================

-- -------------------------
-- 1) Create app role
-- -------------------------
DO
$$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hdagent_app') THEN
    CREATE ROLE hdagent_app LOGIN PASSWORD 'change_me_now';
  END IF;
END
$$;

-- -------------------------
-- 2) Create app database
-- -------------------------
SELECT 'CREATE DATABASE hdagent OWNER hdagent_app ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'hdagent')
\gexec

-- --------------------------------------------------
-- 3) Connect to the app database before continuing
-- --------------------------------------------------
\connect hdagent

ALTER DATABASE hdagent OWNER TO hdagent_app;
ALTER SCHEMA public OWNER TO hdagent_app;

-- -----------------------------------------------------------
-- 4) Enable pgvector
--    If CREATE EXTENSION fails, install pgvector first:
--    - Docker:
--      docker run --name makerfabs-pg -e POSTGRES_PASSWORD=postgres \
--        -e POSTGRES_DB=hdagent -p 5432:5432 pgvector/pgvector:pg16
--    - Homebrew PostgreSQL:
--      brew install pgvector
--      then run: CREATE EXTENSION vector;
-- -----------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS vector;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

SET search_path TO public;
GRANT USAGE, CREATE ON SCHEMA public TO hdagent_app;
SET ROLE hdagent_app;

-- -------------------------
-- 5) Users and auth
-- -------------------------
CREATE TABLE IF NOT EXISTS app_user (
  id BIGSERIAL PRIMARY KEY,
  email CITEXT UNIQUE,
  display_name VARCHAR(120) NOT NULL,
  avatar_url TEXT,
  locale VARCHAR(32) NOT NULL DEFAULT 'zh-CN',
  timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  is_email_verified BOOLEAN NOT NULL DEFAULT FALSE,
  last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_identity (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  provider VARCHAR(32) NOT NULL,
  provider_subject VARCHAR(255) NOT NULL,
  provider_email VARCHAR(255),
  provider_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (provider, provider_subject)
);

CREATE INDEX IF NOT EXISTS idx_user_identity_user_id ON user_identity(user_id);

CREATE TABLE IF NOT EXISTS email_login_code (
  id BIGSERIAL PRIMARY KEY,
  email CITEXT NOT NULL,
  code_hash CHAR(64) NOT NULL,
  purpose VARCHAR(32) NOT NULL DEFAULT 'login',
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ,
  send_attempts INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_login_code_email_created_at
  ON email_login_code(email, created_at DESC);

CREATE TABLE IF NOT EXISTS auth_session (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  session_token_hash CHAR(64) NOT NULL UNIQUE,
  user_agent TEXT,
  ip_address INET,
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auth_session_user_id ON auth_session(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_session_expires_at ON auth_session(expires_at);

-- -------------------------
-- 6) Chat
-- -------------------------
CREATE TABLE IF NOT EXISTS chat_session (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  title VARCHAR(200) NOT NULL DEFAULT 'New chat',
  current_product_model VARCHAR(120),
  provider VARCHAR(32) NOT NULL DEFAULT 'openai',
  model VARCHAR(120),
  archived_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_message_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_session_user_id_last_message_at
  ON chat_session(user_id, last_message_at DESC);

CREATE TABLE IF NOT EXISTS chat_message (
  id BIGSERIAL PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES chat_session(id) ON DELETE CASCADE,
  role VARCHAR(16) NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
  content TEXT NOT NULL,
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  latency_ms INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_message_session_id_created_at
  ON chat_message(session_id, created_at ASC, id ASC);

CREATE TABLE IF NOT EXISTS usage_event (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  session_id UUID REFERENCES chat_session(id) ON DELETE SET NULL,
  provider VARCHAR(32) NOT NULL,
  model VARCHAR(120),
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  estimated_cost_usd NUMERIC(12, 6) NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usage_event_user_id_created_at
  ON usage_event(user_id, created_at DESC);

-- -------------------------
-- 7) Knowledge base
--    Phase 1 only prepares schema.
-- -------------------------
CREATE TABLE IF NOT EXISTS knowledge_base (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id BIGINT REFERENCES app_user(id) ON DELETE SET NULL,
  name VARCHAR(160) NOT NULL,
  description TEXT,
  visibility VARCHAR(32) NOT NULL DEFAULT 'private',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS knowledge_document (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  knowledge_base_id UUID NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
  source_type VARCHAR(32) NOT NULL DEFAULT 'file',
  source_name VARCHAR(255) NOT NULL,
  file_name VARCHAR(255),
  file_ext VARCHAR(24),
  mime_type VARCHAR(120),
  storage_path TEXT,
  checksum_sha256 CHAR(64),
  parse_status VARCHAR(32) NOT NULL DEFAULT 'uploaded',
  parse_error TEXT,
  chunk_count INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_document_kb_id_created_at
  ON knowledge_document(knowledge_base_id, created_at DESC);

CREATE TABLE IF NOT EXISTS knowledge_chunk (
  id BIGSERIAL PRIMARY KEY,
  knowledge_document_id UUID NOT NULL REFERENCES knowledge_document(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  token_count INTEGER NOT NULL DEFAULT 0,
  embedding VECTOR(1536),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (knowledge_document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_document_id
  ON knowledge_chunk(knowledge_document_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_embedding_cosine
  ON knowledge_chunk
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

CREATE TABLE IF NOT EXISTS knowledge_job (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  knowledge_document_id UUID NOT NULL REFERENCES knowledge_document(id) ON DELETE CASCADE,
  job_type VARCHAR(32) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_job_document_id_created_at
  ON knowledge_job(knowledge_document_id, created_at DESC);

-- -------------------------
-- 8) Trigger for updated_at
-- -------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS
$$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_app_user_updated_at ON app_user;
CREATE TRIGGER trg_app_user_updated_at
BEFORE UPDATE ON app_user
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_user_identity_updated_at ON user_identity;
CREATE TRIGGER trg_user_identity_updated_at
BEFORE UPDATE ON user_identity
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_chat_session_updated_at ON chat_session;
CREATE TRIGGER trg_chat_session_updated_at
BEFORE UPDATE ON chat_session
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_knowledge_base_updated_at ON knowledge_base;
CREATE TRIGGER trg_knowledge_base_updated_at
BEFORE UPDATE ON knowledge_base
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_knowledge_document_updated_at ON knowledge_document;
CREATE TRIGGER trg_knowledge_document_updated_at
BEFORE UPDATE ON knowledge_document
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_knowledge_job_updated_at ON knowledge_job;
CREATE TRIGGER trg_knowledge_job_updated_at
BEFORE UPDATE ON knowledge_job
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

RESET ROLE;

ALTER TABLE app_user OWNER TO hdagent_app;
ALTER TABLE user_identity OWNER TO hdagent_app;
ALTER TABLE email_login_code OWNER TO hdagent_app;
ALTER TABLE auth_session OWNER TO hdagent_app;
ALTER TABLE chat_session OWNER TO hdagent_app;
ALTER TABLE chat_message OWNER TO hdagent_app;
ALTER TABLE usage_event OWNER TO hdagent_app;
ALTER TABLE knowledge_base OWNER TO hdagent_app;
ALTER TABLE knowledge_document OWNER TO hdagent_app;
ALTER TABLE knowledge_chunk OWNER TO hdagent_app;
ALTER TABLE knowledge_job OWNER TO hdagent_app;

ALTER SEQUENCE app_user_id_seq OWNER TO hdagent_app;
ALTER SEQUENCE user_identity_id_seq OWNER TO hdagent_app;
ALTER SEQUENCE email_login_code_id_seq OWNER TO hdagent_app;
ALTER SEQUENCE auth_session_id_seq OWNER TO hdagent_app;
ALTER SEQUENCE chat_message_id_seq OWNER TO hdagent_app;
ALTER SEQUENCE usage_event_id_seq OWNER TO hdagent_app;
ALTER SEQUENCE knowledge_chunk_id_seq OWNER TO hdagent_app;
ALTER SEQUENCE knowledge_job_id_seq OWNER TO hdagent_app;

ALTER FUNCTION set_updated_at() OWNER TO hdagent_app;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO hdagent_app;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO hdagent_app;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO hdagent_app;

ALTER DEFAULT PRIVILEGES FOR ROLE hdagent_app IN SCHEMA public
GRANT ALL PRIVILEGES ON TABLES TO hdagent_app;

ALTER DEFAULT PRIVILEGES FOR ROLE hdagent_app IN SCHEMA public
GRANT ALL PRIVILEGES ON SEQUENCES TO hdagent_app;

ALTER DEFAULT PRIVILEGES FOR ROLE hdagent_app IN SCHEMA public
GRANT ALL PRIVILEGES ON FUNCTIONS TO hdagent_app;
