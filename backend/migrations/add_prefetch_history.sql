-- Predictive prefetch history (3d-ai-performance Track A)
-- Records every warm attempt; `hit` is flipped when the study is actually opened
-- within 24h, which is both the accuracy metric and future ML training data.
-- Idempotent. Apply to openpacs DB.
CREATE TABLE IF NOT EXISTS prefetch_history (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  study_instance_uid VARCHAR(128) NOT NULL,
  predicted_for VARCHAR(128) NOT NULL,           -- username the warm was made for
  trigger_type VARCHAR(16) NOT NULL,             -- study_opened | assignment
  reason VARCHAR(32) NOT NULL,                   -- next_in_worklist | prior | assignment
  warmed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  frames_warmed INT NOT NULL DEFAULT 0,
  bytes_warmed BIGINT NOT NULL DEFAULT 0,
  duration_ms INT,
  status VARCHAR(16) NOT NULL DEFAULT 'done',    -- done | partial | failed | skipped
  hit BOOLEAN NOT NULL DEFAULT false,
  hit_at TIMESTAMPTZ,
  open_load_ms INT                               -- viewer-reported load time at hit
);
CREATE INDEX IF NOT EXISTS idx_pfh_study ON prefetch_history(study_instance_uid, warmed_at DESC);
CREATE INDEX IF NOT EXISTS idx_pfh_user ON prefetch_history(predicted_for, warmed_at DESC);

-- Viewer open events (baseline instrumentation, step 0). One row per study-open,
-- regardless of whether a prefetch existed — gives the un-warmed baseline too.
CREATE TABLE IF NOT EXISTS viewer_open_events (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  study_instance_uid VARCHAR(128) NOT NULL,
  username VARCHAR(128) NOT NULL,
  opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  load_ms INT,                                   -- mode-enter -> first image rendered
  was_prefetched BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_voe_opened ON viewer_open_events(opened_at DESC);
