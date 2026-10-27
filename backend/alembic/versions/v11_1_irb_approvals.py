"""Add irb_approvals table (IRB approval registry).

Standalone, idempotent — CREATE TABLE IF NOT EXISTS so it is safe to re-run and
can be applied directly via psql to match runtime-created tables.

Revision ID: v11_1_irb
"""
from alembic import op

revision = "v11_1_irb"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS irb_approvals (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            protocol_number VARCHAR(64) NOT NULL UNIQUE,
            title VARCHAR(256) NOT NULL,
            principal_investigator VARCHAR(128),
            institution VARCHAR(256),
            approved_at DATE,
            expires_at DATE,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            scope_note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_irb_approvals_protocol_number "
        "ON irb_approvals (protocol_number)"
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS irb_approvals")
