"""DICOM 수신 모니터 — 최근 인바운드 스터디(C-STORE/업로드/Q-R retrieve) 현황.

Orthanc를 ground-truth(실제 수신)로 LastUpdate 역순 조회하고, study_provenance로
출처(AE Title·기관·장비·수신경로)를 결합한다. 방사선사가 모달리티 전송이 도착했는지
실시간(자동 새로고침)으로 확인하는 용도.
"""
import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import RequireRole
from app.models.dicom_issue import StudyProvenance
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/reception", tags=["수신 모니터"])


def _fmt_lastupdate(lu: str | None) -> str | None:
    """Orthanc LastUpdate 'YYYYMMDDThhmmss' -> ISO 'YYYY-MM-DDThh:mm:ss'."""
    if not lu or "T" not in lu:
        return lu
    d, t = lu.split("T", 1)
    if len(d) != 8 or len(t) < 6:
        return lu
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}T{t[:2]}:{t[2:4]}:{t[4:6]}"


@router.get("/recent", summary="최근 DICOM 수신 현황")
async def recent_receptions(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST))],
    limit: int = Query(30, ge=1, le=100),
):
    """최근 수신된 스터디를 Orthanc LastUpdate 역순으로 조회 + 출처 결합."""
    studies: list = []
    try:
        async with httpx.AsyncClient(
            base_url=settings.orthanc_url,
            auth=(settings.orthanc_username, settings.orthanc_password),
            timeout=20,
        ) as c:
            resp = await c.post(
                "/tools/find",
                json={
                    "Level": "Study",
                    "Query": {},
                    "Expand": True,
                    "OrderBy": [{"Type": "Metadata", "Key": "LastUpdate", "Direction": "DESC"}],
                    "Limit": limit,
                    "RequestedTags": ["ModalitiesInStudy"],
                },
            )
            if resp.status_code == 200:
                studies = resp.json()
            else:
                logger.warning(f"reception: orthanc /tools/find {resp.status_code}")
    except Exception as e:  # pragma: no cover - network/orthanc failure
        logger.error(f"reception: orthanc query failed: {e}")
        return {"count": 0, "studies": [], "error": "orthanc_unavailable"}

    uids = [
        s.get("MainDicomTags", {}).get("StudyInstanceUID")
        for s in studies
        if s.get("MainDicomTags", {}).get("StudyInstanceUID")
    ]
    prov_map: dict = {}
    if uids:
        rows = await db.execute(
            select(StudyProvenance).where(StudyProvenance.study_instance_uid.in_(uids))
        )
        for p in rows.scalars().all():
            prov_map[p.study_instance_uid] = p

    out = []
    for s in studies:
        mt = s.get("MainDicomTags", {})
        pt = s.get("PatientMainDicomTags", {})
        rt = s.get("RequestedTags", {}) or {}
        uid = mt.get("StudyInstanceUID")
        prov = prov_map.get(uid)
        out.append({
            "study_uid": uid,
            "orthanc_id": s.get("ID"),
            "received_at": _fmt_lastupdate(s.get("LastUpdate")),
            "is_stable": s.get("IsStable"),
            "patient_name": pt.get("PatientName") or "",
            "patient_id": pt.get("PatientID") or "",
            "study_date": mt.get("StudyDate") or "",
            "study_description": mt.get("StudyDescription") or "",
            "modality": rt.get("ModalitiesInStudy") or "",
            "series_count": len(s.get("Series", [])),
            "origin": prov.origin if prov else "unknown",
            "upload_method": prov.upload_method if prov else None,
            "source_ae_title": prov.source_ae_title if prov else None,
            "source_institution": prov.source_institution if prov else None,
            "source_device": prov.source_device if prov else None,
        })
    return {"count": len(out), "studies": out}
