"""Result storage service for inference results.

Persists inference results (DICOM references, metadata) to database.
Manages result lifecycle: creation, retrieval, cleanup of old results.

Features:
- InferenceResult record creation with metadata
- File path management for local storage
- Metadata indexing (DICOM type, confidence, measurements)
- Cleanup of results older than retention period
"""
import logging
from uuid import UUID
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from pathlib import Path

from sqlalchemy import and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import InferenceResult, InferenceJob
from app.core.exceptions import NotFoundError

logger = logging.getLogger(__name__)

# Result retention (30 days before cleanup)
RESULT_RETENTION_DAYS = 30


class ResultStorageService:
    """Service for managing inference result storage and retrieval."""

    def __init__(self, db: AsyncSession, storage_path: str = "/results"):
        self.db = db
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.logger = logger

    async def create_result(
        self,
        job_id: UUID,
        dicom_type: str,
        orthanc_id: str,
        file_path: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> InferenceResult:
        """Create a new inference result record.

        Args:
            job_id: UUID of parent InferenceJob
            dicom_type: Type of DICOM result (SEG, SR, SC, ANN)
            orthanc_id: Orthanc instance ID for the stored result
            file_path: Optional local file path for result
            metadata: Optional dict of additional metadata

        Returns:
            InferenceResult: Created result record

        Raises:
            NotFoundError: If job doesn't exist
        """
        try:
            # Step 1: Verify job exists
            job = await self.db.query(InferenceJob).filter(InferenceJob.id == job_id).first()
            if not job:
                raise NotFoundError("Inference job", str(job_id))

            # Step 2: Create result record
            result = InferenceResult(
                job_id=job_id,
                dicom_type=dicom_type,
                orthanc_id=orthanc_id,
                file_path=file_path or self._generate_file_path(job_id, dicom_type),
                metadata=metadata or {},
            )

            self.db.add(result)
            await self.db.commit()
            await self.db.refresh(result)

            self.logger.info(
                f"Result record created",
                extra={
                    "result_id": str(result.id),
                    "job_id": str(job_id),
                    "dicom_type": dicom_type,
                    "orthanc_id": orthanc_id,
                },
            )

            return result

        except Exception as e:
            self.logger.error(f"Error creating result record: {str(e)}", exc_info=True)
            raise

    async def get_result(self, result_id: UUID) -> InferenceResult:
        """Retrieve a result record by ID.

        Args:
            result_id: UUID of the result

        Returns:
            InferenceResult: Result record

        Raises:
            NotFoundError: If result doesn't exist
        """
        try:
            result = await self.db.query(InferenceResult).filter(InferenceResult.id == result_id).first()

            if not result:
                raise NotFoundError("Inference result", str(result_id))

            self.logger.debug(f"Retrieved result {result_id}")
            return result

        except Exception as e:
            self.logger.error(f"Error retrieving result: {str(e)}", exc_info=True)
            raise

    async def get_results_by_job(self, job_id: UUID) -> list:
        """Retrieve all results for a job.

        Args:
            job_id: UUID of the inference job

        Returns:
            list: List of InferenceResult records

        Raises:
            NotFoundError: If job doesn't exist
        """
        try:
            # Verify job exists
            job = await self.db.query(InferenceJob).filter(InferenceJob.id == job_id).first()
            if not job:
                raise NotFoundError("Inference job", str(job_id))

            # Get results
            results = await self.db.query(InferenceResult).filter(InferenceResult.job_id == job_id).all()

            self.logger.debug(f"Retrieved {len(results)} results for job {job_id}")
            return results

        except Exception as e:
            self.logger.error(f"Error retrieving results by job: {str(e)}", exc_info=True)
            raise

    async def update_result_metadata(
        self,
        result_id: UUID,
        metadata: Dict[str, Any],
    ) -> InferenceResult:
        """Update result metadata (merge with existing).

        Args:
            result_id: UUID of the result
            metadata: Dict of metadata to merge

        Returns:
            InferenceResult: Updated result record

        Raises:
            NotFoundError: If result doesn't exist
        """
        try:
            result = await self.db.query(InferenceResult).filter(InferenceResult.id == result_id).first()

            if not result:
                raise NotFoundError("Inference result", str(result_id))

            # Merge metadata
            if result.result_metadata is None:
                result.result_metadata = {}
            result.result_metadata.update(metadata)

            await self.db.commit()
            await self.db.refresh(result)

            self.logger.info(f"Updated metadata for result {result_id}")
            return result

        except Exception as e:
            self.logger.error(f"Error updating result metadata: {str(e)}", exc_info=True)
            raise

    async def cleanup_old_results(self, days: int = RESULT_RETENTION_DAYS) -> int:
        """Delete results older than specified days.

        Args:
            days: Number of days to retain (default 30)

        Returns:
            int: Number of results deleted

        Raises:
            Exception: If cleanup fails
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)

            # Step 1: Query old results
            old_results = await (
                self.db.query(InferenceResult)
                .filter(InferenceResult.created_at < cutoff_date)
                .all()
            )

            if not old_results:
                self.logger.info(f"No results to cleanup (older than {days} days)")
                return 0

            # Step 2: Delete files from filesystem (if stored locally)
            deleted_count = 0
            for result in old_results:
                try:
                    if result.file_path:
                        file_path = Path(result.file_path)
                        if file_path.exists():
                            file_path.unlink()
                            self.logger.debug(f"Deleted result file: {result.file_path}")
                except Exception as e:
                    self.logger.warning(f"Failed to delete result file {result.file_path}: {str(e)}")

            # Step 3: Delete database records
            await self.db.query(InferenceResult).filter(InferenceResult.created_at < cutoff_date).delete()
            await self.db.commit()

            deleted_count = len(old_results)
            self.logger.info(
                f"Cleaned up {deleted_count} old results",
                extra={"older_than_days": days, "cutoff_date": cutoff_date.isoformat()},
            )

            return deleted_count

        except Exception as e:
            self.logger.error(f"Error during result cleanup: {str(e)}", exc_info=True)
            raise

    def _generate_file_path(self, job_id: UUID, dicom_type: str) -> str:
        """Generate a unique file path for a result.

        Args:
            job_id: UUID of the job
            dicom_type: Type of DICOM (SEG, SR, etc.)

        Returns:
            str: File path relative to storage_path
        """
        now = datetime.utcnow()
        year_month = now.strftime("%Y/%m")
        filename = f"{job_id}_{dicom_type}_{now.timestamp()}.dcm"
        return str(self.storage_path / year_month / filename)

    async def save_result_file(self, result_id: UUID, dicom_bytes: bytes) -> str:
        """Save DICOM bytes to filesystem.

        Args:
            result_id: UUID of the result
            dicom_bytes: Serialized DICOM data

        Returns:
            str: Saved file path

        Raises:
            NotFoundError: If result doesn't exist
            Exception: If file save fails
        """
        try:
            result = await self.get_result(result_id)

            file_path = Path(result.file_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            with open(file_path, "wb") as f:
                f.write(dicom_bytes)

            self.logger.info(f"Saved result file: {file_path}")
            return str(file_path)

        except Exception as e:
            self.logger.error(f"Error saving result file: {str(e)}", exc_info=True)
            raise

    async def get_result_file(self, result_id: UUID) -> bytes:
        """Retrieve DICOM bytes from filesystem.

        Args:
            result_id: UUID of the result

        Returns:
            bytes: DICOM data

        Raises:
            NotFoundError: If result doesn't exist
            Exception: If file read fails
        """
        try:
            result = await self.get_result(result_id)

            file_path = Path(result.file_path)
            if not file_path.exists():
                raise FileNotFoundError(f"Result file not found: {file_path}")

            # Read file
            with open(file_path, "rb") as f:
                dicom_bytes = f.read()

            self.logger.debug(f"Retrieved result file: {file_path}")
            return dicom_bytes

        except Exception as e:
            self.logger.error(f"Error retrieving result file: {str(e)}", exc_info=True)
            raise
