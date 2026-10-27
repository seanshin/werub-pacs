"""Reading report API endpoints."""
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from app.api.audit import AuditLogger, _log_audit_entry
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from pydantic import BaseModel
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import RequireRole, get_current_user
from app.models.report import Report, ReportStatus
from app.models.user import Role, User
from app.models.worklist import WorklistItem

# 식별 리포트(findings/impression/이름/MRN) 읽기 — RESEARCHER·TECHNOLOGIST 제외(P2 결정).
# RESIDENT는 RequireRole이 RADIOLOGIST로 승격해 통과. PHYSICIAN은 아래 스코프로 본인 의뢰 환자만.
ReportReadRoles = RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.PHYSICIAN)


def _is_physician_only(user) -> bool:
    return str(getattr(user, "role", "")).upper() == "PHYSICIAN"


def _physician_pname(user) -> str:
    name = (getattr(user, "full_name", None) or getattr(user, "username", None) or "").strip()
    # 이름 미해결 PHYSICIAN은 아무것도 매칭 안 됨(전체 노출 방지) — '%%' 금지.
    return f"%{name}%" if name else "\x00"


async def _can_read_study(db: AsyncSession, user, study_uid: str) -> bool:
    """PHYSICIAN은 worklist referring/requesting가 본인 이름과 매칭되는 study만. 그 외(ADMIN/RAD/RESIDENT) 전체."""
    if not _is_physician_only(user):
        return True
    res = await db.execute(text(
        "SELECT 1 FROM worklist_items WHERE study_instance_uid = :uid "
        "AND (referring_physician ILIKE :p OR requesting_physician ILIKE :p) LIMIT 1"
    ), {"uid": study_uid, "p": _physician_pname(user)})
    return res.first() is not None

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

LOCK_TIMEOUT_MINUTES = 30


class ReportCreate(BaseModel):
    study_instance_uid: str
    orthanc_study_id: str | None = None
    patient_id: str
    patient_name: str | None = None
    modality: str | None = None
    study_date: str | None = None
    study_description: str | None = None
    accession_number: str | None = None
    template_id: str | None = None
    clinical_info: str | None = None
    findings: str | None = None
    impression: str | None = None
    recommendation: str | None = None
    urgency: str | None = "normal"
    ai_findings: dict | None = None


class ReportUpdate(BaseModel):
    clinical_info: str | None = None
    findings: str | None = None
    impression: str | None = None
    recommendation: str | None = None
    urgency: str | None = None
    structured_data: dict | None = None


def _to_response(r: Report) -> dict:
    return {
        "id": str(r.id),
        "study_instance_uid": r.study_instance_uid,
        "patient_id": r.patient_id,
        "patient_name": r.patient_name,
        "modality": r.modality,
        "study_date": r.study_date,
        "study_description": r.study_description,
        "accession_number": r.accession_number,
        "status": r.status,
        "urgency": r.urgency,
        "clinical_info": r.clinical_info,
        "findings": r.findings,
        "impression": r.impression,
        "recommendation": r.recommendation,
        "template_id": r.template_id,
        "author_name": r.author_name,
        "signed_at": r.signed_at.isoformat() if r.signed_at else None,
        "signed_by_name": r.signed_by_name,
        "locked_by_name": r.locked_by_name,
        "locked_at": r.locked_at.isoformat() if r.locked_at else None,
        "preliminary_by_name": r.preliminary_by_name,
        "preliminary_at": r.preliminary_at.isoformat() if r.preliminary_at else None,
        "preliminary_content": r.preliminary_content,
        "ai_findings": r.ai_findings,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


def _check_lock(report: Report, user: User):
    """Check if report is locked by another user."""
    if report.locked_by_id and report.locked_by_id != user.id:
        if report.locked_at:
            elapsed = (datetime.now(timezone.utc) - report.locked_at).total_seconds() / 60
            if elapsed < LOCK_TIMEOUT_MINUTES:
                raise ForbiddenError(
                    message=f"Report is locked by {report.locked_by_name} ({int(elapsed)}m ago)"
                )


@router.get("")
async def list_reports(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ReportReadRoles)],
    study_uid: str | None = Query(None),
    patient_id: str | None = Query(None),
    report_status: ReportStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List reports with filters."""
    query = select(Report).order_by(Report.created_at.desc())
    if study_uid:
        query = query.where(Report.study_instance_uid == study_uid)
    if patient_id:
        query = query.where(Report.patient_id == patient_id)
    if report_status:
        query = query.where(Report.status == report_status)
    # PHYSICIAN은 본인 의뢰(worklist referring/requesting) study만 — IDOR/PHI 차단.
    if _is_physician_only(user):
        query = query.where(Report.study_instance_uid.in_(
            select(WorklistItem.study_instance_uid).where(
                WorklistItem.referring_physician.ilike(_physician_pname(user))
                | WorklistItem.requesting_physician.ilike(_physician_pname(user))
            )
        ))

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar()
    result = await db.execute(query.offset(offset).limit(limit))
    reports = result.scalars().all()

    return {"total": total, "count": len(reports), "results": [_to_response(r) for r in reports]}


@router.get("/next-unread", summary="다음 미판독 Study")
async def next_unread_study(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],  # 판독 워크플로 — 연구/기사 제외
    current_study_uid: str | None = Query(None, description="현재 Study UID (이후 검사 반환)"),
    modality: str | None = Query(None, description="모달리티 필터 (CT, MR 등)"),
):
    """다음 미판독 Study의 UID를 반환합니다.

    판독의가 N키를 눌러 다음 미판독 검사로 이동할 때 사용.
    워크리스트에서 가장 오래된 미판독 Study를 찾아 반환합니다.
    """
    client = request.app.state.http_client

    # Get all studies from Orthanc (recent first)
    resp = await client.post("/tools/find", json={
        "Level": "Study",
        "Query": {"ModalitiesInStudy": modality or ""},
        "Expand": True,
        "Limit": 200,
    })
    if resp.status_code != 200:
        return {"study_uid": None, "message": "Orthanc 조회 실패"}

    orthanc_studies = resp.json()

    # Get all reported study UIDs
    result = await db.execute(
        select(Report.study_instance_uid).where(Report.status.in_(["final", "draft", "preliminary"]))
    )
    reported_uids = {row[0] for row in result.all()}

    # Find next unread (oldest first)
    candidates = []
    for s in orthanc_studies:
        uid = s.get("MainDicomTags", {}).get("StudyInstanceUID", "")
        date = s.get("MainDicomTags", {}).get("StudyDate", "")
        if uid and uid not in reported_uids:
            candidates.append({"uid": uid, "date": date})

    # Sort by date ascending (oldest unread first)
    candidates.sort(key=lambda x: x["date"])

    # If current_study_uid provided, find the next one after it
    if current_study_uid and candidates:
        found = False
        for c in candidates:
            if found:
                return {
                    "study_uid": c["uid"],
                    "viewer_url": f"/werub-viewer/viewer?StudyInstanceUIDs={c['uid']}",
                    "remaining": len(candidates) - 1,
                }
            if c["uid"] == current_study_uid:
                found = True
        # If current was last or not found, return first candidate
        if candidates:
            return {
                "study_uid": candidates[0]["uid"],
                "viewer_url": f"/werub-viewer/viewer?StudyInstanceUIDs={candidates[0]['uid']}",
                "remaining": len(candidates),
            }

    # No current — return first unread
    if candidates:
        return {
            "study_uid": candidates[0]["uid"],
            "viewer_url": f"/werub-viewer/viewer?StudyInstanceUIDs={candidates[0]['uid']}",
            "remaining": len(candidates),
        }

    return {"study_uid": None, "message": "미판독 검사가 없습니다", "remaining": 0}


@router.get("/status-batch")
async def batch_report_status(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ReportReadRoles)],
    study_uids: str = Query(..., description="Comma-separated StudyInstanceUIDs"),
):
    """Get report status for multiple studies in one call.

    Returns a map of study_uid → status (final/draft/preliminary or null).
    Optimized for Study List view — returns only the highest-priority status per study.
    """
    uid_list = [u.strip() for u in study_uids.split(",") if u.strip()]
    if not uid_list or len(uid_list) > 200:
        return {"status_map": {}}

    query = (
        select(Report.study_instance_uid, Report.status)
        .where(Report.study_instance_uid.in_(uid_list))
        .order_by(Report.created_at.desc())
    )
    result = await db.execute(query)
    rows = result.all()

    # Priority: final > draft > preliminary
    priority = {"final": 3, "draft": 2, "preliminary": 1}
    status_map = {}
    for uid, st in rows:
        if uid not in status_map or priority.get(st, 0) > priority.get(status_map[uid], 0):
            status_map[uid] = st

    return {"status_map": status_map}


@router.post("", status_code=status.HTTP_201_CREATED)
@AuditLogger.log("REPORT_CREATED", "Report")
async def create_report(
    body: ReportCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """Create a new draft report. Radiologist or Admin only."""
    report = Report(
        **body.model_dump(),
        author_id=user.id,
        author_name=user.full_name,
        status=ReportStatus.DRAFT,
        locked_by_id=user.id,
        locked_by_name=user.full_name,
        locked_at=datetime.now(timezone.utc),
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return _to_response(report)


@router.get("/{report_id}")
async def get_report(
    report_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(ReportReadRoles)],
):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise NotFoundError("Report", str(report_id))
    # PHYSICIAN은 본인 의뢰 study만 — 임의 report_id로 타 환자 열람 차단(IDOR).
    if not await _can_read_study(db, user, report.study_instance_uid):
        raise ForbiddenError("본인이 의뢰한 환자의 리포트만 열람할 수 있습니다.")
    return _to_response(report)


@router.patch("/{report_id}")
@AuditLogger.log("REPORT_UPDATED", "Report")
async def update_report(
    report_id: UUID,
    body: ReportUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """Update report content. Must be draft or preliminary."""
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise NotFoundError("Report", str(report_id))
    if report.status in (ReportStatus.FINAL, ReportStatus.CANCELLED):
        raise ValidationError(f"Cannot edit report in '{report.status}' status")

    _check_lock(report, user)

    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(report, key, value)

    report.locked_by_id = user.id
    report.locked_by_name = user.full_name
    report.locked_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(report)
    return _to_response(report)


@router.post("/{report_id}/sign")
@AuditLogger.log("REPORT_SIGNED", "Report")
async def sign_report(
    report_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.RADIOLOGIST, Role.ADMIN))],
    as_preliminary: bool = Query(False),
):
    """Sign (finalize) a report."""
    # 행잠금 — 동시 2명 서명/중복제출 시 lost update(서명자 덮어쓰기) 방지(법적 의료기록)
    result = await db.execute(select(Report).where(Report.id == report_id).with_for_update())
    report = result.scalar_one_or_none()
    if not report:
        raise NotFoundError("Report", str(report_id))

    # 이미 최종/취소된 보고서 재서명 차단(재서명=서명자 덮어쓰기+중복알림)
    if report.status == ReportStatus.FINAL:
        raise ValidationError("이미 최종 서명된 보고서입니다")
    if report.status == ReportStatus.CANCELLED:
        raise ValidationError("취소된 보고서는 서명할 수 없습니다")

    if not report.findings or not report.impression:
        raise ValidationError("Findings and impression are required before signing")

    # RESIDENT role: force preliminary signing (cannot finalize directly)
    if Role(user.role) == Role.RESIDENT and not as_preliminary:
        as_preliminary = True

    if as_preliminary:
        report.status = ReportStatus.PRELIMINARY
        report.preliminary_by_id = user.id
        report.preliminary_by_name = user.full_name
        report.preliminary_at = datetime.now(timezone.utc)
    else:
        report.status = ReportStatus.FINAL
    report.signed_at = datetime.now(timezone.utc)
    report.signed_by_id = user.id
    report.signed_by_name = user.full_name
    report.locked_by_id = None
    report.locked_by_name = None
    report.locked_at = None

    await db.commit()
    await db.refresh(report)

    # Create notification
    from app.api.notification import create_notification

    if as_preliminary:
        # Notify attending radiologists that a preliminary read is ready
        await create_notification(
            db,
            type="preliminary_ready",
            title=f"예비 판독 대기: {report.patient_name or report.patient_id}",
            message=f"{report.modality or ''} {report.study_description or ''} — 예비 판독 by {user.full_name}",
            urgency="normal",
            target_role="radiologist",
            study_instance_uid=report.study_instance_uid,
            patient_id=report.patient_id,
            action_url=f"/viewer/?StudyInstanceUIDs={report.study_instance_uid}",
        )

    urgency = "critical" if report.urgency == "urgent" else "normal"
    await create_notification(
        db,
        type="report_ready",
        title=f"판독 완료: {report.patient_name or report.patient_id}",
        message=f"{report.modality or ''} {report.study_description or ''} — {report.impression[:100] if report.impression else ''}",
        urgency=urgency,
        target_role="physician",
        study_instance_uid=report.study_instance_uid,
        patient_id=report.patient_id,
        action_url=f"/viewer/?StudyInstanceUIDs={report.study_instance_uid}",
    )

    # WebSocket broadcast — especially for urgent findings
    try:
        from app.api.websocket import manager as ws_manager
        await ws_manager.broadcast({
            "type": "report_signed",
            "study_uid": report.study_instance_uid,
            "patient_id": report.patient_id,
            "patient_name": report.patient_name,
            "status": report.status.value if hasattr(report.status, 'value') else str(report.status),
            "urgency": report.urgency,
            "impression": (report.impression or "")[:200],
            "signed_by": report.signed_by_name,
            "is_urgent": report.urgency == "urgent",
        })
    except Exception:
        pass  # WebSocket broadcast is non-critical

    return _to_response(report)


@router.post("/{report_id}/finalize")
@AuditLogger.log("REPORT_FINALIZED", "Report")
async def finalize_report(
    report_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.RADIOLOGIST, Role.ADMIN))],
    body: ReportUpdate | None = None,
):
    """Finalize a preliminary report. Attending radiologist reviews and confirms."""
    # Residents cannot finalize — only attending radiologists or admins
    if Role(user.role) == Role.RESIDENT:
        raise ForbiddenError(message="Residents cannot finalize reports. Request attending review.")

    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise NotFoundError("Report", str(report_id))

    if report.status != ReportStatus.PRELIMINARY:
        raise ValidationError("Only preliminary reports can be finalized")

    # Backup preliminary content
    report.preliminary_content = {
        "findings": report.findings,
        "impression": report.impression,
        "recommendation": report.recommendation,
        "backed_up_at": datetime.now(timezone.utc).isoformat(),
    }

    # Apply attending's modifications if provided
    if body:
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(report, key, value)

    # Finalize
    report.status = ReportStatus.FINAL
    report.signed_at = datetime.now(timezone.utc)
    report.signed_by_id = user.id
    report.signed_by_name = user.full_name
    report.locked_by_id = None
    report.locked_by_name = None
    report.locked_at = None

    await db.commit()
    await db.refresh(report)

    # Notify referring physician
    from app.api.notification import create_notification
    urgency = "critical" if report.urgency == "urgent" else "normal"
    await create_notification(
        db,
        type="report_ready",
        title=f"판독 완료: {report.patient_name or report.patient_id}",
        message=f"{report.modality or ''} {report.study_description or ''} — {report.impression[:100] if report.impression else ''}",
        urgency=urgency,
        target_role="physician",
        study_instance_uid=report.study_instance_uid,
        patient_id=report.patient_id,
        action_url=f"/viewer/?StudyInstanceUIDs={report.study_instance_uid}",
    )

    # WebSocket broadcast
    try:
        from app.api.websocket import manager as ws_manager
        await ws_manager.broadcast({
            "type": "report_finalized",
            "study_uid": report.study_instance_uid,
            "patient_id": report.patient_id,
            "patient_name": report.patient_name,
            "status": "final",
            "urgency": report.urgency,
            "signed_by": report.signed_by_name,
            "preliminary_by": report.preliminary_by_name,
        })
    except Exception:
        pass

    return _to_response(report)


@router.post("/{report_id}/addendum")
@AuditLogger.log("REPORT_ADDENDUM_CREATED", "Report")
async def create_addendum(
    report_id: UUID,
    body: ReportUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.RADIOLOGIST, Role.ADMIN))],
):
    """Create an addendum to a finalized report."""
    result = await db.execute(select(Report).where(Report.id == report_id))
    parent = result.scalar_one_or_none()
    if not parent:
        raise NotFoundError("Report", str(report_id))
    if parent.status != ReportStatus.FINAL:
        raise ValidationError("Addendum can only be added to finalized reports")

    addendum = Report(
        study_instance_uid=parent.study_instance_uid,
        orthanc_study_id=parent.orthanc_study_id,
        patient_id=parent.patient_id,
        patient_name=parent.patient_name,
        modality=parent.modality,
        study_date=parent.study_date,
        study_description=parent.study_description,
        accession_number=parent.accession_number,
        status=ReportStatus.ADDENDUM,
        author_id=user.id,
        author_name=user.full_name,
        parent_report_id=parent.id,
        findings=body.findings,
        impression=body.impression,
        recommendation=body.recommendation,
    )
    db.add(addendum)
    await db.commit()
    await db.refresh(addendum)
    return _to_response(addendum)


@router.post("/{report_id}/unlock")
async def unlock_report(
    report_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    # 확정 리포트 잠금 해제 = 법적 의무기록 수정 경로. 응급 "열람"과 무관한 관리 행위라
    # BTG로는 못 한다(v12.3 정책: 관리/반출/삭제는 allow_btg=False).
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False))],
):
    """Release edit lock on a report."""
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise NotFoundError("Report", str(report_id))

    if report.locked_by_id != user.id and Role(user.role) != Role.ADMIN:
        raise ForbiddenError("Only lock owner or admin can unlock")

    # ★전후 대조는 setattr 전에 스냅샷(v13.38 규칙). 여기서 남길 가치가 있는 것은
    #   "누가 남의 잠금을 풀었나"다 — 형제 EP(CREATED/UPDATED/SIGNED/FINALIZED/
    #   ADDENDUM)는 모두 감사되는데 정작 **확정 의무기록을 다시 열 수 있는** 이 경로만
    #   무기록이었다(v13.44에서 BTG까지 차단한 민감도인데 기록이 없었다).
    prev_owner = report.locked_by_name
    prev_owner_id = str(report.locked_by_id) if report.locked_by_id else None
    report_status = report.status.name if hasattr(report.status, "name") else str(report.status)
    study_uid = report.study_instance_uid
    patient_id = report.patient_id

    report.locked_by_id = None
    report.locked_by_name = None
    report.locked_at = None
    await db.commit()

    await _log_audit_entry(
        db=db, operation="REPORT_UNLOCKED", resource_type="Report", status="SUCCESS",
        user_id=str(user.id), username=user.username,
        resource_id=str(report_id),
        study_instance_uid=study_uid,
        patient_id=patient_id,
        details={
            "report_status": report_status,      # 확정본이었는지가 핵심 맥락
            "previous_lock_owner": prev_owner,
            "previous_lock_owner_id": prev_owner_id,
            "unlocked_other_users_lock": prev_owner_id is not None
            and prev_owner_id != str(user.id),
        },
    )
    return {"status": "unlocked"}
