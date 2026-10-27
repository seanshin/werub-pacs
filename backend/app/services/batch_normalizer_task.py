"""Celery task for batch DICOM normalization processing."""
import asyncio
import io
import logging
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.ai_worker import celery_app  # celery_app defined in ai_worker
from app.models.batch_job import BatchJob, BatchJobFile, NormalizationReview
from app.services.batch_job_service import BatchJobService
from app.services.normalizer_engine import NormalizerEngine
from app.services.orthanc_client import OrthancCachedClient as OrthancClient
from app.services.supplier_normalizer import CHANGE_SCHEMA_VERSION
# K3: celery 태스크는 FastAPI websocket을 import하지 않는다(워커 startup 크래시) →
# Redis pub/sub로 분리(sync publish, backend ws가 구독·전달).
from app.services.batch_progress import (
    publish_batch_progress as broadcast_batch_progress,
    publish_batch_complete as broadcast_batch_complete,
    publish_batch_error as broadcast_batch_error,
)

logger = logging.getLogger(__name__)


# Async session — 모듈레벨 create_async_engine은 워커 startup에서 sync 드라이버
# (psycopg2) URL과 충돌해 import 크래시(K3 2차 블로커) → 지연 생성 + URL을 asyncpg로
# 강제(celery 워커 env가 sync URL이어도 이 태스크는 async 사용). A11: 엔진은 태스크별
# 생성·폐기(전역 캐시 금지 — 닫힌 루프 재사용 방지).


def _async_db_url() -> str:
    u = settings.database_url
    if "+asyncpg" in u:
        return u
    return u.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace(
        "postgresql://", "postgresql+asyncpg://")


@asynccontextmanager
async def AsyncSessionLocal():
    """A11 fix: build a FRESH async engine bound to the current event loop and
    dispose it on exit. A module-global cached engine/pool gets bound to the
    first ``asyncio.run()`` loop; that loop is then closed, so the 2nd+ task in
    the same prefork worker would draw connections on a dead loop ("Future
    attached to a different loop" / "Event loop is closed"). Per-task lifecycle
    is cheap here (batch jobs are infrequent) and removes the loop-binding hazard.
    """
    engine_local = create_async_engine(_async_db_url(), echo=False, pool_pre_ping=True)
    factory = sessionmaker(engine_local, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine_local.dispose()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_batch_normalization(self, batch_id: str, auto_normalize: bool = False):
    """
    Process DICOM batch normalization job.

    This task:
    1. Updates batch status to 'processing'
    2. Iterates through batch files
    3. Normalizes each using NormalizerEngine
    4. Updates file status and changes
    5. Logs all changes
    6. Updates batch counters
    7. Marks batch as 'completed' or 'failed'

    Args:
        batch_id: Batch job UUID
        auto_normalize: Whether to auto-apply SAFE changes
    """
    import asyncio

    async def run():
        async with AsyncSessionLocal() as session:
            try:
                # 1. Get batch job
                batch = await BatchJobService.get_batch_job(session, batch_id)
                if not batch:
                    logger.error(f"Batch not found: {batch_id}")
                    return

                logger.info(f"Starting normalization for batch {batch_id}, files: {batch.total_files}")

                # 2. Update status to processing
                await BatchJobService.update_batch_job_status(session, batch_id, "processing")
                await session.commit()

                # Broadcast start
                broadcast_batch_progress(
                    batch_id=batch_id,
                    status="processing",
                    processed=0,
                    total=batch.total_files,
                    succeeded=0,
                    failed=0,
                    current_file="Starting batch processing...",
                )

                # 3. Initialize engine and Orthanc client
                engine = NormalizerEngine(session)
                _orthanc_http = httpx.AsyncClient(
                    base_url=settings.orthanc_url,
                    auth=(settings.orthanc_username, settings.orthanc_password),
                    timeout=30.0,
                )
                orthanc = OrthancClient(_orthanc_http)

                # 4. Process files
                from sqlalchemy import select
                stmt = select(BatchJobFile).where(
                    BatchJobFile.batch_id == str(batch_id)
                ).order_by(BatchJobFile.sequence_number)

                result = await session.execute(stmt)
                files = result.scalars().all()

                succeeded = 0
                failed = 0
                error_summary = {}
                processed_count = 0

                for file in files:
                    try:
                        logger.info(f"Processing file {file.sequence_number}/{batch.total_files}: {file.filename}")

                        # Get file from temp storage or Orthanc
                        file_bytes = await _get_file_bytes(
                            batch.temp_file_path,
                            file.filename,
                            orthanc,
                        )

                        if not file_bytes:
                            raise ValueError(f"Could not load file: {file.filename}")

                        # Update file status to normalizing
                        await BatchJobService.update_file_status(
                            session,
                            str(file.id),
                            "normalizing",
                        )
                        await session.commit()

                        # Run normalization
                        result = await engine.normalize_dicom(
                            file_id=str(file.id),
                            filename=file.filename,
                            dicom_bytes=file_bytes,
                            modality=file.modality or "UNKNOWN",
                            auto_normalize=auto_normalize,
                        )

                        if result.error:
                            logger.error(f"Normalization error for {file.filename}: {result.error}")
                            await BatchJobService.update_file_status(
                                session,
                                str(file.id),
                                "failed",
                                error_message=result.error,
                                detected_supplier=result.detected_supplier,
                            )
                            failed += 1
                            error_summary[file.filename] = result.error
                            processed_count += 1
                            await session.commit()
                            continue

                        # Update file status to normalized with change details
                        await BatchJobService.update_file_status(
                            session,
                            str(file.id),
                            "normalized",
                            normalization_changes={
                                "applied": result.applied,
                                "changes": result.changes,
                                "elapsed_ms": result.elapsed_ms,
                            },
                            detected_supplier=result.detected_supplier,
                        )
                        await session.commit()

                        logger.info(
                            f"Normalized {file.filename}: "
                            f"supplier={result.detected_supplier}, "
                            f"changes={len(result.changes)}, "
                            f"applied={result.applied}"
                        )

                        # Create NormalizationReview records for medium-risk changes
                        medium_changes = [
                            c for c in result.changes
                            if c.get("risk_level") == "medium"
                        ]
                        if medium_changes:
                            review = NormalizationReview(
                                batch_id=str(batch.id),
                                file_id=str(file.id),
                                reviewer_id=str(batch.user_id),
                                decision="defer",
                                comment="Auto-created: medium-risk changes require manual approval",
                                # 캐논 엔벨로프(버전 포함) — 레거시 요약 dict와 구분, v2 apply 적용가능 판별용.
                                reviewed_changes={"schema_version": CHANGE_SCHEMA_VERSION, "changes": medium_changes},
                            )
                            session.add(review)
                            logger.info(
                                f"Created review record for {file.filename}: "
                                f"{len(medium_changes)} medium-risk change(s) deferred"
                            )
                            await session.commit()

                        # Store normalized file back to Orthanc
                        # Re-read file_bytes (already normalized in-memory by engine if applied)
                        storage_status = "stored"
                        storage_error = None
                        try:
                            await _upload_to_orthanc(orthanc, file_bytes, file.filename)
                            logger.info(f"Stored {file.filename} to Orthanc")
                        except Exception as store_exc:
                            storage_error = str(store_exc)
                            storage_status = "normalized"  # remain at normalized, not stored
                            logger.warning(
                                f"Orthanc storage failed for {file.filename}: {store_exc} "
                                f"(file remains normalized but not stored)"
                            )

                        await BatchJobService.update_file_status(
                            session,
                            str(file.id),
                            storage_status,
                            error_message=storage_error,
                        )

                        if storage_error:
                            # Storage failure is non-fatal; file still normalized
                            failed += 1
                            error_summary[file.filename] = f"Storage failed: {storage_error}"
                        else:
                            succeeded += 1

                        processed_count += 1
                        await session.commit()

                        # Broadcast progress update
                        broadcast_batch_progress(
                            batch_id=batch_id,
                            status="processing",
                            processed=processed_count,
                            total=batch.total_files,
                            succeeded=succeeded,
                            failed=failed,
                            current_file=file.filename,
                            elapsed_ms=result.elapsed_ms,
                        )

                    except Exception as e:
                        logger.exception(f"Failed to process file {file.filename}: {str(e)}")
                        await BatchJobService.update_file_status(
                            session,
                            str(file.id),
                            "failed",
                            error_message=str(e),
                        )
                        failed += 1
                        error_summary[file.filename] = str(e)
                        processed_count += 1
                        await session.commit()

                # 5. Update batch completion
                batch = await BatchJobService.get_batch_job(session, batch_id)
                batch.processed_files = len(files)
                batch.succeeded_files = succeeded
                batch.failed_files = failed
                batch.error_summary = error_summary if error_summary else None

                final_status = "completed" if failed == 0 else "failed"

                # Mark as completed
                await BatchJobService.update_batch_job_status(
                    session,
                    batch_id,
                    final_status,
                )
                await session.commit()

                logger.info(
                    f"Batch {batch_id} completed: "
                    f"total={len(files)}, succeeded={succeeded}, failed={failed}"
                )

                # Clean up temporary files
                if batch.temp_file_path:
                    import shutil
                    try:
                        shutil.rmtree(batch.temp_file_path, ignore_errors=True)
                        logger.info(f"Cleaned up temp directory: {batch.temp_file_path}")
                    except Exception as cleanup_exc:
                        logger.warning(
                            f"Failed to clean up temp directory "
                            f"{batch.temp_file_path}: {cleanup_exc}"
                        )

                # Broadcast completion
                broadcast_batch_complete(
                    batch_id=batch_id,
                    status=final_status,
                    total=len(files),
                    succeeded=succeeded,
                    failed=failed,
                    error_summary=error_summary if error_summary else None,
                )

            except Exception as e:
                logger.exception(f"Batch processing failed for {batch_id}: {str(e)}")
                error_msg = str(e)
                try:
                    await BatchJobService.update_batch_job_status(session, batch_id, "failed")
                    await session.commit()

                    # Broadcast error
                    broadcast_batch_error(batch_id=batch_id, error=error_msg)
                except Exception as e2:
                    logger.exception(f"Failed to mark batch as failed: {str(e2)}")

    # Run async task
    asyncio.run(run())

    return {
        "batch_id": batch_id,
        "status": "completed",
    }


async def _upload_to_orthanc(
    orthanc: "OrthancClient",
    file_bytes: bytes,
    filename: str,
    max_retries: int = 3,
) -> dict:
    """
    Upload a normalized DICOM file to Orthanc via REST API.

    Retries on transient network errors with exponential backoff.

    Args:
        orthanc: OrthancClient instance (unused directly; uses httpx with config)
        file_bytes: Raw DICOM bytes to upload
        filename: Filename for logging
        max_retries: Number of retry attempts on transient failure

    Returns:
        Orthanc JSON response with uploaded instance ID

    Raises:
        RuntimeError: If upload fails after all retries
    """
    import asyncio as _asyncio

    url = f"{settings.orthanc_url}/instances"
    auth = (settings.orthanc_username, settings.orthanc_password)
    headers = {"Content-Type": "application/dicom"}

    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(auth=auth, timeout=30.0) as client:
                response = await client.post(url, content=file_bytes, headers=headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            last_error = e
            logger.warning(
                f"Orthanc upload HTTP error for {filename} "
                f"(attempt {attempt}/{max_retries}): {e.response.status_code}"
            )
            # 4xx errors are not retryable
            if 400 <= e.response.status_code < 500:
                break
        except (httpx.RequestError, httpx.TimeoutException) as e:
            last_error = e
            logger.warning(
                f"Orthanc upload transient error for {filename} "
                f"(attempt {attempt}/{max_retries}): {e}"
            )

        if attempt < max_retries:
            await _asyncio.sleep(2 ** attempt)

    raise RuntimeError(
        f"Orthanc upload failed for {filename} after {max_retries} attempt(s): {last_error}"
    )


async def _get_file_bytes(
    temp_path: Optional[str],
    filename: str,
    orthanc: "OrthancClient",
) -> Optional[bytes]:
    """
    Get file bytes from temp storage or Orthanc.

    Args:
        temp_path: Temporary directory path
        filename: File name
        orthanc: Orthanc client

    Returns:
        File bytes or None if not found
    """
    if temp_path:
        import os
        file_path = os.path.join(temp_path, filename)
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                return f.read()

    # Try Orthanc fallback
    # This would require filename-to-orthanc-ID mapping
    # For now, return None
    return None
