"""Add mpps_sop_instance_uid to worklist_items (MPPS N-CREATE/N-SET linkage).

Standalone, idempotent — worklist_items may be a runtime-created table, so this
adds the column defensively.

Revision ID: v10_1_mpps
"""
from alembic import op
import sqlalchemy as sa

revision = "v10_1_mpps"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE worklist_items "
        "ADD COLUMN IF NOT EXISTS mpps_sop_instance_uid VARCHAR(128)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_worklist_items_mpps_sop_instance_uid "
        "ON worklist_items (mpps_sop_instance_uid)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_worklist_items_mpps_sop_instance_uid")
    op.execute("ALTER TABLE worklist_items DROP COLUMN IF EXISTS mpps_sop_instance_uid")
