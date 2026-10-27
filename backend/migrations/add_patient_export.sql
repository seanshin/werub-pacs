-- Patient result export requests (patient-portal feature).
-- The external patient portal asks (via HIS shared-secret service token) for a
-- patient's DICOM + final report; PACS packages it encrypted and hands it back
-- through a one-time gateway. Decrypt key / download token live in Redis only.
-- Idempotent. Apply to openpacs DB.
CREATE TABLE IF NOT EXISTS patient_export_requests (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  mrn VARCHAR(64) NOT NULL,
  study_uids JSONB,                                  -- null = all studies of the patient
  purpose VARCHAR(64) NOT NULL DEFAULT 'patient_view',
  status VARCHAR(16) NOT NULL DEFAULT 'processing',  -- processing|ready|failed|expired|consumed
  study_count INT,
  package_path TEXT,
  package_bytes BIGINT,
  error TEXT,
  requester_ip VARCHAR(64),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ready_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  consumed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_per_mrn ON patient_export_requests(mrn, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_per_status ON patient_export_requests(status, created_at DESC);
