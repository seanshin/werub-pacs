"""DICOM Study Provenance (origin tracking) API."""
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import AuditLogger
from app.core.database import get_db
from app.core.security import RequireRole, get_current_user
from app.models.dicom_issue import StudyProvenance
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/provenance", tags=["provenance"])

# AE Title → origin mapping (auto-classify on ingestion)
AE_ORIGIN_MAP = {
    "OPENPACS": "internal",       # 자체 서버
    "STORESCU": "test_data",      # 테스트 전송 도구
    "DCMTK": "test_data",
    "FINDSCU": "test_data",
}

ORIGIN_LABELS = {
    "internal": "원내 촬영",
    "external": "원외 (타 병원)",
    "patient_upload": "환자 업로드",
    "kiosk": "키오스크",
    "test_data": "테스트 데이터",
    "research": "연구용",
    "ai_generated": "AI 생성",
    "migration": "데이터 이관",
    "unknown": "미분류",
}


def classify_origin(ae_title: str | None, manufacturer: str | None, upload_method: str | None) -> str:
    """Auto-classify study origin based on AE Title, manufacturer, and upload method."""
    if upload_method == "patient_portal":
        return "patient_upload"
    if upload_method == "kiosk":
        return "kiosk"
    if upload_method == "migration":
        return "migration"
    if upload_method in ("cd_import",):
        return "external"

    if ae_title:
        ae_upper = ae_title.upper().strip()
        if ae_upper in AE_ORIGIN_MAP:
            return AE_ORIGIN_MAP[ae_upper]
        # Known internal AE patterns
        if any(p in ae_upper for p in ("CT_", "MR_", "CR_", "DX_", "US_", "XA_")):
            return "internal"

    # Known test/demo data sources
    if manufacturer:
        mfr = manufacturer.upper()
        if any(m in mfr for m in ("PYDICOM", "OFFIS", "ACME", "DUMMY", "TEST", "DEMO", "SAMPLE")):
            return "test_data"
        if "OPENPACS" in mfr:
            return "ai_generated"
        # Known real equipment manufacturers → likely internal
        if any(m in mfr for m in (
            "SIEMENS", "GE ", "G.E.", "PHILIPS", "CANON", "FUJI", "SAMSUNG", "HOLOGIC",
            "TOSHIBA", "HITACHI", "SHIMADZU", "AGFA", "CARESTREAM", "KONICA", "MINOLTA",
            "ALOKA", "SONOSITE", "ESAOTE", "MINDRAY", "ZONARE", "SUPERSONIC",
            "VARIAN", "ELEKTA", "ACCURAY", "BRAINLAB", "CMS",
        )):
            return "internal"

    return "unknown"


async def record_provenance(
    db: AsyncSession,
    study_uid: str,
    orthanc_id: str | None = None,
    ae_title: str | None = None,
    manufacturer: str | None = None,
    station_name: str | None = None,
    upload_method: str | None = None,
    uploaded_by: str | None = None,
    source_institution: str | None = None,
    remote_id: str | None = None,
    tags: dict | None = None,
):
    """Record or update provenance for a study. Called from upload/scan pipelines."""
    existing = await db.execute(
        select(StudyProvenance).where(StudyProvenance.study_instance_uid == study_uid)
    )
    prov = existing.scalar_one_or_none()

    origin = classify_origin(ae_title, manufacturer, upload_method)

    if prov:
        # Don't overwrite manually verified provenance
        if not prov.verified_at:
            prov.origin = origin
            if ae_title:
                prov.source_ae_title = ae_title
            if manufacturer:
                prov.source_manufacturer = manufacturer
            if upload_method:
                prov.upload_method = upload_method
    else:
        prov = StudyProvenance(
            study_instance_uid=study_uid,
            orthanc_id=orthanc_id,
            origin=origin,
            source_ae_title=ae_title,
            source_device=station_name,
            source_manufacturer=manufacturer,
            upload_method=upload_method or "c-store",
            uploaded_by=uploaded_by,
            source_institution=source_institution,
            tags=tags or {},
        )
        if remote_id:
            import uuid as _uuid
            try:
                prov.remote_id = _uuid.UUID(remote_id)
            except Exception:
                pass
        db.add(prov)

    return prov


# ─── API Endpoints ───────────────────────────────────────────────────────────

@router.get("")
async def list_provenance(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    origin: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List study provenance records."""
    q = select(StudyProvenance).order_by(StudyProvenance.received_at.desc())
    if origin:
        q = q.where(StudyProvenance.origin == origin)

    total_q = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_q.scalar() or 0
    result = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    rows = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "origin_labels": ORIGIN_LABELS,
        "items": [
            {
                "id": str(p.id),
                "study_instance_uid": p.study_instance_uid,
                "origin": p.origin,
                "origin_label": ORIGIN_LABELS.get(p.origin, p.origin),
                "source_institution": p.source_institution,
                "source_ae_title": p.source_ae_title,
                "source_device": p.source_device,
                "source_manufacturer": p.source_manufacturer,
                "upload_method": p.upload_method,
                "uploaded_by": p.uploaded_by,
                "tags": p.tags,
                "note": p.note,
                "received_at": p.received_at.isoformat() if p.received_at else None,
                "verified_at": p.verified_at.isoformat() if p.verified_at else None,
            }
            for p in rows
        ],
    }


@router.get("/statistics")
async def provenance_statistics(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Provenance statistics by origin."""
    result = await db.execute(
        select(StudyProvenance.origin, func.count()).group_by(StudyProvenance.origin)
    )
    by_origin = dict(result.all())

    method_q = await db.execute(
        select(StudyProvenance.upload_method, func.count())
        .where(StudyProvenance.upload_method.isnot(None))
        .group_by(StudyProvenance.upload_method)
    )

    total_q = await db.execute(select(func.count()).select_from(StudyProvenance))
    unverified_q = await db.execute(
        select(func.count()).select_from(StudyProvenance).where(StudyProvenance.verified_at.is_(None))
    )

    return {
        "total": total_q.scalar() or 0,
        "unverified": unverified_q.scalar() or 0,
        "by_origin": {k: {"count": v, "label": ORIGIN_LABELS.get(k, k)} for k, v in by_origin.items()},
        "by_method": dict(method_q.all()),
        "origin_labels": ORIGIN_LABELS,
    }


@router.get("/{study_uid}")
async def get_provenance(
    study_uid: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Get provenance for a specific study."""
    result = await db.execute(
        select(StudyProvenance).where(StudyProvenance.study_instance_uid == study_uid)
    )
    p = result.scalar_one_or_none()
    if not p:
        return {"found": False, "study_instance_uid": study_uid}

    return {
        "found": True,
        "id": str(p.id),
        "study_instance_uid": p.study_instance_uid,
        "origin": p.origin,
        "origin_label": ORIGIN_LABELS.get(p.origin, p.origin),
        "source_institution": p.source_institution,
        "source_ae_title": p.source_ae_title,
        "source_device": p.source_device,
        "source_manufacturer": p.source_manufacturer,
        "upload_method": p.upload_method,
        "uploaded_by": p.uploaded_by,
        "tags": p.tags,
        "note": p.note,
        "received_at": p.received_at.isoformat() if p.received_at else None,
        "verified_at": p.verified_at.isoformat() if p.verified_at else None,
    }


class ProvenanceUpdate(BaseModel):
    origin: str | None = None
    source_institution: str | None = None
    tags: dict | None = None
    note: str | None = None


@router.put("/{study_uid}")
@AuditLogger.log("PROVENANCE_UPDATE", "StudyProvenance")
async def update_provenance(
    study_uid: str,
    body: ProvenanceUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
):
    """Update provenance — manual origin correction, tagging, notes."""
    result = await db.execute(
        select(StudyProvenance).where(StudyProvenance.study_instance_uid == study_uid)
    )
    p = result.scalar_one_or_none()
    if not p:
        return {"error": "Provenance not found"}

    if body.origin is not None:
        p.origin = body.origin
    if body.source_institution is not None:
        p.source_institution = body.source_institution
    if body.tags is not None:
        p.tags = body.tags
    if body.note is not None:
        p.note = body.note

    p.verified_at = datetime.now(timezone.utc)
    p.verified_by = user.id
    await db.commit()

    return {"ok": True, "origin": p.origin, "origin_label": ORIGIN_LABELS.get(p.origin, p.origin)}


@router.post("/scan")
async def scan_provenance(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, allow_btg=False))],
    limit: int = Query(100, ge=1, le=500),
):
    """Scan existing studies and auto-classify provenance for those without records."""
    client = request.app.state.http_client

    # Fetch study IDs then expand individually
    resp = await client.get("/studies", params={"since": 0, "limit": limit})
    study_ids = resp.json() if resp.status_code == 200 and isinstance(resp.json(), list) else []
    studies = []
    for sid in study_ids:
        try:
            sr = await client.get(f"/studies/{sid}")
            if sr.status_code == 200:
                studies.append(sr.json())
        except Exception:
            continue

    existing_q = await db.execute(select(StudyProvenance.study_instance_uid))
    existing_uids = {row[0] for row in existing_q.all()}

    created = 0
    for study in studies:
        try:
            study_uid = study.get("MainDicomTags", {}).get("StudyInstanceUID", "")
            if not study_uid or study_uid in existing_uids:
                continue

            # Get first instance for metadata
            ae_title = None
            manufacturer = None
            station_name = None
            series_list = study.get("Series", [])
            if series_list:
                try:
                    ss = await client.get(f"/series/{series_list[0]}")
                    if ss.status_code == 200:
                        s_data = ss.json()
                        insts = s_data.get("Instances", [])
                        if insts:
                            tags = await client.get(f"/instances/{insts[0]}/simplified-tags")
                            if tags.status_code == 200:
                                t = tags.json()
                                ae_title = t.get("SourceApplicationEntityTitle")
                                manufacturer = t.get("Manufacturer")
                                station_name = t.get("StationName")
                except Exception:
                    pass

            origin = classify_origin(ae_title, manufacturer, None)

            db.add(StudyProvenance(
                study_instance_uid=study_uid,
                orthanc_id=study.get("ID"),
                origin=origin,
                source_ae_title=(ae_title or "")[:16] or None,
                source_device=(station_name or "")[:128] or None,
                source_manufacturer=(manufacturer or "")[:64] or None,
                upload_method="c-store",
            ))
            try:
                await db.flush()
                created += 1
                existing_uids.add(study_uid)
            except Exception:
                await db.rollback()
        except Exception as e:
            logger.warning(f"Provenance scan error for study: {e}")
            try:
                await db.rollback()
            except Exception:
                pass
            continue

    await db.commit()
    return {"ok": True, "created": created, "total_studies": len(studies), "already_tracked": len(existing_uids)}
