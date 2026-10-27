"""Emergency department view — urgent studies first, simplified for ER physicians."""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import ClinicalPHIReadRoles, get_current_user
from app.models.report import Report, ReportStatus
from app.models.user import User

router = APIRouter(prefix="/api/v1/emergency", tags=["응급"])


@router.get("/board", summary="응급 영상 보드")
async def emergency_board(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ClinicalPHIReadRoles)],
    hours: int = Query(24, ge=1, le=72, description="조회 기간 (시간)"),
):
    """응급실 전용 영상 보드.

    - 긴급/STAT 우선 정렬
    - 판독 대기 시간 표시
    - 판독 완료 시 impression 요약 포함
    """
    client = request.app.state.http_client

    # Get recent studies from Orthanc
    resp = await client.post("/tools/find", json={
        "Level": "Study",
        "Query": {},
        "Expand": True,
        "Limit": 100,
        "RequestedTags": ["ModalitiesInStudy"],   # MainDicomTags엔 없음 → RequestedTags로만 채워짐
    })
    if resp.status_code != 200:
        return {"board": [], "total": 0, "urgent_count": 0, "pending_count": 0}

    orthanc_studies = resp.json()

    # Reports for the studies on the board only (F8: 전체 Report 테이블 언바운드 로드 제거)
    board_uids = [
        s.get("MainDicomTags", {}).get("StudyInstanceUID", "")
        for s in orthanc_studies
    ]
    board_uids = [u for u in board_uids if u]
    reports = {}
    if board_uids:
        rpt_result = await db.execute(
            select(Report).where(Report.study_instance_uid.in_(board_uids))
        )
        for r in rpt_result.scalars().all():
            # Keep highest priority report per study
            existing = reports.get(r.study_instance_uid)
            if not existing or _report_priority(r.status) > _report_priority(existing.status):
                reports[r.study_instance_uid] = r

    board = []
    for study in orthanc_studies:
        tags = study.get("MainDicomTags", {})
        patient = study.get("PatientMainDicomTags", {})
        study_uid = tags.get("StudyInstanceUID", "")

        report = reports.get(study_uid)
        read_status = report.status if report else "unread"
        urgency = report.urgency if report and report.urgency else "normal"

        # Calculate wait time
        wait_minutes = None
        study_date = tags.get("StudyDate", "")
        study_time = tags.get("StudyTime", "")
        if study_date:
            try:
                st = study_time[:6] if study_time else "000000"
                study_dt = datetime.strptime(f"{study_date}{st}", "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - study_dt).total_seconds() / 60
                wait_minutes = int(elapsed) if elapsed <= 1440 else None  # 24시간 이내만
            except Exception:
                pass

        board.append({
            "study_uid": study_uid,
            "patient_name": patient.get("PatientName", ""),
            "patient_id": patient.get("PatientID", ""),
            "modality": study.get("RequestedTags", {}).get("ModalitiesInStudy", ""),
            "study_description": tags.get("StudyDescription", ""),
            "study_date": study_date,
            "study_time": study_time,
            "read_status": read_status,
            "urgency": urgency,
            "wait_minutes": wait_minutes,
            "impression": (report.impression[:150] if report and report.impression else None),
            "reader": report.author_name if report else None,
            "signed_at": report.signed_at.isoformat() if report and report.signed_at else None,
            "viewer_url": f"/werub-viewer/viewer?StudyInstanceUIDs={study_uid}",
        })

    # Sort: urgent/stat first, then by wait time desc
    board.sort(key=lambda b: (
        0 if b["urgency"] in ("urgent", "stat") else 1,
        0 if b["read_status"] == "unread" else 1,
        -(b["wait_minutes"] or 0),
    ))

    return {
        "board": board,
        "total": len(board),
        "urgent_count": sum(1 for b in board if b["urgency"] in ("urgent", "stat")),
        "pending_count": sum(1 for b in board if b["read_status"] == "unread"),
    }


def _report_priority(status) -> int:
    s = status.value if hasattr(status, 'value') else str(status)
    return {"final": 3, "preliminary": 2, "draft": 1}.get(s, 0)
