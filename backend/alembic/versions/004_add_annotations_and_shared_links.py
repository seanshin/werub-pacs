"""Add study_annotations and shared_links tables.

Revision ID: 004
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '004'
down_revision = '003'


def upgrade() -> None:
    op.create_table(
        'study_annotations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('study_uid', sa.String(128), nullable=False),
        sa.Column('user_id', sa.String(128), nullable=False),
        sa.Column('measurements', postgresql.JSONB, default=[]),
        sa.Column('key_images', postgresql.JSONB, default=[]),
        sa.Column('notes', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_annotations_study', 'study_annotations', ['study_uid'])
    op.create_index('ix_annotations_user', 'study_annotations', ['user_id'])

    op.create_table(
        'shared_links',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('study_uid', sa.String(128), nullable=False),
        sa.Column('token', sa.String(64), nullable=False, unique=True),
        sa.Column('anonymize', sa.Boolean, default=True),
        sa.Column('created_by', sa.String(128)),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_shared_links_token', 'shared_links', ['token'])


def downgrade() -> None:
    op.drop_table('shared_links')
    op.drop_table('study_annotations')
