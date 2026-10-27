"""Add multi-tenancy tables (tenants, tenant_users).

Revision ID: 006
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '006'
down_revision = '005'


def upgrade() -> None:
    op.create_table(
        'tenants',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('slug', sa.String(64), nullable=False, unique=True),
        sa.Column('domain', sa.String(256)),
        sa.Column('is_active', sa.Boolean, server_default='true'),
        sa.Column('settings', postgresql.JSONB, server_default='{}'),
        sa.Column('storage_quota_gb', sa.Integer, server_default='100'),
        sa.Column('max_users', sa.Integer, server_default='50'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_tenants_slug', 'tenants', ['slug'], unique=True)

    op.create_table(
        'tenant_users',
        sa.Column('tenant_id', sa.String(36), sa.ForeignKey('tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('user_id', sa.String(36), primary_key=True),
        sa.Column('role', sa.String(32), nullable=False, server_default='radiologist'),
    )
    op.create_index('ix_tenant_users_user', 'tenant_users', ['user_id'])

    # Seed default tenant for backward compatibility
    op.execute("""
        INSERT INTO tenants (id, name, slug, domain, is_active, settings, storage_quota_gb, max_users)
        VALUES ('default', 'Default Hospital', 'default', NULL, true, '{}', 1000, 100)
    """)


def downgrade() -> None:
    op.drop_table('tenant_users')
    op.drop_table('tenants')
