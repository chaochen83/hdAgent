ALTER TABLE app_user
  ADD COLUMN IF NOT EXISTS role VARCHAR(16) NOT NULL DEFAULT 'user',
  ADD COLUMN IF NOT EXISTS quota_tier_code VARCHAR(32),
  ADD COLUMN IF NOT EXISTS invited_by_code VARCHAR(64),
  ADD COLUMN IF NOT EXISTS notes TEXT,
  ADD COLUMN IF NOT EXISTS is_unlimited BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS quota_tier (
  code VARCHAR(32) PRIMARY KEY,
  name VARCHAR(64) NOT NULL,
  daily_token_limit INTEGER,
  sort_order INTEGER NOT NULL DEFAULT 0,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO quota_tier (code, name, daily_token_limit, sort_order)
VALUES
  ('basic', 'Basic', 50000, 10),
  ('pro', 'Pro', 150000, 20),
  ('vip', 'VIP', 500000, 30)
ON CONFLICT (code) DO NOTHING;

DO
$$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.table_constraints
    WHERE constraint_name = 'fk_app_user_quota_tier'
      AND table_name = 'app_user'
  ) THEN
    ALTER TABLE app_user
      ADD CONSTRAINT fk_app_user_quota_tier
      FOREIGN KEY (quota_tier_code) REFERENCES quota_tier(code) ON DELETE SET NULL;
  END IF;
END
$$;

UPDATE app_user
SET quota_tier_code = 'basic'
WHERE role = 'user'
  AND quota_tier_code IS NULL;

CREATE TABLE IF NOT EXISTS invite_code (
  code VARCHAR(64) PRIMARY KEY,
  created_by_user_id BIGINT REFERENCES app_user(id) ON DELETE SET NULL,
  assigned_quota_tier_code VARCHAR(32) REFERENCES quota_tier(code) ON DELETE SET NULL,
  max_uses INTEGER NOT NULL DEFAULT 1,
  used_count INTEGER NOT NULL DEFAULT 0,
  expires_at TIMESTAMPTZ,
  status VARCHAR(16) NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_invite_code_status_created_at
  ON invite_code(status, created_at DESC);

CREATE TABLE IF NOT EXISTS chat_request_log (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_request_log_user_id_created_at
  ON chat_request_log(user_id, created_at DESC);
