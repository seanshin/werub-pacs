"""Equipment transfer status monitoring — tracks DICOM modality send status."""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import RequireRole
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/equipment", tags=["장비 모니터링"])


@router.get("/status", summary="장비별 전송 현황")
async def get_equipment_status(
    request: Request,
    user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST)),
):
    """Orthanc에 등록된 모달리티별 최근 전송 현황을 조회합니다."""
    client = request.app.state.http_client

    # Get configured modalities from Orthanc
    modalities_resp = await client.get("/modalities")
    modalities = modalities_resp.json() if modalities_resp.status_code == 200 else []

    equipment = []
    for mod_name in modalities:
        mod_resp = await client.get(f"/modalities/{mod_name}")
        mod_info = mod_resp.json() if mod_resp.status_code == 200 else {}

        equipment.append({
            "name": mod_name,
            "ae_title": mod_info.get("AET", ""),
            "host": mod_info.get("Host", ""),
            "port": mod_info.get("Port", 0),
        })

    return {"equipment": equipment, "total": len(equipment)}


@router.get("/transfers", summary="최근 전송 이력")
async def get_recent_transfers(
    request: Request,
    user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST)),
    hours: int = Query(24, ge=1, le=168, description="조회 기간 (시간)"),
    limit: int = Query(50, ge=1, le=200),
):
    """Orthanc 변경 이력에서 최근 수신된 Study 목록을 조회합니다.

    C-STORE로 전송된 영상의 수신 시각, 모달리티, 환자 정보를 반환합니다.
    """
    client = request.app.state.http_client

    # Get recent changes from Orthanc
    changes_resp = await client.get(f"/changes?limit={limit}")
    if changes_resp.status_code != 200:
        return {"transfers": [], "total": 0, "message": "Orthanc 변경 이력 조회 실패"}

    changes = changes_resp.json()
    transfers = []

    for change in changes.get("Changes", []):
        if change.get("ChangeType") != "NewStudy":
            continue

        study_id = change.get("ID", "")
        # requestedTags — ModalitiesInStudy는 MainDicomTags에 없고 RequestedTags로만 채워짐.
        study_resp = await client.get(f"/studies/{study_id}", params={"requestedTags": "ModalitiesInStudy"})
        if study_resp.status_code != 200:
            continue

        study = study_resp.json()
        tags = study.get("MainDicomTags", {})
        patient = study.get("PatientMainDicomTags", {})

        transfers.append({
            "orthanc_id": study_id,
            "study_uid": tags.get("StudyInstanceUID", ""),
            "patient_id": patient.get("PatientID", ""),
            "patient_name": patient.get("PatientName", ""),
            "modality": study.get("RequestedTags", {}).get("ModalitiesInStudy", ""),
            "study_date": tags.get("StudyDate", ""),
            "study_description": tags.get("StudyDescription", ""),
            "institution": tags.get("InstitutionName", ""),
            "station_name": tags.get("StationName", ""),
            "received_at": change.get("Date", ""),
            "series_count": len(study.get("Series", [])),
        })

    return {"transfers": transfers, "total": len(transfers)}


@router.get("/summary", summary="모달리티별 통계")
async def get_transfer_summary(
    request: Request,
    user: User = Depends(RequireRole(Role.ADMIN, Role.TECHNOLOGIST, Role.RADIOLOGIST)),
    date: str | None = Query(None, description="날짜 (YYYY-MM-DD, 기본=오늘)"),
):
    """오늘 또는 지정 날짜의 모달리티별 수신 건수를 반환합니다."""
    client = request.app.state.http_client
    target_date = date or datetime.now(timezone.utc).strftime("%Y%m%d")
    target_date_clean = target_date.replace("-", "")

    resp = await client.post("/tools/find", json={
        "Level": "Study",
        "Query": {"StudyDate": target_date_clean},
        "Expand": True,
        "RequestedTags": ["ModalitiesInStudy"],   # MainDicomTags엔 없음 → RequestedTags로만
    })

    if resp.status_code != 200:
        return {"summary": {}, "total": 0, "date": target_date}

    studies = resp.json()
    by_modality: dict[str, int] = {}
    by_station: dict[str, int] = {}

    for s in studies:
        tags = s.get("MainDicomTags", {})
        mod = s.get("RequestedTags", {}).get("ModalitiesInStudy") or "UNKNOWN"
        station = tags.get("StationName", "unknown")
        by_modality[mod] = by_modality.get(mod, 0) + 1
        by_station[station] = by_station.get(station, 0) + 1

    return {
        "date": target_date,
        "total": len(studies),
        "by_modality": by_modality,
        "by_station": by_station,
    }
