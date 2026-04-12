-- hdAgent knowledge RAG migration
-- Target: PostgreSQL 15+ with pgvector

SET client_encoding = 'UTF8';

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS board_type (
  id BIGSERIAL PRIMARY KEY,
  code VARCHAR(80) NOT NULL UNIQUE,
  name VARCHAR(160) NOT NULL UNIQUE,
  description TEXT,
  default_hint TEXT,
  is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_by BIGINT REFERENCES app_user(id) ON DELETE SET NULL,
  updated_by BIGINT REFERENCES app_user(id) ON DELETE SET NULL,
  deleted_at TIMESTAMPTZ,
  deleted_by BIGINT REFERENCES app_user(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS board_alias (
  id BIGSERIAL PRIMARY KEY,
  board_type_id BIGINT NOT NULL REFERENCES board_type(id) ON DELETE RESTRICT,
  alias VARCHAR(160) NOT NULL,
  normalized_alias VARCHAR(160) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (board_type_id, normalized_alias),
  UNIQUE (normalized_alias)
);

CREATE INDEX IF NOT EXISTS idx_board_alias_board_type_id
  ON board_alias(board_type_id);

CREATE TABLE IF NOT EXISTS knowledge_document_v2 (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  board_type_id BIGINT NOT NULL REFERENCES board_type(id) ON DELETE RESTRICT,
  title VARCHAR(255) NOT NULL,
  knowledge_type VARCHAR(32) NOT NULL,
  source_type VARCHAR(32) NOT NULL,
  source_name VARCHAR(255) NOT NULL,
  source_url TEXT,
  raw_text TEXT,
  file_name VARCHAR(255),
  file_ext VARCHAR(24),
  mime_type VARCHAR(120),
  storage_path TEXT,
  file_size BIGINT,
  checksum_sha256 CHAR(64),
  parse_status VARCHAR(32) NOT NULL DEFAULT 'queued',
  parse_error TEXT,
  chunk_count INTEGER NOT NULL DEFAULT 0,
  token_count INTEGER NOT NULL DEFAULT 0,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by BIGINT REFERENCES app_user(id) ON DELETE SET NULL,
  updated_by BIGINT REFERENCES app_user(id) ON DELETE SET NULL,
  deleted_at TIMESTAMPTZ,
  deleted_by BIGINT REFERENCES app_user(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_document_v2_board_created
  ON knowledge_document_v2(board_type_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_knowledge_document_v2_board_status
  ON knowledge_document_v2(board_type_id, parse_status);

CREATE INDEX IF NOT EXISTS idx_knowledge_document_v2_not_deleted
  ON knowledge_document_v2(board_type_id, updated_at DESC)
  WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS knowledge_chunk_v2 (
  id BIGSERIAL PRIMARY KEY,
  knowledge_document_id UUID NOT NULL REFERENCES knowledge_document_v2(id) ON DELETE CASCADE,
  board_type_id BIGINT NOT NULL REFERENCES board_type(id) ON DELETE RESTRICT,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  content_tsv TSVECTOR,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  token_count INTEGER NOT NULL DEFAULT 0,
  embedding VECTOR(1536),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (knowledge_document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_v2_document_id
  ON knowledge_chunk_v2(knowledge_document_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_v2_board_type_id
  ON knowledge_chunk_v2(board_type_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_v2_tsv
  ON knowledge_chunk_v2 USING GIN(content_tsv);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_v2_embedding_cosine
  ON knowledge_chunk_v2
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

CREATE TABLE IF NOT EXISTS knowledge_job_v2 (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  knowledge_document_id UUID NOT NULL REFERENCES knowledge_document_v2(id) ON DELETE CASCADE,
  board_type_id BIGINT NOT NULL REFERENCES board_type(id) ON DELETE RESTRICT,
  job_type VARCHAR(32) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  attempt_count INTEGER NOT NULL DEFAULT 0,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  result JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_message TEXT,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_job_v2_document_created
  ON knowledge_job_v2(knowledge_document_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_knowledge_job_v2_board_status
  ON knowledge_job_v2(board_type_id, status, created_at DESC);

CREATE OR REPLACE FUNCTION knowledge_set_updated_at()
RETURNS TRIGGER AS
$$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION knowledge_chunk_v2_set_tsv()
RETURNS TRIGGER AS
$$
BEGIN
  NEW.content_tsv = to_tsvector('simple', COALESCE(NEW.content, ''));
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_board_type_updated_at ON board_type;
CREATE TRIGGER trg_board_type_updated_at
BEFORE UPDATE ON board_type
FOR EACH ROW
EXECUTE FUNCTION knowledge_set_updated_at();

DROP TRIGGER IF EXISTS trg_knowledge_document_v2_updated_at ON knowledge_document_v2;
CREATE TRIGGER trg_knowledge_document_v2_updated_at
BEFORE UPDATE ON knowledge_document_v2
FOR EACH ROW
EXECUTE FUNCTION knowledge_set_updated_at();

DROP TRIGGER IF EXISTS trg_knowledge_job_v2_updated_at ON knowledge_job_v2;
CREATE TRIGGER trg_knowledge_job_v2_updated_at
BEFORE UPDATE ON knowledge_job_v2
FOR EACH ROW
EXECUTE FUNCTION knowledge_set_updated_at();

DROP TRIGGER IF EXISTS trg_knowledge_chunk_v2_tsv ON knowledge_chunk_v2;
CREATE TRIGGER trg_knowledge_chunk_v2_tsv
BEFORE INSERT OR UPDATE OF content ON knowledge_chunk_v2
FOR EACH ROW
EXECUTE FUNCTION knowledge_chunk_v2_set_tsv();

INSERT INTO board_type (code, name, description, default_hint)
VALUES
  ('matouch_esp32s3', 'MaTouch_ESP32S3', 'Makerfabs MaTouch_ESP32S3 board', '您可以让我生成一个笑脸的代码，或者帮您写触摸屏交互示例。'),
  ('esp32_s3_wroom_1', 'ESP32-S3-WROOM-1', 'Makerfabs ESP32-S3-WROOM-1 board', '您也可以让我生成 MPU-6050 串口输出代码，或者给您 I2C 接线建议。')
ON CONFLICT (code) DO NOTHING;

INSERT INTO board_alias (board_type_id, alias, normalized_alias)
SELECT bt.id, v.alias, v.normalized_alias
FROM board_type bt
JOIN (
  VALUES
    ('matouch_esp32s3', 'matouch', 'matouch'),
    ('matouch_esp32s3', 'esp32s3', 'esp32s3'),
    ('matouch_esp32s3', 'matouch_esp32s3', 'matouchesp32s3'),
    ('matouch_esp32s3', 'ma touch', 'matouch'),
    ('matouch_esp32s3', 'esp32 s3', 'esp32s3'),
    ('esp32_s3_wroom_1', 'esp32-s3-wroom-1', 'esp32s3wroom1'),
    ('esp32_s3_wroom_1', 'wroom-1', 'wroom1'),
    ('esp32_s3_wroom_1', 'wroom', 'wroom'),
    ('esp32_s3_wroom_1', 'esp32 s3', 'esp32s3'),
    ('esp32_s3_wroom_1', 'esp32s3 wroom', 'esp32s3wroom'),
    ('esp32_s3_wroom_1', 'esp32-s3', 'esp32s3')
) AS v(code, alias, normalized_alias)
  ON bt.code = v.code
ON CONFLICT (normalized_alias) DO NOTHING;
