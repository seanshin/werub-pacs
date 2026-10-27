"""API endpoints for batch DICOM normalization."""
import csv
import io
import logging
import os
import shutil
import tempfile
import zipfile
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Query, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select, func

from app.api.audit import _log_audit_entry
from app.core.config import settings
from app.core.database import get_async_db
from app.core.auth import get_current_user
from app.core.exceptions import ZipExtractionError, BatchQuotaError
from app.core.upload_stream import CHUNK_SIZE, bounded_stream_to_file, spool_upload_to_disk
from app.core.security import RequireRole
from app.models.user import User, Role
from app.models.batch_job import BatchJob, BatchJobFile, NormalizationReview
from app.services.batch_job_service import BatchJobService
from app.services.batch_normalizer_task import process_batch_normalization
from app.services.supplier_normalizer import CHANGE_SCHEMA_VERSION, is_applicable_change

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/batch", tags=["Batch Normalization"])

# Max files allowed per batch (enforced before task submission)
_MAX_BATCH_FILES = 1000
# DICOM magic bytes: preamble (128 bytes) + "DICM"
_DICOM_MAGIC = b"DICM"
_DICOM_MAGIC_OFFSET = 128


def _is_dicom_bytes(data: bytes) -> bool:
    """Return True if *data* begins with the standard DICOM preamble magic bytes."""
    return len(data) >= 132 and data[_DICOM_MAGIC_OFFSET: _DICOM_MAGIC_OFFSET + 4] == _DICOM_MAGIC


def _cleanup_spool_dir(temp_dir: str | None) -> None:
    """실패 경로에서 공유 스풀 임시 디렉터리를 회수(성공 경로는 워커가 소비하므로 보존)."""
    if not temp_dir:
        return
    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:  # pragma: no cover — 정리 실패가 원래 예외를 가리면 안 된다
        logger.warning("스풀 디렉터리 정리 실패: %s", temp_dir)


def _extract_zip(zip_path: str, dest_dir: str) -> list[tuple[str, str]]:
    """
    Extract DICOM files from a ZIP archive (on disk) into *dest_dir*.

    Only entries whose content starts with the DICOM magic bytes (or whose
    name ends with ``.dcm``) are retained.  Directories and non-DICOM files
    are silently skipped.

    각 멤버는 선두 청크만 판정용으로 읽고 나머지는 **디스크로 흘린다** — RAM 사용은
    청크 크기로 고정된다. 예전 `zf.read(entry.filename)`은 멤버 전체를 RAM에 올렸고
    상한이 없어, 고압축비 멤버 하나로 워커를 OOM에 빠뜨릴 수 있었다(v13.45).

    Args:
        zip_path: Path to the ZIP file on disk.
        dest_dir: Directory where extracted files will be written.

    Returns:
        List of ``(filename, filepath)`` tuples for accepted DICOM entries.

    Raises:
        ZipExtractionError: If the archive is corrupt or contains no DICOM files.
        HTTPException(413): 압축 해제 상한(멤버·누적·항목 수) 초과 시.
    """
    accepted: list[tuple[str, str]] = []
    total = 0
    entries = 0

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for entry in zf.infolist():
                # Skip directories and hidden/system files
                if entry.is_dir() or entry.filename.startswith("__MACOSX"):
                    continue

                name = os.path.basename(entry.filename)
                if not name:
                    continue

                entries += 1
                if entries > settings.max_zip_entries:
                    raise HTTPException(
                        413,
                        f"압축 파일의 항목 수가 너무 많습니다"
                        f"(최대 {settings.max_zip_entries}개)",
                    )
                # 헤더 신고값 선판정 — zipfile은 신고량까지만 해제하므로 유효한 상한이다
                # (자세한 근거는 core/upload_stream 상단 주석). 스트리밍이 이중 강제.
                if entry.file_size > settings.max_zip_member_bytes:
                    raise HTTPException(
                        413,
                        f"압축 해제 크기가 상한을 초과했습니다(멤버 {entry.filename})",
                    )
                if total + entry.file_size > settings.max_zip_extract_bytes:
                    raise HTTPException(
                        413, "압축 해제 누적 크기가 상한을 초과했습니다"
                    )

                dest_path = os.path.join(dest_dir, name)
                # Avoid overwriting files with duplicate basenames
                if os.path.exists(dest_path):
                    base, ext = os.path.splitext(name)
                    name = f"{base}_{len(accepted)}{ext}"
                    dest_path = os.path.join(dest_dir, name)

                try:
                    with zf.open(entry) as src:
                        # 판정에 필요한 선두만 읽는다 — 비-DICOM이면 나머지는 아예
                        # 읽지 않으므로 잡동사니 아카이브의 해제 비용을 물지 않는다.
                        head = src.read(CHUNK_SIZE)
                        if not (_is_dicom_bytes(head) or name.lower().endswith(".dcm")):
                            logger.debug(f"Skipping non-DICOM ZIP entry: {entry.filename}")
                            continue
                        written = bounded_stream_to_file(
                            src, dest_path,
                            min(settings.max_zip_member_bytes,
                                settings.max_zip_extract_bytes - total),
                            first_chunk=head,
                            label=f"멤버 {entry.filename}",
                        )
                except HTTPException:
                    raise  # 상한 초과는 요청 실패로 올린다(건너뛰기 대상 아님)
                except Exception as read_exc:
                    logger.warning(f"Skipping unreadable ZIP entry {entry.filename}: {read_exc}")
                    continue

                total += written
                accepted.append((name, dest_path))

    except zipfile.BadZipFile as exc:
        raise ZipExtractionError(f"Invalid ZIP archive: {exc}") from exc

    if not accepted:
        raise ZipExtractionError(
            "ZIP archive contained no valid DICOM files (checked for DICM magic bytes and .dcm extension)"
        )

    return accepted


class UploadBatchRequest:
    """Request body for batch normalization."""
    def __init__(
        self,
        supplier: str = "auto_detect",
        auto_normalize: bool = False,
    ):
        self.supplier = supplier
        self.auto_normalize = auto_normalize


@router.post("/normalize/upload")
async def upload_batch_for_normalization(
    files: list[UploadFile] = File(...),
    supplier: str = Query("auto_detect", description="siemens|ge|philips|auto_detect"),
    auto_normalize: bool = Query(False, description="Auto-apply SAFE changes"),
    current_user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST, allow_btg=False)),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """
    Upload DICOM files for batch normalization.

    Args:
        files: List of DICOM files to normalize
        supplier: Supplier hint or auto_detect
        auto_normalize: Whether to auto-apply SAFE changes
        current_user: Authenticated user
        db: Database session

    Returns:
        Batch job details with submission ID
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    if len(files) > _MAX_BATCH_FILES:
        raise BatchQuotaError(
            f"Maximum {_MAX_BATCH_FILES} files per batch; received {len(files)}"
        )

    temp_dir: str | None = None
    try:
        # ★공유 스풀에 저장 — backend(저장)와 celery-worker(읽기)가 별도 컨테이너라 /tmp면 워커가 못 읽음.
        os.makedirs(settings.batch_spool_dir, exist_ok=True)
        # Create temp directory early so ZIP extraction can target it
        temp_dir = tempfile.mkdtemp(prefix="batch_upload_", dir=settings.batch_spool_dir)

        # ------------------------------------------------------------------
        # Expand files: regular DICOM uploads + ZIP archives
        # ------------------------------------------------------------------
        # ``expanded`` collects (filename, on-disk path) pairs. Each upload is
        # streamed to disk in 1MB chunks (RAM-bounded) — the whole batch is
        # never held in memory (F7 OOM 벡터 제거, v13.0 upload_stream 적용).
        # ZIP files are extracted (one entry at a time); DICOM files pass through.
        expanded: list[tuple[str, str]] = []

        for idx, upload in enumerate(files):
            original_name = upload.filename or f"file_{idx}.dcm"
            spooled_path, _sz = await spool_upload_to_disk(
                upload, max_bytes=settings.max_upload_bytes, suffix=".upload", dir=temp_dir
            )

            is_zip = original_name.lower().endswith(".zip")
            if not is_zip:
                with open(spooled_path, "rb") as fh:
                    is_zip = fh.read(2) == b"PK"

            if is_zip:
                # ZIP archive — extract DICOM entries from the spooled file
                try:
                    zip_entries = _extract_zip(spooled_path, temp_dir)
                    expanded.extend(zip_entries)
                    logger.info(
                        f"Extracted {len(zip_entries)} DICOM file(s) from ZIP '{original_name}'"
                    )
                except ZipExtractionError as exc:
                    logger.warning(f"Skipping invalid ZIP '{original_name}': {exc.message}")
                    # Non-fatal: skip the bad archive and continue
                finally:
                    try:
                        os.remove(spooled_path)  # 원본 ZIP 제거(추출본만 유지)
                    except OSError:
                        pass
            else:
                expanded.append((original_name, spooled_path))

        if not expanded:
            raise HTTPException(status_code=400, detail="No valid DICOM files found in upload")

        if len(expanded) > _MAX_BATCH_FILES:
            raise BatchQuotaError(
                f"Expanded batch exceeds maximum of {_MAX_BATCH_FILES} files "
                f"({len(expanded)} files after ZIP extraction)"
            )

        # Create batch job record (file count known after expansion)
        batch = await BatchJobService.create_batch_job(
            db,
            user_id=str(current_user.id),
            total_files=len(expanded),
            supplier=supplier,
        )
        await db.commit()

        logger.info(
            f"Created batch {batch.id} with {len(expanded)} files, user={current_user.id}"
        )

        # Rename temp dir to include batch ID for traceability. The spooled
        # files move with the directory (atomic rename), so remap their paths.
        import shutil
        old_temp_dir = temp_dir
        named_temp_dir = tempfile.mkdtemp(prefix=f"batch_{batch.id}_", dir=settings.batch_spool_dir)
        shutil.rmtree(named_temp_dir)
        os.rename(temp_dir, named_temp_dir)
        temp_dir = named_temp_dir
        expanded = [
            (fn, os.path.join(temp_dir, os.path.relpath(p, old_temp_dir)))
            for fn, p in expanded
        ]

        # Move spooled files into their final names and register batch file records
        file_count = 0
        for idx, (filename, src_path) in enumerate(expanded):
            try:
                filepath = os.path.join(temp_dir, filename)
                # Avoid collisions from duplicate filenames (e.g., across ZIPs)
                if os.path.exists(filepath) and os.path.abspath(filepath) != os.path.abspath(src_path):
                    base, ext = os.path.splitext(filename)
                    filename = f"{base}_{idx}{ext}"
                    filepath = os.path.join(temp_dir, filename)

                if os.path.abspath(src_path) != os.path.abspath(filepath):
                    os.replace(src_path, filepath)

                # Add file record to batch
                await BatchJobService.add_batch_file(
                    db,
                    batch_id=str(batch.id),
                    filename=filename,
                    sequence_number=idx + 1,
                    modality="UNKNOWN",  # Will be detected during normalization
                )

                file_count += 1

            except Exception as e:
                logger.error(f"Failed to save file {filename}: {str(e)}")
                # Continue with other files

        await db.commit()

        if file_count == 0:
            raise HTTPException(status_code=400, detail="No files could be saved")

        # Update batch with temp path
        batch = await BatchJobService.get_batch_job(db, str(batch.id))
        batch.temp_file_path = temp_dir
        await db.commit()

        # Trigger Celery task
        task = process_batch_normalization.delay(str(batch.id), auto_normalize)

        logger.info(f"Queued batch normalization task {task.id} for batch {batch.id}")

        return {
            "batch_id": str(batch.id),
            "task_id": task.id,
            "status": "queued",
            "total_files": file_count,
            "supplier": supplier,
            "auto_normalize": auto_normalize,
            "message": "Batch submitted for normalization",
        }

    except (HTTPException, ZipExtractionError, BatchQuotaError):
        # 실패 경로의 스풀 디렉터리는 아무도 회수하지 않는다 — 성공 시엔 celery
        # 워커가 `batch.temp_file_path`로 읽고 정리하지만, 실패하면 배치 행조차
        # 없어서 공유 스풀(`batch_spool_dir`)에 부분 해제물이 영구히 남는다.
        # 상한을 도입한 김에 같은 축(디스크 고갈)의 누출을 함께 닫는다.
        _cleanup_spool_dir(temp_dir)
        raise
    except Exception as e:
        _cleanup_spool_dir(temp_dir)
        logger.exception(f"Error uploading batch: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.get("/normalize/{batch_id}")
async def get_batch_status(
    batch_id: str,
    current_user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST, allow_btg=False)),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """
    Get batch normalization status and results.

    Args:
        batch_id: Batch job ID
        current_user: Authenticated user
        db: Database session

    Returns:
        Batch job details with processing statistics
    """
    batch = await BatchJobService.get_batch_job(db, batch_id)

    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_id}")

    # Permission check: user can only view their own batches
    if str(batch.user_id) != str(current_user.id):
        # Allow admins to view all
        if not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Not authorized")

    # Get statistics
    stats = await BatchJobService.get_batch_statistics(db, batch_id)

    return {
        "batch_id": str(batch.id),
        "status": batch.status,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "started_at": batch.started_at.isoformat() if batch.started_at else None,
        "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
        "supplier": batch.supplier,
        "statistics": stats,
        "error_summary": batch.error_summary,
    }


@router.get("/normalize/{batch_id}/files")
async def list_batch_files(
    batch_id: str,
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST, allow_btg=False)),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """
    List files in a batch with their normalization results.

    Args:
        batch_id: Batch job ID
        status: Filter files by status (validated|normalizing|normalized|stored|failed)
        limit: Pagination limit
        offset: Pagination offset
        current_user: Authenticated user
        db: Database session

    Returns:
        Paginated list of batch files with normalization details
    """
    batch = await BatchJobService.get_batch_job(db, batch_id)

    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_id}")

    # Permission check
    if str(batch.user_id) != str(current_user.id):
        if not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Not authorized")

    # Query files
    stmt = select(BatchJobFile).where(
        BatchJobFile.batch_id == batch_id
    )

    if status:
        stmt = stmt.where(BatchJobFile.status == status)

    stmt = stmt.order_by(BatchJobFile.sequence_number).limit(limit).offset(offset)

    result = await db.execute(stmt)
    files = result.scalars().all()

    # Count total
    count_stmt = select(func.count(BatchJobFile.id)).where(
        BatchJobFile.batch_id == batch_id
    )
    if status:
        count_stmt = count_stmt.where(BatchJobFile.status == status)

    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    return {
        "batch_id": batch_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "files": [
            {
                "file_id": str(f.id),
                "filename": f.filename,
                "sequence": f.sequence_number,
                "status": f.status,
                "modality": f.modality,
                "detected_supplier": f.detected_supplier,
                "normalization_changes": f.normalization_changes,
                "error_message": f.error_message,
                "started_at": f.started_at.isoformat() if f.started_at else None,
                "completed_at": f.completed_at.isoformat() if f.completed_at else None,
            }
            for f in files
        ],
    }


@router.get("/normalize/{batch_id}/report")
async def get_batch_report(
    batch_id: str,
    format: str = Query("json", description="Report format: json|csv"),
    current_user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST, allow_btg=False)),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Get a detailed normalization report for a completed batch.

    Args:
        batch_id: Batch job ID
        format: Output format — 'json' (default) or 'csv'
        current_user: Authenticated user
        db: Database session

    Returns:
        JSON object or CSV file stream with full batch report
    """
    batch = await BatchJobService.get_batch_job(db, batch_id)

    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_id}")

    # Permission check: user can view own batch; admin can view any
    if str(batch.user_id) != str(current_user.id):
        if not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Not authorized")

    if format not in ("json", "csv"):
        raise HTTPException(status_code=400, detail="format must be 'json' or 'csv'")

    # Fetch all files for this batch
    files_stmt = (
        select(BatchJobFile)
        .where(BatchJobFile.batch_id == batch_id)
        .order_by(BatchJobFile.sequence_number)
    )
    files_result = await db.execute(files_stmt)
    files = files_result.scalars().all()

    # Fetch deferred reviews for this batch
    reviews_stmt = select(NormalizationReview).where(
        NormalizationReview.batch_id == batch_id
    )
    reviews_result = await db.execute(reviews_stmt)
    reviews = reviews_result.scalars().all()
    reviews_by_file = {}
    for r in reviews:
        reviews_by_file.setdefault(str(r.file_id), []).append(r)

    # Build per-file detail rows
    total_elapsed_ms = 0.0
    success_count = 0
    file_rows = []
    for f in files:
        changes_data = f.normalization_changes or {}
        change_list = changes_data.get("changes", [])
        elapsed_ms = changes_data.get("elapsed_ms", 0.0)
        applied = changes_data.get("applied", False)

        total_elapsed_ms += float(elapsed_ms)
        is_success = f.status in ("normalized", "stored") and not f.error_message
        if is_success:
            success_count += 1

        file_rows.append({
            "file_id": str(f.id),
            "filename": f.filename,
            "sequence": f.sequence_number,
            "status": f.status,
            "modality": f.modality or "",
            "detected_supplier": f.detected_supplier or "",
            "changes_count": len(change_list),
            "medium_risk_count": sum(
                1 for c in change_list if c.get("risk_level") == "medium"
            ),
            "applied": applied,
            "success": is_success,
            "elapsed_ms": elapsed_ms,
            "error_message": f.error_message or "",
            "pending_reviews": len(reviews_by_file.get(str(f.id), [])),
            "started_at": f.started_at.isoformat() if f.started_at else None,
            "completed_at": f.completed_at.isoformat() if f.completed_at else None,
        })

    total_files = len(files)
    success_rate = (success_count / total_files * 100) if total_files > 0 else 0.0
    avg_processing_ms = (total_elapsed_ms / total_files) if total_files > 0 else 0.0

    if format == "csv":
        output = io.StringIO()
        fieldnames = [
            "file_id", "filename", "sequence", "status", "modality",
            "detected_supplier", "changes_count", "medium_risk_count",
            "applied", "success", "elapsed_ms", "error_message",
            "pending_reviews", "started_at", "completed_at",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(file_rows)

        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="batch_{batch_id}_report.csv"'
            },
        )

    # JSON response
    return {
        "batch_id": batch_id,
        "summary": {
            "status": batch.status,
            "supplier": batch.supplier,
            "total_files": batch.total_files,
            "processed_files": batch.processed_files,
            "succeeded_files": batch.succeeded_files,
            "failed_files": batch.failed_files,
            "created_at": batch.created_at.isoformat() if batch.created_at else None,
            "started_at": batch.started_at.isoformat() if batch.started_at else None,
            "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
        },
        "statistics": {
            "success_rate": round(success_rate, 2),
            "avg_processing_ms": round(avg_processing_ms, 2),
            "total_processing_ms": round(total_elapsed_ms, 2),
            "total_pending_reviews": sum(r["pending_reviews"] for r in file_rows),
        },
        "files": file_rows,
    }


@router.get("/normalize")
async def list_batches(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """
    List batch normalization jobs for current user.

    Args:
        status: Filter by status (queued|processing|completed|failed|paused)
        limit: Pagination limit
        offset: Pagination offset
        current_user: Authenticated user
        db: Database session

    Returns:
        Paginated list of batches
    """
    batches, total = await BatchJobService.list_batch_jobs(
        db,
        user_id=str(current_user.id),
        status=status,
        limit=limit,
        offset=offset,
    )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "batches": [
            {
                "batch_id": str(b.id),
                "status": b.status,
                "created_at": b.created_at.isoformat() if b.created_at else None,
                "started_at": b.started_at.isoformat() if b.started_at else None,
                "completed_at": b.completed_at.isoformat() if b.completed_at else None,
                "total_files": b.total_files,
                "processed_files": b.processed_files,
                "succeeded_files": b.succeeded_files,
                "failed_files": b.failed_files,
                "supplier": b.supplier,
            }
            for b in batches
        ],
    }


# ─── 정규화 검토 큐(medium-risk 보류 변경 승인/반려) ──────────────────────────
# 정규화 시 safe=자동적용, medium-risk=미적용 'defer' 보류(NormalizationReview). 여기서 검토자가
# 승인/반려를 **기록**한다. (승인 시 ingested study에 DICOM 재적용은 형식 표준화+실배치 확보 후 v2 —
# reviewed_changes 형식이 과거 시드와 불일치해 현재 자동적용은 보류.)
ReviewRoles = RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST, allow_btg=False)  # QC 검토·승인=적용(파괴적) — researcher 제외·BTG 차단
_PENDING_DECISIONS = ("defer", "deferred")


class ReviewDecisionBody(BaseModel):
    decision: str            # approve | reject
    comment: str | None = None


def _expand_review_items(review: NormalizationReview, file: BatchJobFile | None) -> list[dict]:
    """NormalizationReview.reviewed_changes → 프론트 ReviewItem(change당 1행)으로 전개."""
    rc = review.reviewed_changes or {}
    version = rc.get("schema_version") if isinstance(rc, dict) else None
    changes = rc.get("changes") if isinstance(rc, dict) else None
    supplier = file.detected_supplier if file else None
    filename = file.filename if file else ""
    base = {"review_id": str(review.id), "batch_id": str(review.batch_id),
            "filename": filename, "supplier": supplier, "schema_version": version}
    out: list[dict] = []
    if isinstance(changes, list) and changes:
        for c in changes:
            out.append({**base,
                "dicom_tag": str(c.get("tag", "")),
                "original_value": str(c.get("original", "")),
                "proposed_value": str(c.get("corrected", c.get("proposed", ""))),
                "algorithm": str(c.get("algorithm", c.get("risk_level", ""))),
                "risk_rationale": str(c.get("rationale", "")),
                # v2 apply 적용가능 판별(캐논 태그+새값). 레거시 표시문자열/요약은 False.
                "applicable": is_applicable_change(c)})
    else:
        # 과거/요약 형식(태그별 목록 없음) — 요약 1행(자동적용 불가, 기록 검토만).
        out.append({**base, "dicom_tag": "", "original_value": "", "proposed_value": "",
                    "algorithm": str(rc.get("risk_level", "")) if isinstance(rc, dict) else "",
                    "risk_rationale": "요약 형식(태그별 변경 없음)", "applicable": False})
    return out


@router.get("/reviews", summary="정규화 검토 대기 큐(medium-risk 보류)")
async def list_pending_reviews(
    supplier: Optional[str] = Query(None),
    change_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    user: User = Depends(ReviewRoles),
    db: AsyncSession = Depends(get_async_db),
):
    base_q = select(NormalizationReview).where(NormalizationReview.decision.in_(_PENDING_DECISIONS))
    total = (await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar_one()
    reviews = (await db.execute(
        base_q.order_by(NormalizationReview.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    # 파일 메타 배치 조회(N+1 회피)
    file_ids = [r.file_id for r in reviews]
    files = {}
    if file_ids:
        frows = (await db.execute(select(BatchJobFile).where(BatchJobFile.id.in_(file_ids)))).scalars().all()
        files = {str(f.id): f for f in frows}
    items: list[dict] = []
    for r in reviews:
        for it in _expand_review_items(r, files.get(str(r.file_id))):
            if supplier and supplier != "all" and (it.get("supplier") or "") != supplier:
                continue
            items.append(it)
    total_pages = max(1, (total + page_size - 1) // page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size, "total_pages": total_pages}


@router.post("/reviews/{review_id}", summary="정규화 검토 결정(승인 시 DICOM 적용)")
async def decide_review(
    review_id: str,
    body: ReviewDecisionBody,
    request: Request,
    user: User = Depends(ReviewRoles),
    db: AsyncSession = Depends(get_async_db),
):
    if body.decision not in ("approve", "reject"):
        raise HTTPException(422, "decision은 approve 또는 reject")
    review = await db.get(NormalizationReview, review_id)
    if not review:
        raise HTTPException(404, "검토 항목을 찾을 수 없습니다.")
    if review.decision not in _PENDING_DECISIONS:
        raise HTTPException(409, f"이미 처리된 검토입니다: {review.decision}")

    applied_result = None
    if body.decision == "approve":
        # 승인 시 applicable(캐논) 변경만 SOP에 in-place 적용(fix.py 재사용, UID 보존+원본 백업/롤백).
        rc = review.reviewed_changes or {}
        changes = rc.get("changes") if isinstance(rc, dict) else []
        applicable = [c for c in (changes or []) if is_applicable_change(c)]
        if applicable:
            file = await db.get(BatchJobFile, review.file_id)
            sop = file.sop_instance_uid if file else None
            if not sop:
                raise HTTPException(409, "대상 SOPInstanceUID가 없어 적용할 수 없습니다.")
            # 드리프트 없는 신규 공유 모듈(서버 dicom_issues 단일파일/repo 패키지 무관).
            from app.services.normalization_apply import apply_canonical_changes
            applied_result = await apply_canonical_changes(
                db, request.app.state.http_client, sop, applicable, user.id
            )
            if applied_result.get("error"):
                raise HTTPException(409, f"적용 실패: {applied_result['error']}")

    review.decision = body.decision
    review.reviewer_id = str(user.id)
    # 적용 결과(rollback용 fix history id 포함)를 comment에 기록
    note = body.comment or ""
    if applied_result and applied_result.get("history_id"):
        note = f"{note} [applied fix_history={applied_result['history_id']}]".strip()
    review.comment = note
    await db.commit()
    # 감사강화 — 검토 결정(+적용 결과)을 감사로그에 기록. 적용 DICOM 변경/롤백 추적.
    await _log_audit_entry(
        db, "NORMALIZATION_REVIEW_DECIDED", "NormalizationReview", "SUCCESS",
        str(user.id), user.full_name or user.username,
        {"review_id": str(review_id), "decision": body.decision,
         "applied": bool(applied_result and applied_result.get("applied")),
         "fix_history_id": (applied_result or {}).get("history_id")},
    )
    return {"ok": True, "review_id": str(review_id), "decision": body.decision,
            "applied": bool(applied_result and applied_result.get("applied")),
            "apply_result": applied_result}
