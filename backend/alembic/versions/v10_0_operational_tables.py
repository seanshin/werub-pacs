"""v10.0: Create operational tables (previously runtime DDL)

These tables were previously created via _ensure_table() in API handlers.
Now managed by Alembic for proper migration tracking.

Revision ID: v10_0_ops
Revises: None (standalone — these tables may already exist)
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v10_0_ops"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # openpacs_config — shared config store
    op.execute("""
        CREATE TABLE IF NOT EXISTS openpacs_config (
            key TEXT PRIMARY KEY,
            value JSONB NOT NULL DEFAULT '{}',
            updated_by TEXT,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # retake_requests
    op.execute("""
        CREATE TABLE IF NOT EXISTS retake_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            study_instance_uid TEXT NOT NULL,
            reason TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'quality',
            urgency TEXT NOT NULL DEFAULT 'routine',
            status TEXT NOT NULL DEFAULT 'requested',
            notes TEXT,
            requested_by TEXT NOT NULL,
            requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            reviewed_by TEXT,
            reviewed_at TIMESTAMPTZ,
            reviewer_notes TEXT,
            scheduled_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            patient_id TEXT,
            patient_name TEXT,
            modality TEXT,
            study_description TEXT
        )
    """)

    # sla_escalation_log
    op.execute("""
        CREATE TABLE IF NOT EXISTS sla_escalation_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            study_instance_uid TEXT NOT NULL,
            escalation_type TEXT NOT NULL,
            action_taken TEXT NOT NULL,
            from_user TEXT,
            to_user TEXT,
            notes TEXT,
            triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved_at TIMESTAMPTZ,
            sla_minutes INT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_sla_esc_study ON sla_escalation_log(study_instance_uid)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sla_esc_time ON sla_escalation_log(triggered_at DESC)")

    # his_requests
    op.execute("""
        CREATE TABLE IF NOT EXISTS his_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            request_type TEXT NOT NULL,
            accession_number TEXT,
            study_instance_uid TEXT,
            patient_id TEXT NOT NULL,
            patient_name TEXT,
            status TEXT NOT NULL DEFAULT 'received',
            payload JSONB NOT NULL DEFAULT '{}',
            requested_by TEXT,
            requesting_department TEXT,
            his_order_id TEXT,
            callback_url TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            processed_at TIMESTAMPTZ,
            processed_by TEXT,
            result JSONB
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_his_req_type ON his_requests(request_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_his_req_acc ON his_requests(accession_number)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_his_req_patient ON his_requests(patient_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS his_requests CASCADE")
    op.execute("DROP TABLE IF EXISTS sla_escalation_log CASCADE")
    op.execute("DROP TABLE IF EXISTS retake_requests CASCADE")
    # openpacs_config is shared — don't drop
