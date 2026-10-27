"""Prior Study API — find previous studies for the same patient.

Essential for radiology reading: compare current vs prior exams
to assess disease progression or treatment response.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.report import ReportReadRoles, _can_read_study
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services.prior_lookup import find_priors

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/studies", tags=["Prior Studies"])


@router.get("/{study_uid}/priors", summary="이전 영상 검색")
async def get_prior_studies(
    request: Request,
    study_uid: str,
    max_results: int = Query(10, ge=1, le=50),
    same_modality: bool = Query(False, description="같은 모달리티만"),
    user: User = Depends(ReportReadRoles),
    db: AsyncSession = Depends(get_db),
):
    """동일 환자의 이전 검사를 자동으로 검색합니다.

    현재 스터디의 PatientID를 기반으로 Orthanc에서 동일 환자의
    다른 스터디를 검색하여 날짜순으로 반환합니다.

    사용 예: 뷰어에서 좌(현재)/우(이전) 비교 판독

    RBAC: 리포트 열람과 동일 스코프 — ADMIN/RAD/RESIDENT는 전체, PHYSICIAN은 본인 의뢰
    study만(referring/requesting 매칭). RESEARCHER/TECH 제외 — PatientID·검사이력 PHI 차단.
    """
    if not await _can_read_study(db, user, study_uid):
        raise HTTPException(403, "본인이 의뢰한 검사만 조회할 수 있습니다")

    orthanc = request.app.state.http_client

    try:
        result = await find_priors(orthanc, study_uid, max_results, same_modality)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Failed to get study info: {e}")
        raise HTTPException(500, "Failed to retrieve study information")

    result["total"] = len(result["priors"])
    return result


@router.get("/{study_uid}/compare-url", summary="비교 뷰어 URL 생성")
async def get_compare_url(
    request: Request,
    study_uid: str,
    prior_uid: str = Query(..., description="비교할 이전 스터디 UID"),
    user: User = Depends(get_current_user),
):
    """현재 + 이전 스터디를 나란히 볼 수 있는 뷰어 URL을 생성합니다."""
    return {
        "compare_url": f"/werub-viewer/viewer?StudyInstanceUIDs={study_uid}&StudyInstanceUIDs={prior_uid}",
        "current_uid": study_uid,
        "prior_uid": prior_uid,
    }
