-- XDM (XDS-I) document set export (xds-i-export feature).
-- Produces a portable standards package (KOS + DICOM + ebRIM METADATA.XML) a
-- receiving XDS/XDM-capable institution can ingest. Idempotent.
CREATE TABLE IF NOT EXISTS xds_export_requests (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  study_uids JSONB NOT NULL,
  patient_id VARCHAR(64),
  status VARCHAR(16) NOT NULL DEFAULT 'processing',  -- processing|ready|failed|expired
  study_count INT,
  package_path TEXT,
  package_bytes BIGINT,
  error TEXT,
  requested_by VARCHAR(128),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ready_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_xds_status ON xds_export_requests(status, created_at DESC);
