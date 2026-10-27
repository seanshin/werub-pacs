-- P2 Tables Migration
-- Run: psql -U openpacs -d openpacs -f add_p2_tables.sql

-- 1. Peer Review
CREATE TABLE IF NOT EXISTS peer_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    study_instance_uid VARCHAR(128) NOT NULL,
    report_id UUID REFERENCES reports(id),
    reviewer_id UUID REFERENCES users(id) NOT NULL,
    reviewer_name VARCHAR(256) NOT NULL,
    review_type VARCHAR(32) DEFAULT 'peer_review', -- peer_review, second_opinion, quality
    agreement VARCHAR(16) DEFAULT 'agree', -- agree, minor_disagreement, major_disagreement
    comments TEXT,
    findings_addendum TEXT,
    status VARCHAR(16) DEFAULT 'pending', -- pending, completed
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_peer_reviews_study ON peer_reviews(study_instance_uid);
CREATE INDEX IF NOT EXISTS idx_peer_reviews_reviewer ON peer_reviews(reviewer_id);

-- 2. Dose Records (CT Radiation Dose)
CREATE TABLE IF NOT EXISTS dose_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    study_instance_uid VARCHAR(128) NOT NULL,
    series_instance_uid VARCHAR(128),
    patient_id VARCHAR(64) NOT NULL,
    modality VARCHAR(16) DEFAULT 'CT',
    body_part VARCHAR(64),
    -- CT dose values
    ctdi_vol DECIMAL(10,4),        -- mGy
    dlp DECIMAL(10,4),             -- mGy·cm
    effective_dose DECIMAL(10,4),  -- mSv (calculated)
    -- Scan parameters
    kvp INTEGER,
    mas DECIMAL(10,2),
    scan_length DECIMAL(10,2),     -- cm
    -- Reference
    protocol_name VARCHAR(256),
    station_name VARCHAR(64),
    operator_name VARCHAR(256),
    -- Alerts
    exceeds_drl BOOLEAN DEFAULT FALSE,  -- Diagnostic Reference Level exceeded
    alert_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dose_records_study ON dose_records(study_instance_uid);
CREATE INDEX IF NOT EXISTS idx_dose_records_patient ON dose_records(patient_id);

-- 3. Conferences
CREATE TABLE IF NOT EXISTS conferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(256) NOT NULL,
    conference_type VARCHAR(32) DEFAULT 'morbidity_mortality', -- morbidity_mortality, tumor_board, teaching, journal_club
    scheduled_at TIMESTAMPTZ,
    organizer_id UUID REFERENCES users(id),
    organizer_name VARCHAR(256),
    status VARCHAR(16) DEFAULT 'scheduled', -- scheduled, in_progress, completed, cancelled
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conference_cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conference_id UUID REFERENCES conferences(id) ON DELETE CASCADE,
    study_instance_uid VARCHAR(128) NOT NULL,
    patient_id VARCHAR(64),
    presenter_name VARCHAR(256),
    clinical_history TEXT,
    teaching_points TEXT,
    diagnosis TEXT,
    discussion TEXT,
    order_index INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_conference_cases_conf ON conference_cases(conference_id);

-- 4. Second Opinions
CREATE TABLE IF NOT EXISTS second_opinions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    study_instance_uid VARCHAR(128) NOT NULL,
    original_report_id UUID REFERENCES reports(id),
    requested_by_id UUID REFERENCES users(id),
    requested_by_name VARCHAR(256),
    assigned_to_id UUID REFERENCES users(id),
    assigned_to_name VARCHAR(256),
    reason TEXT,
    opinion TEXT,
    status VARCHAR(16) DEFAULT 'requested', -- requested, in_progress, completed
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. Report preliminary fields (if not already added by ORM migration)
ALTER TABLE reports ADD COLUMN IF NOT EXISTS preliminary_by_id UUID REFERENCES users(id);
ALTER TABLE reports ADD COLUMN IF NOT EXISTS preliminary_by_name VARCHAR(256);
ALTER TABLE reports ADD COLUMN IF NOT EXISTS preliminary_at TIMESTAMPTZ;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS preliminary_content JSONB;

-- 6. Study comments
CREATE TABLE IF NOT EXISTS study_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    study_instance_uid VARCHAR(128) NOT NULL,
    comment TEXT NOT NULL,
    comment_type VARCHAR(32) DEFAULT 'general', -- general, quality_issue, technologist_note, clinical_info
    author_id UUID REFERENCES users(id),
    author_name VARCHAR(256),
    author_role VARCHAR(32),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_study_comments_study ON study_comments(study_instance_uid);

-- 7. Imaging protocols
CREATE TABLE IF NOT EXISTS imaging_protocols (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(256) NOT NULL,
    modality VARCHAR(16) NOT NULL,
    body_part VARCHAR(64),
    description TEXT,
    parameters JSONB DEFAULT '{}',
    is_default BOOLEAN DEFAULT FALSE,
    created_by VARCHAR(256),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_protocols_modality ON imaging_protocols(modality);

-- 8. On-call schedule
CREATE TABLE IF NOT EXISTS oncall_schedule (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    radiologist_id UUID REFERENCES users(id),
    radiologist_username VARCHAR(128),
    radiologist_name VARCHAR(256),
    schedule_date DATE NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    is_primary BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_oncall_date ON oncall_schedule(schedule_date);

-- 9. External consults (외부 판독 의뢰)
CREATE TABLE IF NOT EXISTS external_consults (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    study_instance_uid VARCHAR(128) NOT NULL,
    report_id UUID,
    consult_type VARCHAR(32) DEFAULT 'external_read',
    institution_name VARCHAR(256),
    physician_name VARCHAR(256),
    physician_email VARCHAR(256),
    reason TEXT,
    clinical_info TEXT,
    urgency VARCHAR(16) DEFAULT 'routine',
    share_method VARCHAR(32) DEFAULT 'link',
    share_link_id UUID,
    status VARCHAR(16) DEFAULT 'requested',
    external_findings TEXT,
    external_impression TEXT,
    external_report_pdf TEXT,
    requested_by_id UUID,
    requested_by_name VARCHAR(256),
    requested_at TIMESTAMPTZ DEFAULT NOW(),
    responded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ext_consult_study ON external_consults(study_instance_uid);
CREATE INDEX IF NOT EXISTS idx_ext_consult_status ON external_consults(status);

-- 10. Access tokens for external portal
ALTER TABLE external_consults ADD COLUMN IF NOT EXISTS access_token VARCHAR(64) UNIQUE;
ALTER TABLE second_opinions ADD COLUMN IF NOT EXISTS access_token VARCHAR(64) UNIQUE;

-- 11. Consult consent records
CREATE TABLE IF NOT EXISTS consult_consents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    consult_token VARCHAR(64) NOT NULL,
    respondent_name VARCHAR(256) NOT NULL,
    respondent_institution VARCHAR(256),
    agreed_terms TEXT NOT NULL,
    ip_address VARCHAR(64),
    consented_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_consult_consent_token ON consult_consents(consult_token);

-- 12. External accounts (승인된 외부 기관)
CREATE TABLE IF NOT EXISTS external_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    institution_name VARCHAR(256) NOT NULL,
    physician_name VARCHAR(256) NOT NULL,
    physician_email VARCHAR(256) NOT NULL,
    specialties VARCHAR(256),
    notes TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_by VARCHAR(128),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ext_accounts_inst ON external_accounts(institution_name);
