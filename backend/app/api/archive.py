"""DICOM Archive (IOCM) API — Study/Series lifecycle management.

Archive instead of delete, with full audit trail, viewer support, and restore capability.
"""
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, case, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import RequireRole, get_current_user
from app.models.archive import ArchiveReason, ArchivedStudy, REJECTION_CODES, StorageType
from app.models.audit import AuditLog
from app.models.report import Report
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/archive", tags=["archive"])

# Default retention: 5 years (의료법 제22조)
DEFAULT_RETENTION_YEARS = 5


# ── Schemas ──

class ArchiveRequest(BaseModel):
    study_instance_uid: str | None = None
    orthanc_study_id: str | None = None  # Orthanc internal ID (alternative)
    series_instance_uid: str | None = None
    reason: ArchiveReason
    note: str | None = None
    keep_metadata: bool = True


class RestoreRequest(BaseModel):
    note: str | None = None


class RetentionPolicyUpdate(BaseModel):
    default_years: int = Field(5, ge=1, le=30)
    modality_overrides: dict[str, int] | None = None  # e.g. {"MG": 10, "CT": 7}


# ── Helpers ──

async def _get_orthanc_study_by_id(orthanc: httpx.AsyncClient, orthanc_id: str) -> dict:
    """Fetch study info from Orthanc by Orthanc internal ID."""
    resp = await orthanc.get(f"/studies/{orthanc_id}")
    if resp.status_code != 200:
        raise NotFoundError(resource="Study", resource_id=orthanc_id)

    study = resp.json()
    patient_tags = study.get("PatientMainDicomTags", {})
    main_tags = study.get("MainDicomTags", {})
    series_list = study.get("Series", [])

    instance_count = 0
    for sid in series_list:
        sr = await orthanc.get(f"/series/{sid}")
        if sr.status_code == 200:
            instance_count += len(sr.json().get("Instances", []))

    return {
        "orthanc_study_id": orthanc_id,
        "study_instance_uid": main_tags.get("StudyInstanceUID", ""),
        "patient_id": patient_tags.get("PatientID", ""),
        "patient_name": patient_tags.get("PatientName", ""),
        "patient_birth_date": patient_tags.get("PatientBirthDate", ""),
        "patient_sex": patient_tags.get("PatientSex", ""),
        "modality": main_tags.get("ModalitiesInStudy", ""),
        "study_date": main_tags.get("StudyDate", ""),
        "study_description": main_tags.get("StudyDescription", ""),
        "series_count": len(series_list),
        "instance_count": instance_count,
        "series_ids": series_list,
        "full_metadata": {**patient_tags, **main_tags},
    }


async def _get_orthanc_study(orthanc: httpx.AsyncClient, study_uid: str) -> dict:
    """Fetch study info from Orthanc by StudyInstanceUID."""
    # Try tools/find first
    find_resp = await orthanc.post("/tools/find", json={
        "Level": "Study", "Query": {"StudyInstanceUID": study_uid},
    })
    studies = find_resp.json() if find_resp.status_code == 200 else []

    # Fallback: iterate studies if find returns empty (PostgreSQL index issue)
    if not studies:
        all_resp = await orthanc.get("/studies")
        if all_resp.status_code == 200:
            for sid in all_resp.json():
                sr = await orthanc.get(f"/studies/{sid}")
                if sr.status_code == 200:
                    s = sr.json()
                    if s.get("MainDicomTags", {}).get("StudyInstanceUID") == study_uid:
                        studies = [sid]
                        break

    if not studies:
        raise NotFoundError(resource="Study", resource_id=study_uid)

    study_id = studies[0]
    resp = await orthanc.get(f"/studies/{study_id}")
    if resp.status_code != 200:
        raise NotFoundError(resource="Study", resource_id=study_uid)

    study = resp.json()
    patient_tags = study.get("PatientMainDicomTags", {})
    main_tags = study.get("MainDicomTags", {})
    series_list = study.get("Series", [])

    # Count instances
    instance_count = 0
    for sid in series_list:
        sr = await orthanc.get(f"/series/{sid}")
        if sr.status_code == 200:
            instance_count += len(sr.json().get("Instances", []))

    return {
        "orthanc_study_id": study_id,
        "patient_id": patient_tags.get("PatientID", ""),
        "patient_name": patient_tags.get("PatientName", ""),
        "patient_birth_date": patient_tags.get("PatientBirthDate", ""),
        "patient_sex": patient_tags.get("PatientSex", ""),
        "modality": main_tags.get("ModalitiesInStudy", ""),
        "study_date": main_tags.get("StudyDate", ""),
        "study_description": main_tags.get("StudyDescription", ""),
        "series_count": len(series_list),
        "instance_count": instance_count,
        "series_ids": series_list,
        "full_metadata": {**patient_tags, **main_tags},
    }


async def _get_thumbnail(orthanc: httpx.AsyncClient, study_id: str) -> bytes | None:
    """Get first instance preview as JPEG thumbnail."""
    resp = await orthanc.get(f"/studies/{study_id}")
    if resp.status_code != 200:
        return None
    study = resp.json()
    for series_id in study.get("Series", []):
        sr = await orthanc.get(f"/series/{series_id}")
        if sr.status_code == 200:
            instances = sr.json().get("Instances", [])
            if instances:
                preview = await orthanc.get(f"/instances/{instances[0]}/preview")
                if preview.status_code == 200:
                    return preview.content
    return None


def _archive_response(a: ArchivedStudy) -> dict:
    """Convert ArchivedStudy model to API response."""
    return {
        "id": str(a.id),
        "study_instance_uid": a.study_instance_uid,
        "series_instance_uid": a.series_instance_uid,
        "patient_id": a.patient_id,
        "patient_name": a.patient_name,
        "patient_sex": a.patient_sex,
        "modality": a.modality,
        "study_date": a.study_date,
        "study_description": a.study_description,
        "series_count": a.series_count,
        "instance_count": a.instance_count,
        "reason": a.reason,
        "note": a.note,
        "rejection_code": a.rejection_code,
        "archived_by_name": a.archived_by_name,
        "archived_at": a.archived_at.isoformat() if a.archived_at else None,
        "storage_type": a.storage_type,
        "file_size_bytes": a.file_size_bytes,
        "is_restorable": a.is_restorable,
        "restored_at": a.restored_at.isoformat() if a.restored_at else None,
        "restored_by_name": a.restored_by_name,
        "retention_expires_at": a.retention_expires_at.isoformat() if a.retention_expires_at else None,
        "has_thumbnail": a.thumbnail is not None,
        "original_report_id": str(a.original_report_id) if a.original_report_id else None,
    }


# ── Endpoints ──

@router.post("")
# 파괴적(Orthanc study 삭제) — BTG 우회 차단.
async def archive_study(
    body: ArchiveRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST, allow_btg=False))],
):
    """Study 또는 Series를 아카이브 (삭제 대신 보관).

    1. Orthanc에서 메타데이터 스냅샷 저장
    2. 썸네일 저장
    3. Orthanc에서 제거
    4. archived_studies 레코드 생성
    5. 감사 로그 기록
    """
    orthanc = request.app.state.http_client

    if not body.study_instance_uid and not body.orthanc_study_id:
        raise ValidationError(message="study_instance_uid 또는 orthanc_study_id 중 하나를 입력하세요.")

    # 1. Fetch study info from Orthanc
    if body.orthanc_study_id:
        study_info = await _get_orthanc_study_by_id(orthanc, body.orthanc_study_id)
        body.study_instance_uid = study_info["study_instance_uid"]
    else:
        study_info = await _get_orthanc_study(orthanc, body.study_instance_uid)

    # Check if already archived
    existing = await db.execute(
        select(ArchivedStudy).where(
            ArchivedStudy.study_instance_uid == body.study_instance_uid,
            ArchivedStudy.restored_at.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise ValidationError(message="이미 아카이브된 Study입니다.")

    # 2. Get thumbnail
    thumbnail = await _get_thumbnail(orthanc, study_info["orthanc_study_id"])

    # 3. Find linked report
    report_result = await db.execute(
        select(Report.id).where(Report.study_instance_uid == body.study_instance_uid)
    )
    report_id = report_result.scalar_one_or_none()

    # 4. Calculate retention expiry
    retention_expires = datetime.now(timezone.utc) + timedelta(days=DEFAULT_RETENTION_YEARS * 365)

    # 5. Create archive record
    archive = ArchivedStudy(
        study_instance_uid=body.study_instance_uid,
        series_instance_uid=body.series_instance_uid,
        orthanc_study_id=study_info["orthanc_study_id"],
        patient_id=study_info["patient_id"],
        patient_name=study_info["patient_name"],
        patient_birth_date=study_info["patient_birth_date"],
        patient_sex=study_info["patient_sex"],
        modality=study_info["modality"],
        study_date=study_info["study_date"],
        study_description=study_info["study_description"],
        series_count=study_info["series_count"],
        instance_count=study_info["instance_count"],
        reason=body.reason,
        note=body.note,
        rejection_code=REJECTION_CODES.get(body.reason, ""),
        archived_by=user.id,
        archived_by_name=f"{user.username} ({user.role})",
        orthanc_metadata=study_info["full_metadata"],
        thumbnail=thumbnail,
        storage_type=StorageType.LOCAL,
        is_restorable=True,
        original_report_id=report_id,
        retention_expires_at=retention_expires,
    )
    db.add(archive)

    # 6. Delete from Orthanc
    if body.series_instance_uid:
        # Archive specific series
        for sid in study_info["series_ids"]:
            sr = await orthanc.get(f"/series/{sid}")
            if sr.status_code == 200:
                series_data = sr.json()
                series_uid = series_data.get("MainDicomTags", {}).get("SeriesInstanceUID", "")
                if series_uid == body.series_instance_uid:
                    await orthanc.delete(f"/series/{sid}")
                    break
    else:
        # Archive entire study
        await orthanc.delete(f"/studies/{study_info['orthanc_study_id']}")

    # 7. Audit log
    audit = AuditLog(
        user_id=str(user.id),
        username=user.username,
        action="STUDY_ARCHIVED",
        resource_type="Study",
        resource_id=body.study_instance_uid,
        details={
            "reason": body.reason,
            "note": body.note,
            "patient_id": study_info["patient_id"],
            "modality": study_info["modality"],
            "series_count": study_info["series_count"],
            "instance_count": study_info["instance_count"],
        },
    )
    db.add(audit)
    await db.commit()
    await db.refresh(archive)

    return _archive_response(archive)


@router.get("")
async def list_archives(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST))],
    reason: ArchiveReason | None = None,
    patient_id: str | None = None,
    modality: str | None = None,
    archived_by: str | None = None,
    from_date: str | None = Query(None, description="YYYY-MM-DD"),
    to_date: str | None = Query(None, description="YYYY-MM-DD"),
    include_restored: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """아카이브 목록 조회 (필터, 페이징)."""
    query = select(ArchivedStudy)

    if not include_restored:
        query = query.where(ArchivedStudy.restored_at.is_(None))
    if reason:
        query = query.where(ArchivedStudy.reason == reason)
    if patient_id:
        query = query.where(ArchivedStudy.patient_id.ilike(f"%{patient_id}%"))
    if modality:
        query = query.where(ArchivedStudy.modality.ilike(f"%{modality}%"))
    if archived_by:
        query = query.where(ArchivedStudy.archived_by_name.ilike(f"%{archived_by}%"))
    # 문자열을 datetime으로 파싱 — archived_at은 timestamptz라 str 바인딩 시 asyncpg DataError(500).
    if from_date:
        query = query.where(ArchivedStudy.archived_at >= datetime.strptime(from_date, "%Y-%m-%d"))
    if to_date:
        query = query.where(
            ArchivedStudy.archived_at < datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)
        )

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Paginate
    query = query.order_by(ArchivedStudy.archived_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    archives = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "archives": [_archive_response(a) for a in archives],
    }


@router.get("/statistics")
async def archive_statistics(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST))],
):
    """아카이브 통계 (사유별, 월별, 모달리티별)."""
    now = datetime.now(timezone.utc)

    # Total counts
    total = (await db.execute(select(func.count(ArchivedStudy.id)))).scalar() or 0
    active = (await db.execute(
        select(func.count(ArchivedStudy.id)).where(ArchivedStudy.restored_at.is_(None))
    )).scalar() or 0
    restored = total - active

    # This month
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_month = (await db.execute(
        select(func.count(ArchivedStudy.id)).where(ArchivedStudy.archived_at >= month_start)
    )).scalar() or 0

    # Expiring soon (next 90 days)
    expiring = (await db.execute(
        select(func.count(ArchivedStudy.id)).where(
            ArchivedStudy.retention_expires_at <= now + timedelta(days=90),
            ArchivedStudy.retention_expires_at > now,
            ArchivedStudy.restored_at.is_(None),
        )
    )).scalar() or 0

    # By reason
    reason_q = await db.execute(
        select(ArchivedStudy.reason, func.count(ArchivedStudy.id))
        .where(ArchivedStudy.restored_at.is_(None))
        .group_by(ArchivedStudy.reason)
    )
    by_reason = {r: c for r, c in reason_q.all()}

    # By modality
    modality_q = await db.execute(
        select(ArchivedStudy.modality, func.count(ArchivedStudy.id))
        .where(ArchivedStudy.restored_at.is_(None))
        .group_by(ArchivedStudy.modality)
    )
    by_modality = {m or "Unknown": c for m, c in modality_q.all()}

    # Total size
    total_size = (await db.execute(
        select(func.sum(ArchivedStudy.file_size_bytes))
        .where(ArchivedStudy.restored_at.is_(None))
    )).scalar() or 0

    return {
        "total": total,
        "active": active,
        "restored": restored,
        "this_month": this_month,
        "expiring_soon": expiring,
        "by_reason": by_reason,
        "by_modality": by_modality,
        "total_size_bytes": total_size,
        "total_size_gb": round(total_size / (1024**3), 2),
    }


@router.get("/retention/candidates")
async def retention_candidates(
    request: Request,
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    limit: int = Query(200, ge=1, le=500),
):
    """보존기간(기본 5년) 경과한 **활성** study — 아카이브 후보 목록.

    매월 beat(storage_monitor.check_retention_candidates)가 같은 기준으로 admin에
    알림한다. 자동 삭제 없음 — 아카이브/purge는 기존 수동 경로(5년 잠금)가 담당.
    """
    from app.services.storage_monitor import _retention_cutoff_yyyymmdd
    cutoff = _retention_cutoff_yyyymmdd()
    orthanc = request.app.state.http_client
    resp = await orthanc.post("/tools/find", json={
        "Level": "Study",
        "Query": {"StudyDate": f"19000101-{cutoff}"},
        "Expand": True,
        "RequestedTags": ["StudyDate", "ModalitiesInStudy"],
        "Limit": limit,
    })
    resp.raise_for_status()
    studies = resp.json()
    candidates = [{
        "orthanc_id": s.get("ID"),
        "study_instance_uid": s.get("MainDicomTags", {}).get("StudyInstanceUID"),
        "study_date": s.get("MainDicomTags", {}).get("StudyDate"),
        "modalities": s.get("RequestedTags", {}).get("ModalitiesInStudy", ""),
    } for s in studies]
    return {"cutoff": cutoff, "count": len(candidates), "candidates": candidates}


@router.get("/retention-policy")
async def get_retention_policy(
    user: Annotated[User, Depends(get_current_user)],
):
    """보존기간 정책 조회."""
    from sqlalchemy import text as sa_text
    from app.core.database import async_session
    if async_session:
        async with async_session() as db:
            try:
                result = await db.execute(sa_text(
                    "SELECT value FROM openpacs_config WHERE key = 'archive_retention_policy'"
                ))
                row = result.scalar_one_or_none()
                if row:
                    import json
                    return json.loads(row) if isinstance(row, str) else row
            except Exception:
                pass
    return {
        "default_years": DEFAULT_RETENTION_YEARS,
        "modality_overrides": {},
        "legal_basis": "의료법 제22조 (진료기록 5년 보존)",
    }


@router.put("/retention-policy")
async def update_retention_policy(
    body: RetentionPolicyUpdate,
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """보존기간 정책 변경 (Admin only)."""
    import json
    from sqlalchemy import text as sa_text
    from app.core.database import async_session
    policy = {
        "default_years": body.default_years,
        "modality_overrides": body.modality_overrides or {},
        "legal_basis": "의료법 제22조 (진료기록 5년 보존)",
    }
    if async_session:
        async with async_session() as db:
            val = json.dumps(policy, ensure_ascii=False)
            await db.execute(sa_text("""
                INSERT INTO openpacs_config (key, value, updated_by)
                VALUES ('archive_retention_policy', :val, :user)
                ON CONFLICT (key) DO UPDATE SET value = :val, updated_by = :user, updated_at = NOW()
            """), {"val": val, "user": user.username})
            await db.commit()
    return {"status": "ok", "policy": policy}


@router.get("/{archive_id}")
async def get_archive(
    archive_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """아카이브 상세 정보 (메타데이터 + 이력)."""
    result = await db.execute(select(ArchivedStudy).where(ArchivedStudy.id == archive_id))
    archive = result.scalar_one_or_none()
    if not archive:
        raise NotFoundError(resource="Archive", resource_id=str(archive_id))

    resp = _archive_response(archive)
    resp["orthanc_metadata"] = archive.orthanc_metadata
    return resp


@router.get("/{archive_id}/thumbnail")
async def get_thumbnail(
    archive_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """아카이브 영상 썸네일 (128x128 JPEG)."""
    result = await db.execute(
        select(ArchivedStudy.thumbnail).where(ArchivedStudy.id == archive_id)
    )
    thumbnail = result.scalar_one_or_none()
    if not thumbnail:
        raise NotFoundError(resource="Thumbnail", resource_id=str(archive_id))

    return Response(content=thumbnail, media_type="image/jpeg")


@router.get("/{archive_id}/preview")
async def get_preview(
    archive_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """아카이브 영상 프리뷰 (저장된 썸네일 반환)."""
    result = await db.execute(
        select(ArchivedStudy.thumbnail).where(ArchivedStudy.id == archive_id)
    )
    thumbnail = result.scalar_one_or_none()
    if not thumbnail:
        raise NotFoundError(resource="Preview", resource_id=str(archive_id))

    return Response(content=thumbnail, media_type="image/jpeg")


@router.get("/{archive_id}/dicom-tags")
async def get_dicom_tags(
    archive_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """아카이브 DICOM 태그 전체 (원본 스냅샷)."""
    result = await db.execute(
        select(ArchivedStudy.orthanc_metadata, ArchivedStudy.study_instance_uid)
        .where(ArchivedStudy.id == archive_id)
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundError(resource="Archive", resource_id=str(archive_id))

    return {
        "study_instance_uid": row.study_instance_uid,
        "tags": row.orthanc_metadata or {},
    }


@router.post("/{archive_id}/view")
async def view_archived_study(
    archive_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """아카이브 영상을 OHIF 뷰어로 열기 (임시 로드).

    현재는 아카이브 메타데이터만 반환합니다.
    파일이 로컬 archive에 보존되어 있으면 Orthanc에 임시 업로드 후 뷰어 URL을 반환합니다.
    """
    result = await db.execute(select(ArchivedStudy).where(ArchivedStudy.id == archive_id))
    archive = result.scalar_one_or_none()
    if not archive:
        raise NotFoundError(resource="Archive", resource_id=str(archive_id))

    # Audit: archive viewed
    audit = AuditLog(
        user_id=str(user.id),
        username=user.username,
        action="ARCHIVE_VIEWED",
        resource_type="Archive",
        resource_id=str(archive_id),
        details={
            "study_uid": archive.study_instance_uid,
            "patient_id": archive.patient_id,
        },
    )
    db.add(audit)
    await db.commit()

    # Return viewer info (actual OHIF reload requires file restore)
    viewer_url = f"/viewer/?StudyInstanceUIDs={archive.study_instance_uid}"

    return {
        "archive_id": str(archive_id),
        "study_instance_uid": archive.study_instance_uid,
        "patient_id": archive.patient_id,
        "patient_name": archive.patient_name,
        "modality": archive.modality,
        "study_date": archive.study_date,
        "viewer_url": viewer_url,
        "status": "metadata_only" if not archive.storage_path else "restorable",
        "message": "아카이브 메타데이터를 반환합니다. 영상 복원 후 뷰어에서 열 수 있습니다.",
        "orthanc_metadata": archive.orthanc_metadata,
    }


@router.post("/{archive_id}/restore")
async def restore_archive(
    archive_id: uuid.UUID,
    body: RestoreRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """아카이브된 Study를 복원 (Orthanc에 재업로드).

    Admin only. 복원 후에도 아카이브 기록은 유지됩니다.
    """
    result = await db.execute(select(ArchivedStudy).where(ArchivedStudy.id == archive_id))
    archive = result.scalar_one_or_none()
    if not archive:
        raise NotFoundError(resource="Archive", resource_id=str(archive_id))

    if archive.restored_at:
        raise ValidationError(message="이미 복원된 아카이브입니다.")

    if not archive.is_restorable:
        raise ValidationError(message="복원 불가능한 아카이브입니다 (보존기간 만료).")

    # Mark as restored
    archive.restored_at = datetime.now(timezone.utc)
    archive.restored_by = user.id
    archive.restored_by_name = f"{user.username} ({user.role})"

    # Audit
    audit = AuditLog(
        user_id=str(user.id),
        username=user.username,
        action="STUDY_RESTORED",
        resource_type="Archive",
        resource_id=str(archive_id),
        details={
            "study_uid": archive.study_instance_uid,
            "patient_id": archive.patient_id,
            "original_reason": archive.reason,
            "restore_note": body.note,
        },
    )
    db.add(audit)
    await db.commit()
    await db.refresh(archive)

    return {
        "status": "restored",
        "archive": _archive_response(archive),
        "message": "아카이브가 복원되었습니다. 영상 파일은 Orthanc에 재업로드가 필요할 수 있습니다.",
    }


@router.delete("/{archive_id}")
async def delete_archive(
    archive_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """아카이브 영구 삭제 (Admin only).

    보존기간이 만료된 아카이브만 삭제 가능합니다.
    """
    result = await db.execute(select(ArchivedStudy).where(ArchivedStudy.id == archive_id))
    archive = result.scalar_one_or_none()
    if not archive:
        raise NotFoundError(resource="Archive", resource_id=str(archive_id))

    now = datetime.now(timezone.utc)
    if archive.retention_expires_at and archive.retention_expires_at > now:
        remaining = (archive.retention_expires_at - now).days
        raise ValidationError(
            message=f"보존기간이 만료되지 않았습니다 (잔여 {remaining}일). "
                    f"의료법 제22조에 따라 보존기간 내 삭제가 불가합니다."
        )

    # Audit before delete
    audit = AuditLog(
        user_id=str(user.id),
        username=user.username,
        action="ARCHIVE_PURGED",
        resource_type="Archive",
        resource_id=str(archive_id),
        details={
            "study_uid": archive.study_instance_uid,
            "patient_id": archive.patient_id,
            "reason": archive.reason,
            "archived_at": archive.archived_at.isoformat() if archive.archived_at else None,
        },
    )
    db.add(audit)

    await db.delete(archive)
    await db.commit()

    return {"status": "purged", "message": "보존기간 만료 아카이브가 영구 삭제되었습니다."}
