-- 3D 사용 텔레메트리 (vrt-rendering Phase 1) — 서버 GPU 렌더(Phase 2) 수요 근거.
-- Idempotent. Apply to openpacs DB.
CREATE TABLE IF NOT EXISTS vrt_metrics (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  study_instance_uid VARCHAR(128) NOT NULL,
  username VARCHAR(128) NOT NULL,
  protocol_id VARCHAR(64) NOT NULL,        -- main3D | only3D | primary3D | mprAnd3DVolumeViewport | fourUp
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_vrt_metrics_created ON vrt_metrics(created_at DESC);
