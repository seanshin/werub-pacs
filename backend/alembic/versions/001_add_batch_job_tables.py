"""Add batch job tables for Phase 4 normalizer

Revision ID: 001
Revises: None
Create Date: 2026-05-14 08:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - create batch job tables."""
    # Create batch_jobs table
    op.create_table(
        "batch_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("total_files", sa.Integer(), nullable=False),
        sa.Column("processed_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("supplier", sa.String(64), nullable=False, server_default="auto_detect"),
        sa.Column("temp_file_path", sa.String(512), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_summary", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_batch_jobs_user_created", "user_id", "created_at"),
        sa.Index("ix_batch_jobs_status", "status"),
    )

    # Create batch_job_files table
    op.create_table(
        "batch_job_files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="validated"),
        sa.Column("normalization_changes", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sop_instance_uid", sa.String(128), nullable=True, index=True),
        sa.Column("study_instance_uid", sa.String(128), nullable=True, index=True),
        sa.Column("series_instance_uid", sa.String(128), nullable=True),
        sa.Column("patient_id", sa.String(64), nullable=True),
        sa.Column("modality", sa.String(32), nullable=True),
        sa.Column("detected_supplier", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["batch_id"], ["batch_jobs.id"], ondelete="CASCADE"),
        sa.Index("ix_batch_job_files_batch_id", "batch_id"),
        sa.Index("ix_batch_job_files_batch_status", "batch_id", "status"),
        sa.Index("ix_batch_job_files_study", "study_instance_uid"),
    )

    # Create normalization_reviews table
    op.create_table(
        "normalization_reviews",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("reviewer_id", sa.String(128), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("reviewed_changes", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["batch_id"], ["batch_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["batch_job_files.id"], ondelete="CASCADE"),
        sa.Index("ix_normalization_reviews_batch_id", "batch_id"),
        sa.Index("ix_normalization_reviews_file_id", "file_id"),
        sa.Index("ix_normalization_reviews_batch_decision", "batch_id", "decision"),
    )

    # Create normalization_config table
    op.create_table(
        "normalization_config",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("modality", sa.String(32), nullable=False, unique=True, index=True),
        sa.Column("algorithms", sa.JSON(), nullable=False, server_default=sa.text("'{\"pixel_spacing\": true, \"missing_tags\": true, \"photometric\": false, \"charset\": true}'::jsonb")),
        sa.Column("risk_tiers", sa.JSON(), nullable=False, server_default=sa.text("'{\"safe\": \"auto\", \"medium\": \"manual\", \"risky\": \"reject\"}'::jsonb")),
        sa.Column("updated_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_normalization_config_modality", "modality"),
    )

    # Create supplier_rules table
    op.create_table(
        "supplier_rules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("supplier_name", sa.String(64), nullable=False, index=True),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true", index=True),
        sa.Column("rule_config", sa.JSON(), nullable=False),
        sa.Column("managed_by", sa.String(128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_supplier_rules_supplier_active", "supplier_name", "is_active"),
    )


def downgrade() -> None:
    """Downgrade schema - drop batch job tables."""
    op.drop_table("supplier_rules")
    op.drop_table("normalization_config")
    op.drop_table("normalization_reviews")
    op.drop_table("batch_job_files")
    op.drop_table("batch_jobs")
