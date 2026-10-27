"""Cohort builder API for research — filter patients by criteria."""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import RequireRole
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/cohort", tags=["연구 코호트"])


class CohortQuery(BaseModel):
    modality: str | None = None
    date_from: str | None = None  # YYYYMMDD
    date_to: str | None = None
    body_part: str | None = None
    description_contains: str | None = None
    min_age: int | None = None
    max_age: int | None = None
    sex: str | None = None  # M, F
    limit: int = 100


@router.post("/search", summary="코호트 검색")
async def search_cohort(
    body: CohortQuery,
    request: Request,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RESEARCHER, allow_btg=False)),
):
    """연구 조건에 맞는 환자/Study 그룹을 검색합니다.

    조건: 모달리티, 날짜 범위, 검사 부위, 연령, 성별 등
    결과: 익명화 전 Study 목록 (배치 익명화에 연결 가능)
    """
    client = request.app.state.http_client

    # Build Orthanc query
    query = {}
    if body.modality:
        query["ModalitiesInStudy"] = body.modality
    if body.date_from and body.date_to:
        query["StudyDate"] = f"{body.date_from}-{body.date_to}"
    elif body.date_from:
        query["StudyDate"] = f"{body.date_from}-"
    elif body.date_to:
        query["StudyDate"] = f"-{body.date_to}"
    if body.body_part:
        query["BodyPartExamined"] = body.body_part
    if body.description_contains:
        query["StudyDescription"] = f"*{body.description_contains}*"
    if body.sex:
        query["PatientSex"] = body.sex

    resp = await client.post("/tools/find", json={
        "Level": "Study",
        "Query": query,
        "Expand": True,
        "Limit": body.limit,
    })

    if resp.status_code != 200:
        return {"studies": [], "total": 0, "error": "Orthanc query failed"}

    studies = resp.json()
    results = []
    for s in studies:
        main = s.get("MainDicomTags", {})
        patient = s.get("PatientMainDicomTags", {})
        results.append({
            "study_instance_uid": main.get("StudyInstanceUID", ""),
            "patient_id": patient.get("PatientID", ""),
            "patient_name": patient.get("PatientName", ""),
            "patient_sex": patient.get("PatientSex", ""),
            "patient_birth_date": patient.get("PatientBirthDate", ""),
            "study_date": main.get("StudyDate", ""),
            "modality": main.get("ModalitiesInStudy", ""),
            "description": main.get("StudyDescription", ""),
            "series_count": len(s.get("Series", [])),
        })

    return {
        "studies": results,
        "total": len(results),
        "query": body.model_dump(exclude_unset=True),
    }


@router.post("/export-uids", summary="코호트 UID 추출")
async def export_cohort_uids(
    body: CohortQuery,
    request: Request,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RESEARCHER, allow_btg=False)),
):
    """코호트 검색 결과의 StudyInstanceUID 목록만 추출합니다.

    배치 익명화 API (/api/v1/anonymize/batch)에 바로 전달 가능.
    """
    result = await search_cohort(body, request, user)
    uids = [s["study_instance_uid"] for s in result.get("studies", []) if s["study_instance_uid"]]
    return {
        "study_uids": uids,
        "total": len(uids),
        "anonymize_url": "/api/v1/anonymize/batch",
    }
