-- Opportunistic AI screening (opportunistic-ai feature).
-- Every incoming study is auto-screened by a modality-mapped model; actionable
-- results alert the reader. acknowledged/dismissed feed the AI-acceptance metric
-- (governance gap 2). Idempotent. Apply to openpacs DB.
CREATE TABLE IF NOT EXISTS ai_screening_results (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  study_instance_uid VARCHAR(128) NOT NULL UNIQUE,   -- one screening per study
  modality VARCHAR(16),
  model_name VARCHAR(128),
  inference_job_id UUID,
  status VARCHAR(16) NOT NULL DEFAULT 'pending',      -- pending|done|failed|skipped
  is_actionable BOOLEAN NOT NULL DEFAULT false,
  is_critical BOOLEAN,
  max_confidence FLOAT,
  findings JSONB,
  notified BOOLEAN NOT NULL DEFAULT false,
  acknowledged BOOLEAN NOT NULL DEFAULT false,        -- reader accepted the alert
  dismissed BOOLEAN NOT NULL DEFAULT false,           -- reader rejected the alert
  ack_at TIMESTAMPTZ,
  screened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_scr_status ON ai_screening_results(status, screened_at DESC);
CREATE INDEX IF NOT EXISTS idx_scr_actionable ON ai_screening_results(is_actionable, screened_at DESC);
