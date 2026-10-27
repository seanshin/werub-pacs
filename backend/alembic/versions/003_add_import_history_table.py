"""Add import_history table for CD/DVD import tracking.

Revision ID: 003
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'import_history',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('filename', sa.String(512), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('user_id', sa.String(128), nullable=False),
        sa.Column('dicomdir_result', postgresql.JSONB, nullable=True),
        sa.Column('total_files', sa.Integer, server_default='0'),
        sa.Column('total_studies', sa.Integer, server_default='0'),
        sa.Column('total_patients', sa.Integer, server_default='0'),
        sa.Column('uploaded_files', sa.Integer, server_default='0'),
        sa.Column('skipped_files', sa.Integer, server_default='0'),
        sa.Column('failed_files', sa.Integer, server_default='0'),
        sa.Column('duplicate_studies', postgresql.JSONB, nullable=True),
        sa.Column('errors', postgresql.JSONB, nullable=True),
        sa.Column('temp_dir', sa.String(512), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_import_history_status', 'import_history', ['status'])
    op.create_index('ix_import_history_user', 'import_history', ['user_id'])
    op.create_index('ix_import_history_created', 'import_history', ['created_at'])


def downgrade() -> None:
    op.drop_table('import_history')
