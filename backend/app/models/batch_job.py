"""Batch normalization job models for Phase 4."""
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UUID, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class BatchJob(Base, UUIDMixin, TimestampMixin):
    """Track batch DICOM normalization jobs."""

    __tablename__ = "batch_jobs"

    # Who submitted this batch
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    # Batch metadata
    status: Mapped[str] = mapped_column(
        String(32),
        default="queued",
        nullable=False,
        index=True,
        comment="queued|processing|completed|failed|paused"
    )
    total_files: Mapped[int] = mapped_column(Integer, nullable=False)
    processed_files: Mapped[int] = mapped_column(Integer, default=0)
    succeeded_files: Mapped[int] = mapped_column(Integer, default=0)
    failed_files: Mapped[int] = mapped_column(Integer, default=0)

    # Supplier detection
    supplier: Mapped[str] = mapped_column(
        String(64),
        default="auto_detect",
        nullable=False,
        comment="'auto_detect' or specific (siemens, ge, philips)"
    )

    # Temporary storage
    temp_file_path: Mapped[Optional[str]] = mapped_column(String(512))

    # Timing
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Error tracking
    error_summary: Mapped[Optional[dict]] = mapped_column(JSON)

    # Relationships
    files: Mapped[list["BatchJobFile"]] = relationship(
        "BatchJobFile",
        back_populates="batch",
        cascade="all, delete-orphan"
    )
    reviews: Mapped[list["NormalizationReview"]] = relationship(
        "NormalizationReview",
        back_populates="batch",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_batch_jobs_user_created", "user_id", "created_at"),
        # status index is auto-created by index=True on the column
    )


class BatchJobFile(Base, UUIDMixin, TimestampMixin):
    """Per-file status within a batch job."""

    __tablename__ = "batch_job_files"

    # Reference to batch
    batch_id: Mapped[str] = mapped_column(
        UUID,
        ForeignKey("batch_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # File metadata
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Processing status
    status: Mapped[str] = mapped_column(
        String(32),
        default="validated",
        nullable=False,
        comment="validated|normalizing|normalized|stored|failed"
    )

    # Results
    normalization_changes: Mapped[Optional[dict]] = mapped_column(JSON)
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # DICOM metadata (extracted from file)
    sop_instance_uid: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    study_instance_uid: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    series_instance_uid: Mapped[Optional[str]] = mapped_column(String(128))
    patient_id: Mapped[Optional[str]] = mapped_column(String(64))
    modality: Mapped[Optional[str]] = mapped_column(String(32))

    # Detected supplier for this file
    detected_supplier: Mapped[Optional[str]] = mapped_column(String(64))

    # Timing
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    batch: Mapped["BatchJob"] = relationship("BatchJob", back_populates="files")
    reviews: Mapped[list["NormalizationReview"]] = relationship(
        "NormalizationReview",
        back_populates="file",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_batch_job_files_batch_status", "batch_id", "status"),
        Index("ix_batch_job_files_study", "study_instance_uid"),
    )


class NormalizationReview(Base, UUIDMixin, TimestampMixin):
    """Track manual review decisions for medium-risk normalization changes."""

    __tablename__ = "normalization_reviews"

    # Reference to batch and file
    batch_id: Mapped[str] = mapped_column(
        UUID,
        ForeignKey("batch_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    file_id: Mapped[str] = mapped_column(
        UUID,
        ForeignKey("batch_job_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Reviewer
    reviewer_id: Mapped[str] = mapped_column(String(128), nullable=False)

    # Decision
    decision: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="approve|reject|defer"
    )

    # Comments
    comment: Mapped[Optional[str]] = mapped_column(Text)

    # What was reviewed (snapshot of normalization_changes)
    reviewed_changes: Mapped[Optional[dict]] = mapped_column(JSON)

    # Relationships
    batch: Mapped["BatchJob"] = relationship("BatchJob", back_populates="reviews")
    file: Mapped["BatchJobFile"] = relationship("BatchJobFile", back_populates="reviews")

    __table_args__ = (
        Index("ix_normalization_reviews_batch_decision", "batch_id", "decision"),
    )


class NormalizationConfig(Base, UUIDMixin, TimestampMixin):
    """Per-modality normalization configuration."""

    __tablename__ = "normalization_config"

    # Modality (CT, MR, US, XR, etc.)
    modality: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        unique=True,
    )

    # Which algorithms to enable for this modality
    algorithms: Mapped[dict] = mapped_column(
        JSON,
        default={
            "pixel_spacing": True,
            "missing_tags": True,
            "photometric": False,
            "charset": True,
        },
        nullable=False
    )

    # Risk tier handling
    risk_tiers: Mapped[dict] = mapped_column(
        JSON,
        default={
            "safe": "auto",      # auto-apply
            "medium": "manual",   # require approval
            "risky": "reject",    # never apply
        },
        nullable=False
    )

    # Updated by admin
    updated_by: Mapped[Optional[str]] = mapped_column(String(128))

    __table_args__ = (
        Index("ix_normalization_config_modality", "modality"),
    )

    def _to_cache(self) -> dict:
        """Serialize to cache-friendly dict."""
        return {
            "id": str(self.id),
            "modality": self.modality,
            "algorithms": self.algorithms,
            "risk_tiers": self.risk_tiers,
            "updated_by": self.updated_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def _from_cache(cls, data: dict) -> "NormalizationConfig":
        """Deserialize from cache dict (creates instance without DB persist)."""
        instance = cls()
        instance.id = data["id"]
        instance.modality = data["modality"]
        instance.algorithms = data["algorithms"]
        instance.risk_tiers = data["risk_tiers"]
        instance.updated_by = data.get("updated_by")
        return instance


class SupplierRule(Base, UUIDMixin, TimestampMixin):
    """Version-controlled supplier-specific normalization rules."""

    __tablename__ = "supplier_rules"

    # Which supplier
    supplier_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="siemens|ge|philips|etc"
    )

    # Rule version
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False)

    # Is this rule active?
    is_active: Mapped[bool] = mapped_column(default=True, index=True)

    # Rule implementation (JSONB for flexibility)
    rule_config: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Who manages this rule
    managed_by: Mapped[Optional[str]] = mapped_column(String(128))

    # Descriptive info
    description: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("ix_supplier_rules_supplier_active", "supplier_name", "is_active"),
    )

    def _to_cache(self) -> dict:
        """Serialize to cache-friendly dict."""
        return {
            "id": str(self.id),
            "supplier_name": self.supplier_name,
            "rule_version": self.rule_version,
            "is_active": self.is_active,
            "rule_config": self.rule_config,
            "managed_by": self.managed_by,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def _from_cache(cls, data: dict) -> "SupplierRule":
        """Deserialize from cache dict (creates instance without DB persist)."""
        instance = cls()
        instance.id = data["id"]
        instance.supplier_name = data["supplier_name"]
        instance.rule_version = data["rule_version"]
        instance.is_active = data["is_active"]
        instance.rule_config = data["rule_config"]
        instance.managed_by = data.get("managed_by")
        instance.description = data.get("description")
        return instance

    @classmethod
    def _from_cache_list(cls, data_list: list[dict]) -> list["SupplierRule"]:
        """Deserialize list from cache."""
        return [cls._from_cache(item) for item in data_list]
