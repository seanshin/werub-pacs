"""HospitalRun Integration API.

Endpoints for syncing patients, orders, and reports between
HospitalRun (EMR) and OpenPACS (PACS).
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import ClinicalPHIReadRoles, RequireRole, get_current_user
from app.models.user import Role, User
from app.services.hospitalrun_sync import HospitalRunSyncService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/hospitalrun", tags=["HospitalRun 연동"])


@router.get("/patients/search", summary="HospitalRun 환자 검색")
async def search_hr_patients(
    q: str = Query(..., min_length=1, description="환자명 또는 MRN"),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
):
    """HospitalRun DB에서 환자를 직접 검색합니다.

    기존 환자와 DICOM PatientID를 매칭할 때 사용합니다.
    """
    service = HospitalRunSyncService()
    try:
        patients = await service.search_hr_patients(query=q, limit=limit)
        return {"patients": patients, "total": len(patients)}
    except Exception as e:
        logger.error(f"HR patient search failed: {e}")
        raise HTTPException(503, f"HospitalRun DB 연결 실패: {str(e)[:100]}")


@router.get("/patients/{patient_id}", summary="HospitalRun 환자 상세")
async def get_hr_patient(
    patient_id: str,
    user: User = Depends(get_current_user),
):
    """HospitalRun 환자 상세 정보를 조회합니다."""
    service = HospitalRunSyncService()
    try:
        patient = await service.get_hr_patient(patient_id=patient_id)
        if not patient:
            raise HTTPException(404, "HospitalRun 환자를 찾을 수 없습니다")
        return patient
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(503, f"HospitalRun DB 연결 실패: {str(e)[:100]}")


@router.get("/orders/pending", summary="대기 중인 영상검사 오더")
async def get_pending_orders(
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(ClinicalPHIReadRoles),
):
    """HospitalRun의 대기 중인 영상검사(RADIOLOGY) 오더를 조회합니다.

    상태: ORDERED, RECEIVED, IN_PROGRESS
    우선순위: STAT > URGENT > ROUTINE 순
    """
    service = HospitalRunSyncService()
    try:
        orders = await service.get_pending_imaging_orders(limit=limit)
        return {"orders": orders, "total": len(orders)}
    except Exception as e:
        logger.error(f"HR order fetch failed: {e}")
        raise HTTPException(503, f"HospitalRun DB 연결 실패: {str(e)[:100]}")


class ReportSyncRequest(BaseModel):
    order_id: str
    patient_id: str
    finding: str
    impression: str
    modality: str = "CR"
    radiologist_id: Optional[str] = None


@router.post("/reports/sync", summary="판독 결과 → HospitalRun 동기화")
async def sync_report_to_hr(
    request: ReportSyncRequest,
    # 판독 리포트를 HIS로 전송 = 외부 반출. v12.3이 반출을 BTG 차단으로 못박았다.
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False)),
):
    """OpenPACS 판독 리포트를 HospitalRun imaging_results에 동기화합니다.

    판독의가 리포트를 서명하면 자동으로 호출됩니다.
    - imaging_results 테이블에 finding/impression 저장
    - orders 테이블 상태를 COMPLETED로 변경
    """
    service = HospitalRunSyncService()
    try:
        result = await service.sync_report_to_hr(
            order_id=request.order_id,
            patient_id=request.patient_id,
            finding=request.finding,
            impression=request.impression,
            modality=request.modality,
            radiologist_id=request.radiologist_id,
        )
        logger.info(f"Report synced to HR: order={request.order_id}")
        return result
    except Exception as e:
        logger.error(f"HR report sync failed: {e}")
        raise HTTPException(503, f"HospitalRun 동기화 실패: {str(e)[:100]}")


@router.get("/sync/stats", summary="동기화 통계")
async def get_sync_stats(
    user: User = Depends(get_current_user),
):
    """HospitalRun ↔ OpenPACS 동기화 현황을 조회합니다."""
    service = HospitalRunSyncService()
    try:
        stats = await service.get_sync_stats()
        return stats
    except Exception as e:
        raise HTTPException(503, f"HospitalRun DB 연결 실패: {str(e)[:100]}")
