"""Add structured_report_data and followups tables.

Revision ID: 005
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '005'
down_revision = '004'


def upgrade() -> None:
    op.create_table(
        'structured_report_data',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('report_id', sa.String(36), nullable=False),
        sa.Column('schema_type', sa.String(32), nullable=False),
        sa.Column('data', postgresql.JSONB, nullable=False),
        sa.Column('category', sa.String(16)),
        sa.Column('narrative', sa.Text),
        sa.Column('created_by', sa.String(128)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('report_id', 'schema_type', name='uq_sr_report_schema'),
    )
    op.create_index('ix_sr_report_id', 'structured_report_data', ['report_id'])
    op.create_index('ix_sr_schema_type', 'structured_report_data', ['schema_type'])

    op.create_table(
        'followups',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('report_id', sa.String(36)),
        sa.Column('patient_id', sa.String(64), nullable=False),
        sa.Column('study_instance_uid', sa.String(128)),
        sa.Column('recommended_date', sa.Date, nullable=False),
        sa.Column('reason', sa.Text, nullable=False),
        sa.Column('category', sa.String(32)),
        sa.Column('status', sa.String(16), server_default='pending'),
        sa.Column('completed_study_uid', sa.String(128)),
        sa.Column('notified_at', sa.DateTime(timezone=True)),
        sa.Column('created_by', sa.String(128)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_followups_patient', 'followups', ['patient_id'])
    op.create_index('ix_followups_status', 'followups', ['status'])
    op.create_index('ix_followups_date', 'followups', ['recommended_date'])


def downgrade() -> None:
    op.drop_table('followups')
    op.drop_table('structured_report_data')
