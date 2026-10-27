"""DICOM Upload Center API — v9.2

Admin upload, upload queue (approval), patient portal tokens.
"""
import hashlib
import io
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import AuditLogger
from app.core.config import settings
from app.core.database import get_db
from app.core.security import RequireRole, get_current_user
from app.core.upload_stream import bounded_zip_read, spool_upload_to_disk
from app.models.dicom_issue import PatientUploadToken, UploadQueue
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["upload"])

STAGING_DIR = os.environ.get("UPLOAD_STAGING_DIR", "/tmp/openpacs-upload-staging")


# ─── Admin Upload ────────────────────────────────────────────────────────────

@router.post("/upload/files")
async def upload_files(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    # 아카이브 직접 쓰기 — 임상 수집 역할만(RESEARCHER/PHYSICIAN 주입 차단, S9)
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST, allow_btg=False))],
    files: list[UploadFile] = File(...),
    auto_validate: bool = Query(True),
    auto_normalize: bool = Query(False),
    source: str = Query("admin"),
):
    """Upload DICOM files directly to Orthanc with optional validation."""
    client = request.app.state.http_client

    results = []
    uploaded = 0
    failed = 0

    for file in files:
        data = await file.read()
        if len(data) < 132:
            results.append({"filename": file.filename, "status": "skipped", "reason": "Too small"})
            continue

        # DICOM magic check
        if data[128:132] != b"DICM":
            results.append({"filename": file.filename, "status": "skipped", "reason": "Not DICOM"})
            continue

        # Validate if requested
        validation = None
        if auto_validate:
            from app.services.dicom_validator import DicomValidator
            validator = DicomValidator()
            report = validator.validate(data)
            validation = {
                "accepted": report.accepted,
                "max_severity": report.max_severity.value if report.max_severity else None,
                "counts": {"critical": report.critical_count, "error": report.error_count,
                           "warning": report.warning_count, "info": report.info_count},
            }

            # Auto-normalize
            if auto_normalize and report.findings:
                try:
                    import pydicom
                    from app.services.dicom_normalizer import DicomNormalizer
                    ds = pydicom.dcmread(io.BytesIO(data), force=True)
                    normalizer = DicomNormalizer()
                    norm = await normalizer.normalize(ds, report, data)
                    if norm.modified:
                        output = io.BytesIO()
                        ds.save_as(output, write_like_original=True)
                        data = output.getvalue()
                        validation["normalized"] = True
                        validation["changes"] = len(norm.changes)
                except Exception as e:
                    logger.warning(f"Normalize failed for {file.filename}: {e}")

        # Upload to Orthanc
        try:
            resp = await client.post("/instances", content=data,
                                     headers={"Content-Type": "application/dicom"})
            if resp.status_code in (200, 409):
                uploaded += 1
                resp_data = resp.json() if resp.status_code == 200 else {}
                results.append({
                    "filename": file.filename,
                    "status": "uploaded",
                    "orthanc_id": resp_data.get("ID"),
                    "validation": validation,
                })
            else:
                failed += 1
                results.append({"filename": file.filename, "status": "failed", "reason": f"Orthanc {resp.status_code}"})
        except Exception as e:
            failed += 1
            results.append({"filename": file.filename, "status": "failed", "reason": str(e)})

    return {"ok": True, "uploaded": uploaded, "failed": failed, "total": len(files), "results": results}


@router.post("/upload/zip")
async def upload_zip(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    # 아카이브 직접 쓰기 — 임상 수집 역할만(S9)
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST, allow_btg=False))],
    file: UploadFile = File(...),
    auto_validate: bool = Query(True),
    source: str = Query("admin"),
):
    """Upload ZIP file containing DICOM files."""
    import zipfile

    # 대형 ZIP을 RAM에 통째로 올리지 않고 청크로 디스크에 스풀(io.BytesIO 풀복사 제거).
    zip_path, _size = await spool_upload_to_disk(
        file, max_bytes=settings.max_streaming_upload_bytes, suffix=".zip"
    )

    client = request.app.state.http_client
    uploaded = 0
    skipped = 0
    failed = 0
    total_entries = 0
    extracted_total = 0

    try:
        if not zipfile.is_zipfile(zip_path):
            return {"error": "Not a valid ZIP file"}

        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                if name.endswith('/') or name.startswith('__MACOSX'):
                    continue
                total_entries += 1
                if total_entries > settings.max_zip_entries:
                    raise HTTPException(
                        413,
                        f"압축 파일의 항목 수가 너무 많습니다"
                        f"(최대 {settings.max_zip_entries}개)",
                    )
                try:
                    # 상한 있는 읽기 — 이 경로는 멤버를 Orthanc POST 본문으로 쓰려고
                    # RAM에 올려야 하므로(디스크로 흘릴 수 없다) 더 좁은 상한을 쓴다.
                    fdata = bounded_zip_read(
                        zf, name, max_bytes=settings.max_zip_member_ram_bytes
                    )
                    extracted_total += len(fdata)
                    if extracted_total > settings.max_zip_extract_bytes:
                        raise HTTPException(
                            413,
                            f"압축 해제 누적 크기가 상한을 초과했습니다(최대 "
                            f"{settings.max_zip_extract_bytes // (1024 * 1024)}MB)",
                        )
                    if len(fdata) < 132 or fdata[128:132] != b"DICM":
                        skipped += 1
                        continue

                    resp = await client.post("/instances", content=fdata,
                                             headers={"Content-Type": "application/dicom"})
                    if resp.status_code in (200, 409):
                        uploaded += 1
                    else:
                        failed += 1
                except HTTPException:
                    # ★상한 초과는 반드시 올려보낸다 — 아래 `except Exception`이
                    #   삼키면 폭탄이 "failed 1건"으로 집계되고 루프가 계속돼
                    #   상한이 무력화된다.
                    raise
                except Exception:
                    failed += 1
    finally:
        try:
            os.unlink(zip_path)
        except OSError:
            pass

    return {"ok": True, "uploaded": uploaded, "skipped": skipped, "failed": failed,
            "total_entries": total_entries}


# ─── Upload Queue (Approval) ────────────────────────────────────────────────

@router.get("/upload-queue")
async def list_upload_queue(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    status: str = Query("pending"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List upload queue items."""
    q = select(UploadQueue)
    if status:
        q = q.where(UploadQueue.status == status)
    q = q.order_by(UploadQueue.created_at.desc())

    total_q = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_q.scalar() or 0

    result = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    items = result.scalars().all()

    return {
        "total": total, "page": page,
        "items": [
            {
                "id": str(i.id), "source": i.source, "source_detail": i.source_detail,
                "patient_id": i.patient_id, "patient_name": i.patient_name,
                "file_count": i.file_count, "total_size_bytes": i.total_size_bytes,
                "study_uids": i.study_uids, "modalities": i.modalities,
                "validation_status": i.validation_status,
                "validation_summary": i.validation_summary,
                "status": i.status, "reject_reason": i.reject_reason,
                "created_at": i.created_at.isoformat() if i.created_at else None,
                "expires_at": i.expires_at.isoformat() if i.expires_at else None,
                "approved_at": i.approved_at.isoformat() if i.approved_at else None,
            }
            for i in items
        ],
    }


@router.post("/upload-queue/{queue_id}/approve")
@AuditLogger.log("UPLOAD_APPROVED", "UploadQueue")
async def approve_upload(
    queue_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Approve upload — move files from staging to Orthanc."""
    # Atomic claim: exactly one approver wins the pending→approving transition,
    # so concurrent approves can't double-ingest. On any failure below we reset
    # to 'pending' (try/reset) so the item never gets stuck in 'approving'.
    claim = await db.execute(
        update(UploadQueue)
        .where(UploadQueue.id == queue_id, UploadQueue.status == "pending")
        .values(status="approving")
        .returning(UploadQueue.id)
    )
    await db.commit()
    if claim.first() is None:
        existing = (await db.execute(
            select(UploadQueue).where(UploadQueue.id == queue_id)
        )).scalar_one_or_none()
        if not existing:
            return {"error": "Queue item not found"}
        return {"error": f"Cannot approve item with status '{existing.status}'"}
    item = (await db.execute(
        select(UploadQueue).where(UploadQueue.id == queue_id)
    )).scalar_one_or_none()

    client = request.app.state.http_client
    uploaded = 0
    try:
        # Upload staged files to Orthanc
        if item.storage_path and os.path.isdir(item.storage_path):
            for fname in os.listdir(item.storage_path):
                fpath = os.path.join(item.storage_path, fname)
                if not os.path.isfile(fpath):
                    continue
                try:
                    with open(fpath, "rb") as f:
                        data = f.read()
                    if len(data) >= 132 and data[128:132] == b"DICM":
                        resp = await client.post("/instances", content=data,
                                                 headers={"Content-Type": "application/dicom"})
                        if resp.status_code in (200, 409):
                            uploaded += 1
                except Exception as e:
                    logger.warning(f"Upload staged file failed: {e}")

            # Cleanup staging
            import shutil
            try:
                shutil.rmtree(item.storage_path, ignore_errors=True)
            except Exception:
                pass

        item.status = "approved"
        item.approved_by = user.id
        item.approved_at = datetime.now(timezone.utc)
        await db.commit()
    except Exception as e:
        # Reset the claim so the item is retryable (not stuck in 'approving').
        await db.rollback()
        await db.execute(
            update(UploadQueue)
            .where(UploadQueue.id == queue_id, UploadQueue.status == "approving")
            .values(status="pending")
        )
        await db.commit()
        logger.error(f"approve_upload failed, reset to pending: {e}")
        return {"error": "Approve failed; item reset to pending"}

    return {"ok": True, "uploaded": uploaded, "queue_id": str(item.id)}


@router.post("/upload-queue/{queue_id}/reject")
@AuditLogger.log("UPLOAD_REJECTED", "UploadQueue")
async def reject_upload(
    queue_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    reason: str = Query("", description="Rejection reason"),
):
    """Reject upload — delete staged files."""
    result = await db.execute(select(UploadQueue).where(UploadQueue.id == queue_id))
    item = result.scalar_one_or_none()
    if not item:
        return {"error": "Queue item not found"}

    if item.storage_path and os.path.isdir(item.storage_path):
        import shutil
        shutil.rmtree(item.storage_path, ignore_errors=True)

    item.status = "rejected"
    item.reject_reason = reason
    item.approved_by = user.id
    item.approved_at = datetime.now(timezone.utc)
    await db.commit()

    return {"ok": True, "queue_id": str(item.id)}


@router.get("/upload-queue/stats")
async def upload_queue_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Upload queue statistics."""
    result = await db.execute(
        select(UploadQueue.status, func.count()).group_by(UploadQueue.status)
    )
    by_status = dict(result.all())
    source_q = await db.execute(
        select(UploadQueue.source, func.count())
        .where(UploadQueue.status == "pending")
        .group_by(UploadQueue.source)
    )
    return {"by_status": by_status, "pending_by_source": dict(source_q.all())}


# ─── Patient Upload Tokens ──────────────────────────────────────────────────

class TokenCreate(BaseModel):
    patient_id: str
    patient_name: str | None = None
    patient_birth_date: str | None = None
    expires_hours: int = 24


@router.post("/patient-upload/token")
@AuditLogger.log("PATIENT_TOKEN_CREATED", "PatientUploadToken")
async def create_patient_token(
    body: TokenCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Issue upload token for patient portal."""
    token_str = secrets.token_urlsafe(48)
    tok = PatientUploadToken(
        token=token_str,
        patient_id=body.patient_id,
        patient_name=body.patient_name,
        patient_birth_date=body.patient_birth_date,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=body.expires_hours),
        created_by=user.id,
    )
    db.add(tok)
    await db.commit()

    return {
        "ok": True,
        "token": token_str,
        "url": f"/patient-upload?token={token_str}",
        "expires_at": tok.expires_at.isoformat(),
    }


@router.get("/patient-upload/tokens")
async def list_patient_tokens(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """List recent patient upload tokens."""
    result = await db.execute(
        select(PatientUploadToken).order_by(PatientUploadToken.created_at.desc()).limit(50)
    )
    tokens = result.scalars().all()
    return {
        "tokens": [
            {
                "id": str(t.id), "token": t.token[:8] + "...",
                "patient_id": t.patient_id, "patient_name": t.patient_name,
                "used": t.used, "consent_agreed": t.consent_agreed,
                "expires_at": t.expires_at.isoformat(),
                "created_at": t.created_at.isoformat(),
            }
            for t in tokens
        ]
    }


# ─── Patient Portal (Public, token-based) ───────────────────────────────────

@router.get("/patient-upload/verify")
async def verify_patient_token(
    token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Verify patient upload token — public endpoint."""
    result = await db.execute(
        select(PatientUploadToken).where(PatientUploadToken.token == token)
    )
    tok = result.scalar_one_or_none()
    if not tok:
        return {"valid": False, "error": "Invalid token"}
    if tok.expires_at < datetime.now(timezone.utc):
        return {"valid": False, "error": "Token expired"}
    if tok.used:
        return {"valid": False, "error": "Token already used"}

    return {
        "valid": True,
        "patient_id": tok.patient_id,
        "patient_name": tok.patient_name,
        "consent_agreed": tok.consent_agreed,
    }


@router.post("/patient-upload/consent")
async def submit_consent(
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Submit privacy consent — public endpoint."""
    result = await db.execute(
        select(PatientUploadToken).where(PatientUploadToken.token == token)
    )
    tok = result.scalar_one_or_none()
    if not tok or tok.expires_at < datetime.now(timezone.utc):
        return {"error": "Invalid or expired token"}

    tok.consent_agreed = True
    tok.consent_agreed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}


@router.post("/patient-upload/files")
async def patient_upload_files(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    token: str = Query(...),
    files: list[UploadFile] = File(...),
):
    """Patient file upload — public endpoint, token-authenticated.
    Files go to staging (upload_queue), not directly to Orthanc.
    """
    result = await db.execute(
        select(PatientUploadToken).where(PatientUploadToken.token == token)
    )
    tok = result.scalar_one_or_none()
    if not tok or tok.expires_at < datetime.now(timezone.utc):
        return {"error": "Invalid or expired token"}
    if not tok.consent_agreed:
        return {"error": "Privacy consent required before upload"}
    if tok.used:
        return {"error": "Token already used"}
    # 원자적 단일사용 클레임 — 게이트에서 used=true 선점(공개 EP, 동시 2요청 중복 업로드·
    # 디스크 채우기 방지). 실패 시 토큰 소진은 단일사용 보안상 수용(재발급).
    claimed = (await db.execute(
        update(PatientUploadToken)
        .where(PatientUploadToken.token == token, PatientUploadToken.used == False)
        .values(used=True).returning(PatientUploadToken.id))).first()
    if not claimed:
        return {"error": "Token already used"}
    await db.commit()

    # Create staging directory
    session_id = str(uuid.uuid4())[:8]
    staging = os.path.join(STAGING_DIR, "patient-portal", f"{tok.patient_id}_{session_id}")
    os.makedirs(staging, exist_ok=True)

    saved = 0
    total_size = 0
    study_uids = set()
    modalities = set()

    import pydicom
    for file in files:
        # 각 파일을 청크로 스테이징에 스풀(RAM 바운드) — 전체를 메모리에 올리지 않는다.
        # 개별 파일이 너무 크거나 비었으면 배치 전체를 깨지 않고 해당 파일만 건너뛴다.
        try:
            tmp_path, fsize = await spool_upload_to_disk(
                file, max_bytes=settings.max_upload_bytes, dir=staging
            )
        except HTTPException:
            continue
        total_size += fsize

        # 디스크에서 매직 바이트만 읽어 DICOM 판별(전체 RAM 적재 없음).
        try:
            with open(tmp_path, "rb") as f:
                head = f.read(132)
        except OSError:
            head = b""

        if len(head) >= 132 and head[128:132] == b"DICM":
            dest = os.path.join(staging, f"{saved:04d}.dcm")
            os.replace(tmp_path, dest)
            saved += 1

            # Extract basic info — 디스크에서 직접, 픽셀 데이터는 적재하지 않음.
            try:
                ds = pydicom.dcmread(dest, force=True, stop_before_pixels=True)
                uid = str(getattr(ds, "StudyInstanceUID", ""))
                mod = str(getattr(ds, "Modality", ""))
                if uid:
                    study_uids.add(uid)
                if mod:
                    modalities.add(mod)
            except Exception:
                pass
        elif file.filename and file.filename.lower().endswith(('.jpg', '.jpeg', '.png')):
            # Save image for potential DICOM SC conversion
            dest = os.path.join(staging, f"img_{saved:04d}{os.path.splitext(file.filename)[1]}")
            os.replace(tmp_path, dest)
            saved += 1
        else:
            # DICOM도 이미지도 아님 — 스풀 임시파일 정리.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # Create upload queue entry
    queue = UploadQueue(
        source="patient_portal",
        source_detail=f"token:{tok.token[:8]}, patient:{tok.patient_id}",
        patient_id=tok.patient_id,
        patient_name=tok.patient_name,
        file_count=saved,
        total_size_bytes=total_size,
        storage_path=staging,
        study_uids=list(study_uids) if study_uids else None,
        modalities=list(modalities) if modalities else None,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=72),
    )
    db.add(queue)
    # tok.used는 게이트에서 원자적으로 선점됨(중복 set 제거 — 커밋 후 stale 객체 회피)
    await db.commit()

    # Alert admin about pending upload
    try:
        from app.services.alert_service import alert_upload_pending
        import asyncio
        asyncio.create_task(alert_upload_pending("patient_portal", tok.patient_name or tok.patient_id, saved))
    except Exception:
        pass

    return {
        "ok": True,
        "files_saved": saved,
        "total_size": total_size,
        "queue_id": str(queue.id),
        "message": "업로드 완료. 담당 의료진 승인 후 시스템에 등록됩니다.",
    }


@router.get("/patient-upload/status")
async def patient_upload_status(
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Check upload status — public endpoint."""
    result = await db.execute(
        select(PatientUploadToken).where(PatientUploadToken.token == token)
    )
    tok = result.scalar_one_or_none()
    if not tok:
        return {"error": "Invalid token"}

    queue_q = await db.execute(
        select(UploadQueue).where(
            UploadQueue.source == "patient_portal",
            UploadQueue.patient_id == tok.patient_id,
        ).order_by(UploadQueue.created_at.desc()).limit(1)
    )
    queue = queue_q.scalar_one_or_none()

    return {
        "token_valid": tok.expires_at > datetime.now(timezone.utc) and not tok.used,
        "upload": {
            "status": queue.status if queue else None,
            "file_count": queue.file_count if queue else 0,
            "created_at": queue.created_at.isoformat() if queue else None,
        } if queue else None,
    }
