-- IOCM Archive table for DICOM Study/Series lifecycle management
-- Run on openpacs database

CREATE TYPE archive_reason_enum AS ENUM (
    'quality_reject', 'patient_safety', 'worklist_error',
    'retention_expired', 'superseded', 'storage_migration', 'manual'
);

CREATE TYPE storage_type_enum AS ENUM ('local', 's3', 'glacier');

CREATE TABLE archived_studies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Original DICOM identifiers
    study_instance_uid VARCHAR(128) NOT NULL,
    series_instance_uid VARCHAR(128),
    orthanc_study_id VARCHAR(64),
    orthanc_series_id VARCHAR(64),

    -- Patient info snapshot
    patient_id VARCHAR(64) NOT NULL,
    patient_name VARCHAR(256),
    patient_birth_date VARCHAR(16),
    patient_sex VARCHAR(4),

    -- Study info snapshot
    modality VARCHAR(16),
    study_date VARCHAR(16),
    study_description VARCHAR(256),
    series_count INTEGER DEFAULT 0,
    instance_count INTEGER DEFAULT 0,

    -- Archive reason & audit
    reason archive_reason_enum NOT NULL,
    note TEXT,
    rejection_code VARCHAR(16),

    -- Who archived
    archived_by UUID,
    archived_by_name VARCHAR(128),
    archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Original metadata
    orthanc_metadata JSONB,

    -- Thumbnail & preview
    thumbnail BYTEA,
    preview_path VARCHAR(512),

    -- Storage
    storage_path VARCHAR(512),
    storage_type storage_type_enum DEFAULT 'local',
    file_size_bytes BIGINT DEFAULT 0,

    -- Restore tracking
    is_restorable BOOLEAN DEFAULT TRUE,
    restored_at TIMESTAMPTZ,
    restored_by UUID,
    restored_by_name VARCHAR(128),

    -- Linked report
    original_report_id UUID,

    -- Retention
    retention_expires_at TIMESTAMPTZ,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_archived_studies_study_uid ON archived_studies(study_instance_uid);
CREATE INDEX idx_archived_studies_patient_id ON archived_studies(patient_id);
CREATE INDEX idx_archived_studies_reason ON archived_studies(reason);
CREATE INDEX idx_archived_studies_archived_at ON archived_studies(archived_at DESC);
CREATE INDEX idx_archived_studies_retention ON archived_studies(retention_expires_at)
    WHERE restored_at IS NULL;
