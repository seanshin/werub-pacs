-- Shift-based reading assignment (backlog #7)
-- Idempotent. Applied to openpacs DB.
CREATE TABLE IF NOT EXISTS reading_assignments (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  study_instance_uid VARCHAR(128) NOT NULL,
  patient_id VARCHAR(64),
  patient_name VARCHAR(256),
  modality VARCHAR(32),
  assigned_to_username VARCHAR(128) NOT NULL,
  assigned_to_name VARCHAR(256),
  assignment_type VARCHAR(16) NOT NULL DEFAULT 'shift',  -- shift | manual | escalation
  status VARCHAR(16) NOT NULL DEFAULT 'pending',         -- pending | in_progress | completed
  oncall_id UUID,                                         -- source oncall_schedule row, if any
  is_current BOOLEAN NOT NULL DEFAULT true,               -- only one current assignment per study
  assigned_by VARCHAR(128),
  assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_ra_study ON reading_assignments(study_instance_uid);
CREATE INDEX IF NOT EXISTS idx_ra_assignee ON reading_assignments(assigned_to_username);
CREATE INDEX IF NOT EXISTS idx_ra_current ON reading_assignments(is_current, status);
-- H3: 한 study에 is_current=true 배정은 1개만(동시 배정 race로 복수 current 생성 방지)
CREATE UNIQUE INDEX IF NOT EXISTS uq_reading_assignments_current
  ON reading_assignments(study_instance_uid) WHERE is_current;
