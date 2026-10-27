-- AI model governance: daily performance rollup (ai-governance feature).
-- Time-series per model from inference_jobs + screening acceptance, the basis
-- for drift detection. Idempotent. Apply to openpacs DB.
CREATE TABLE IF NOT EXISTS model_performance_daily (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  day DATE NOT NULL,
  model_name VARCHAR(128) NOT NULL,
  total_jobs INT NOT NULL DEFAULT 0,
  completed INT NOT NULL DEFAULT 0,
  failed INT NOT NULL DEFAULT 0,
  success_rate FLOAT,
  avg_inference_ms INT,
  critical_count INT NOT NULL DEFAULT 0,
  screened_actionable INT NOT NULL DEFAULT 0,
  acknowledged INT NOT NULL DEFAULT 0,
  dismissed INT NOT NULL DEFAULT 0,
  acceptance_rate FLOAT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (day, model_name)
);
CREATE INDEX IF NOT EXISTS idx_mpd_model_day ON model_performance_daily(model_name, day DESC);
