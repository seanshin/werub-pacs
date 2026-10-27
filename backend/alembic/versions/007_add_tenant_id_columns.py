"""Add tenant_id columns to existing domain tables for multi-tenancy isolation.

Revision ID: 007
Create Date: 2026-05-18

Adds tenant_id (VARCHAR(36), NOT NULL, default='default') with FK to tenants(id)
and index to: reports, worklist_items, batch_jobs, audit_logs,
import_history, study_annotations, shared_links, followups.
"""
from alembic import op
import sqlalchemy as sa

revision = '007'
down_revision = '006'

TABLES = [
    'reports',
    'worklist_items',
    'batch_jobs',
    'audit_logs',
    'import_history',
    'study_annotations',
    'shared_links',
    'followups',
]


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                'tenant_id',
                sa.String(36),
                nullable=False,
                server_default='default',
            ),
        )
        op.create_index(
            f'ix_{table}_tenant_id',
            table,
            ['tenant_id'],
        )
        op.create_foreign_key(
            f'fk_{table}_tenant_id',
            table,
            'tenants',
            ['tenant_id'],
            ['id'],
            ondelete='CASCADE',
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_constraint(f'fk_{table}_tenant_id', table, type_='foreignkey')
        op.drop_index(f'ix_{table}_tenant_id', table_name=table)
        op.drop_column(table, 'tenant_id')
