"""Batch job service for managing DICOM normalization batch operations."""
from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func

from app.models.batch_job import BatchJob, BatchJobFile, NormalizationReview
from app.core.exceptions import NotFoundError


class BatchJobService:
    """Manage batch DICOM normalization jobs."""

    @staticmethod
    async def create_batch_job(
        session: AsyncSession,
        user_id: str,
        total_files: int,
        supplier: str = "auto_detect",
        temp_file_path: Optional[str] = None,
    ) -> BatchJob:
        """
        Create a new batch job.

        Args:
            session: Database session
            user_id: User who submitted the batch
            total_files: Total number of files in batch
            supplier: Supplier hint or "auto_detect"
            temp_file_path: Temporary storage path for batch files

        Returns:
            Created BatchJob
        """
        job = BatchJob(
            user_id=user_id,
            total_files=total_files,
            supplier=supplier,
            temp_file_path=temp_file_path,
            status="queued",
            processed_files=0,
            succeeded_files=0,
            failed_files=0,
        )
        session.add(job)
        await session.flush()
        return job

    @staticmethod
    async def get_batch_job(
        session: AsyncSession,
        batch_id: str,
    ) -> Optional[BatchJob]:
        """Get a batch job by ID."""
        stmt = select(BatchJob).where(BatchJob.id == str(batch_id))
        result = await session.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def list_batch_jobs(
        session: AsyncSession,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[BatchJob], int]:
        """
        List batch jobs with optional filtering.

        Returns:
            Tuple of (jobs, total_count)
        """
        stmt = select(BatchJob)

        if user_id:
            stmt = stmt.where(BatchJob.user_id == user_id)
        if status:
            stmt = stmt.where(BatchJob.status == status)

        # Get total count
        count_stmt = select(func.count()).select_from(BatchJob)
        if user_id:
            count_stmt = count_stmt.where(BatchJob.user_id == user_id)
        if status:
            count_stmt = count_stmt.where(BatchJob.status == status)

        count_result = await session.execute(count_stmt)
        total = count_result.scalar() or 0

        # Get paginated results
        stmt = stmt.order_by(BatchJob.created_at.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)
        jobs = result.scalars().all()

        return jobs, total

    @staticmethod
    async def add_batch_file(
        session: AsyncSession,
        batch_id: str,
        filename: str,
        sequence_number: int,
        sop_instance_uid: Optional[str] = None,
        study_instance_uid: Optional[str] = None,
        series_instance_uid: Optional[str] = None,
        patient_id: Optional[str] = None,
        modality: Optional[str] = None,
    ) -> BatchJobFile:
        """
        Add a file to a batch job.

        Args:
            session: Database session
            batch_id: Batch job ID
            filename: Original filename
            sequence_number: Order in batch
            sop_instance_uid: DICOM SOP instance UID
            study_instance_uid: DICOM study instance UID
            series_instance_uid: DICOM series instance UID
            patient_id: DICOM patient ID
            modality: DICOM modality

        Returns:
            Created BatchJobFile
        """
        file = BatchJobFile(
            batch_id=str(batch_id),
            filename=filename,
            sequence_number=sequence_number,
            status="validated",
            sop_instance_uid=sop_instance_uid,
            study_instance_uid=study_instance_uid,
            series_instance_uid=series_instance_uid,
            patient_id=patient_id,
            modality=modality,
        )
        session.add(file)
        await session.flush()
        return file

    @staticmethod
    async def update_batch_job_status(
        session: AsyncSession,
        batch_id: str,
        status: str,
    ) -> BatchJob:
        """
        Update batch job status.

        Valid statuses: queued, processing, completed, failed, paused

        Args:
            session: Database session
            batch_id: Batch job ID
            status: New status

        Returns:
            Updated BatchJob
        """
        valid_statuses = {"queued", "processing", "completed", "failed", "paused"}
        if status not in valid_statuses:
            raise ValueError(f"Invalid status: {status}. Must be one of {valid_statuses}")

        job = await BatchJobService.get_batch_job(session, batch_id)
        if not job:
            raise NotFoundError("Batch job", batch_id)

        job.status = status

        # Set timing
        if status == "processing" and not job.started_at:
            job.started_at = datetime.now(timezone.utc)
        elif status in ("completed", "failed"):
            job.completed_at = datetime.now(timezone.utc)

        await session.flush()
        return job

    @staticmethod
    async def update_file_status(
        session: AsyncSession,
        file_id: str,
        status: str,
        normalization_changes: Optional[dict] = None,
        error_message: Optional[str] = None,
        detected_supplier: Optional[str] = None,
    ) -> BatchJobFile:
        """
        Update batch file processing status.

        Valid statuses: validated, normalizing, normalized, stored, failed

        Args:
            session: Database session
            file_id: Batch job file ID
            status: New status
            normalization_changes: Changes applied (if any)
            error_message: Error details if failed
            detected_supplier: Auto-detected supplier

        Returns:
            Updated BatchJobFile
        """
        valid_statuses = {"validated", "normalizing", "normalized", "stored", "failed"}
        if status not in valid_statuses:
            raise ValueError(f"Invalid file status: {status}")

        stmt = select(BatchJobFile).where(BatchJobFile.id == str(file_id))
        result = await session.execute(stmt)
        file = result.scalars().first()

        if not file:
            raise NotFoundError("Batch file", file_id)

        file.status = status
        if normalization_changes:
            file.normalization_changes = normalization_changes
        if error_message:
            file.error_message = error_message
        if detected_supplier:
            file.detected_supplier = detected_supplier

        # Set timing
        if status == "normalizing" and not file.started_at:
            file.started_at = datetime.now(timezone.utc)
        elif status in ("stored", "failed"):
            file.completed_at = datetime.now(timezone.utc)

        await session.flush()
        return file

    @staticmethod
    async def increment_batch_counters(
        session: AsyncSession,
        batch_id: str,
        processed: int = 1,
        succeeded: int = 0,
        failed: int = 0,
    ) -> BatchJob:
        """
        Increment batch processing counters.

        Args:
            session: Database session
            batch_id: Batch job ID
            processed: Files processed (cumulative)
            succeeded: Files succeeded
            failed: Files failed

        Returns:
            Updated BatchJob
        """
        job = await BatchJobService.get_batch_job(session, batch_id)
        if not job:
            raise NotFoundError("Batch job", batch_id)

        job.processed_files += processed
        job.succeeded_files += succeeded
        job.failed_files += failed

        await session.flush()
        return job

    @staticmethod
    async def add_review(
        session: AsyncSession,
        batch_id: str,
        file_id: str,
        reviewer_id: str,
        decision: str,
        comment: Optional[str] = None,
        reviewed_changes: Optional[dict] = None,
    ) -> NormalizationReview:
        """
        Record a manual review decision for medium-risk changes.

        Args:
            session: Database session
            batch_id: Batch job ID
            file_id: File ID being reviewed
            reviewer_id: User making the review
            decision: Decision (approve, reject, defer)
            comment: Optional reviewer comment
            reviewed_changes: Snapshot of changes being reviewed

        Returns:
            Created NormalizationReview
        """
        valid_decisions = {"approve", "reject", "defer"}
        if decision not in valid_decisions:
            raise ValueError(f"Invalid decision: {decision}")

        review = NormalizationReview(
            batch_id=str(batch_id),
            file_id=str(file_id),
            reviewer_id=reviewer_id,
            decision=decision,
            comment=comment,
            reviewed_changes=reviewed_changes,
        )
        session.add(review)
        await session.flush()
        return review

    @staticmethod
    async def get_batch_statistics(
        session: AsyncSession,
        batch_id: str,
    ) -> dict:
        """
        Get processing statistics for a batch.

        Args:
            session: Database session
            batch_id: Batch job ID

        Returns:
            Statistics dict with counts and percentages
        """
        job = await BatchJobService.get_batch_job(session, batch_id)
        if not job:
            raise NotFoundError("Batch job", batch_id)

        # Count file statuses
        stmt = select(
            BatchJobFile.status,
            func.count(BatchJobFile.id).label("count")
        ).where(
            BatchJobFile.batch_id == str(batch_id)
        ).group_by(BatchJobFile.status)

        result = await session.execute(stmt)
        status_counts = {row[0]: row[1] for row in result.all()}

        # Count pending reviews
        reviews_stmt = select(func.count(NormalizationReview.id)).where(
            (NormalizationReview.batch_id == str(batch_id)) &
            (NormalizationReview.decision == "defer")
        )
        review_result = await session.execute(reviews_stmt)
        pending_reviews = review_result.scalar() or 0

        return {
            "batch_id": str(batch_id),
            "status": job.status,
            "total_files": job.total_files,
            "processed": job.processed_files,
            "succeeded": job.succeeded_files,
            "failed": job.failed_files,
            "status_distribution": status_counts,
            "pending_reviews": pending_reviews,
            "progress_percent": (job.processed_files / job.total_files * 100) if job.total_files > 0 else 0,
            "success_rate": (job.succeeded_files / job.processed_files * 100) if job.processed_files > 0 else 0,
        }
