"""Report comparison — diff between current and prior reports."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import RequireRole
from app.models.report import Report
from app.models.user import Role, User

router = APIRouter(prefix="/api/v1/reports", tags=["리포트 비교"])


@router.get("/compare", summary="리포트 비교 (현재 vs 이전)")
async def compare_reports(
    study_uid: str = Query(..., description="현재 Study UID"),
    patient_id: str = Query(..., description="환자번호"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
):
    """같은 환자의 현재/이전 리포트를 비교합니다.

    동일 환자의 가장 최근 2개 판독 리포트를 반환하여
    소견 변화를 추적할 수 있습니다.
    """
    result = await db.execute(
        select(Report)
        .where(Report.patient_id == patient_id, Report.status == 'final')
        .order_by(Report.signed_at.desc())
        .limit(5)
    )
    reports = result.scalars().all()

    current = None
    prior = None
    for r in reports:
        if r.study_instance_uid == study_uid:
            current = r
        elif current and not prior:
            prior = r

    if not current and reports:
        current = reports[0]
        prior = reports[1] if len(reports) > 1 else None

    def to_dict(r):
        if not r:
            return None
        return {
            "study_uid": r.study_instance_uid,
            "study_date": r.study_date,
            "modality": r.modality,
            "findings": r.findings,
            "impression": r.impression,
            "signed_by": r.signed_by_name,
            "signed_at": r.signed_at.isoformat() if r.signed_at else None,
        }

    # Simple diff: find changed lines
    changes = []
    if current and prior and current.findings and prior.findings:
        curr_lines = current.findings.split('\n')
        prev_lines = prior.findings.split('\n')
        for i, line in enumerate(curr_lines):
            if i < len(prev_lines):
                if line != prev_lines[i]:
                    changes.append({"type": "changed", "current": line, "prior": prev_lines[i]})
            else:
                changes.append({"type": "added", "current": line})
        for i in range(len(curr_lines), len(prev_lines)):
            changes.append({"type": "removed", "prior": prev_lines[i]})

    return {
        "current": to_dict(current),
        "prior": to_dict(prior),
        "changes": changes,
        "has_prior": prior is not None,
        "total_reports": len(reports),
    }
