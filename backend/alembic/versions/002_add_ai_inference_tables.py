"""Add AI inference tables for Phase 5

Revision ID: 002
Create Date: 2026-05-14 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    """Create AI model management and inference job tables"""

    # Table 1: ai_models
    op.create_table(
        'ai_models',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('version', sa.String(32), nullable=False),
        sa.Column('modality', sa.String(16), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('file_path', sa.String(512), nullable=False),
        sa.Column('gpu_required', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('status', sa.String(16), nullable=False, server_default='inactive'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', 'version', name='uq_ai_model_name_version'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    )

    op.create_index('idx_ai_models_status', 'ai_models', ['status'])
    op.create_index('idx_ai_models_modality', 'ai_models', ['modality'])

    # Table 2: inference_jobs
    op.create_table(
        'inference_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('model_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('study_instance_uid', sa.String(64), nullable=False),
        sa.Column('series_instance_uid', sa.String(64), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='queued'),
        sa.Column('celery_task_id', sa.String(128), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('inference_time_ms', sa.Integer(), nullable=True),
        sa.Column('confidence_score', sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['model_id'], ['ai_models.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    )

    op.create_index('idx_inference_jobs_status', 'inference_jobs', ['status'])
    op.create_index('idx_inference_jobs_model_id', 'inference_jobs', ['model_id'])
    op.create_index('idx_inference_jobs_study_uid', 'inference_jobs', ['study_instance_uid'])
    op.create_index('idx_inference_jobs_created_at', 'inference_jobs', [sa.desc('created_at')])

    # Table 3: inference_results
    op.create_table(
        'inference_results',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('job_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('dicom_type', sa.String(8), nullable=False),
        sa.Column('orthanc_id', sa.String(128), nullable=True),
        sa.Column('file_path', sa.String(512), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('job_id', name='uq_inference_result_job_id'),
        sa.ForeignKeyConstraint(['job_id'], ['inference_jobs.id'], ondelete='CASCADE'),
    )


def downgrade():
    """Drop AI inference tables"""

    op.drop_index('idx_inference_jobs_created_at', table_name='inference_jobs')
    op.drop_index('idx_inference_jobs_study_uid', table_name='inference_jobs')
    op.drop_index('idx_inference_jobs_model_id', table_name='inference_jobs')
    op.drop_index('idx_inference_jobs_status', table_name='inference_jobs')
    op.drop_table('inference_results')
    op.drop_table('inference_jobs')

    op.drop_index('idx_ai_models_modality', table_name='ai_models')
    op.drop_index('idx_ai_models_status', table_name='ai_models')
    op.drop_table('ai_models')
