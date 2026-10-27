"""외부 판독 의뢰 API — 외부 기관/전문의에게 판독 위탁."""
import logging
import secrets
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.security import RequireRole, get_current_user
from app.models.user import Role, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/external-consult", tags=["외부 판독 의뢰"])


class ConsultRequest(BaseModel):
    study_instance_uid: str
    report_id: str | None = None
    consult_type: str = "external_read"  # external_read, subspecialty, teleradiology
    institution_name: str | None = None
    physician_name: str | None = None
    physician_email: str | None = None
    reason: str
    clinical_info: str | None = None
    urgency: str = "routine"  # routine, urgent, stat
    share_method: str = "link"  # link, dicom_send, cd


class ConsultResponse(BaseModel):
    external_findings: str | None = None
    external_impression: str | None = None


@router.post("", summary="외부 판독 의뢰 생성", status_code=status.HTTP_201_CREATED)
async def create_consult(
    body: ConsultRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    # 외부 이메일+DICOM 반출 — BTG 우회 차단.
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False))],
):
    """외부 기관에 판독을 의뢰합니다. 영상 공유 링크가 자동 생성됩니다."""
    # Auto-create share link (skip if table doesn't exist)
    share_link_id = None
    if body.share_method == "link":
        try:
            check = await db.execute(text("SELECT 1 FROM information_schema.tables WHERE table_name='share_links'"))
            if check.first():
                link_result = await db.execute(text("""
                    INSERT INTO share_links (study_instance_uid, created_by, expires_hours, access_level)
                    VALUES (:uid, :user, 168, 'view')
                    RETURNING id, token
                """), {"uid": body.study_instance_uid, "user": user.username})
                link_row = link_result.mappings().first()
                if link_row:
                    share_link_id = str(link_row["id"])
        except Exception:
            await db.rollback()

    access_token = secrets.token_urlsafe(32)

    result = await db.execute(text("""
        INSERT INTO external_consults
            (study_instance_uid, report_id, consult_type, institution_name,
             physician_name, physician_email, reason, clinical_info,
             urgency, share_method, share_link_id,
             requested_by_id, requested_by_name, status, access_token)
        VALUES
            (:uid, :rid, :ctype, :inst, :phys, :email, :reason, :cinfo,
             :urgency, :smethod, :slid,
             :req_id, :req_name, 'requested', :atoken)
        RETURNING id
    """), {
        "uid": body.study_instance_uid, "rid": body.report_id,
        "ctype": body.consult_type, "inst": body.institution_name,
        "phys": body.physician_name, "email": body.physician_email,
        "reason": body.reason, "cinfo": body.clinical_info,
        "urgency": body.urgency, "smethod": body.share_method,
        "slid": share_link_id,
        "req_id": str(user.id), "req_name": user.full_name,
        "atoken": access_token,
    })
    await db.commit()
    row = result.mappings().first()

    # Notification
    try:
        from app.api.notification import create_notification
        await create_notification(
            db, type="external_consult",
            title=f"외부 판독 의뢰: {body.institution_name or '외부 기관'}",
            message=f"{body.reason[:100]}",
            urgency="normal" if body.urgency == "routine" else body.urgency,
            target_role="radiologist",
            study_instance_uid=body.study_instance_uid,
        )
    except Exception:
        pass

    portal_url = f"/pacs-admin/consult-portal?token={access_token}"

    # Send email notification to external physician
    if body.physician_email:
        from app.services.email_service import send_consult_email
        send_consult_email(
            to_email=body.physician_email,
            subject=f"[WeRU.B PACS] 판독 의뢰 — {body.reason[:50]}",
            portal_url=portal_url,
            consult_type=body.consult_type,
            requester_name=user.full_name,
            reason=body.reason,
            urgency=body.urgency,
        )

    # DICOM send if requested
    if body.share_method == "dicom_send":
        try:
            orthanc = request.app.state.http_client if hasattr(request.app.state, 'http_client') else None
            if orthanc and body.institution_name:
                # Find study in Orthanc
                find_resp = await orthanc.post("/tools/find", json={
                    "Level": "Study", "Query": {"StudyInstanceUID": body.study_instance_uid}
                })
                study_ids = find_resp.json() if find_resp.status_code == 200 else []
                if study_ids:
                    # Try to send to modality (institution name as AE Title)
                    ae_title = body.institution_name.replace(" ", "")[:16].upper()
                    await orthanc.post(f"/modalities/{ae_title}/store", json=study_ids[0])
                    logger.info(f"DICOM sent to {ae_title}: {body.study_instance_uid}")
        except Exception as e:
            logger.warning(f"DICOM send failed: {e}")

    return {
        "id": str(row["id"]),
        "study_instance_uid": body.study_instance_uid,
        "status": "requested",
        "share_link_id": share_link_id,
        "portal_url": portal_url,
        "access_token": access_token,
        "email_sent": bool(body.physician_email),
    }


@router.get("", summary="외부 판독 의뢰 목록")
async def list_consults(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
):
    """외부 판독 의뢰 목록을 조회합니다."""
    query = """
        SELECT id, study_instance_uid, consult_type, institution_name,
               physician_name, physician_email, reason, urgency,
               status, requested_by_name, requested_at, responded_at,
               external_findings, external_impression
        FROM external_consults
    """
    params: dict = {}
    if status_filter:
        query += " WHERE status = :status"
        params["status"] = status_filter
    query += " ORDER BY requested_at DESC LIMIT :limit"
    params["limit"] = limit

    result = await db.execute(text(query), params)
    rows = [dict(r._mapping) for r in result]

    counts = await db.execute(text("""
        SELECT status, count(*) as cnt FROM external_consults GROUP BY status
    """))
    status_counts = {r._mapping["status"]: r._mapping["cnt"] for r in counts}

    return {"consults": rows, "total": len(rows), "by_status": status_counts}


@router.put("/{consult_id}/respond", summary="외부 판독 결과 입력")
async def respond_consult(
    consult_id: str,
    body: ConsultResponse,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """외부 판독 결과를 입력합니다."""
    result = await db.execute(text("""
        UPDATE external_consults
        SET external_findings = :findings, external_impression = :impression,
            status = 'completed', responded_at = NOW(), updated_at = NOW()
        WHERE id = :id AND status IN ('requested', 'in_progress')
        RETURNING id, study_instance_uid
    """), {
        "findings": body.external_findings,
        "impression": body.external_impression,
        "id": consult_id,
    })
    await db.commit()
    row = result.mappings().first()
    if not row:
        raise NotFoundError("ExternalConsult", consult_id)

    # Notify requester
    try:
        from app.api.notification import create_notification
        await create_notification(
            db, type="consult_completed",
            title="외부 판독 결과 도착",
            message=f"외부 판독이 완료되었습니다.",
            urgency="normal",
            target_role="radiologist",
            study_instance_uid=row["study_instance_uid"],
        )
    except Exception:
        pass

    return {"id": consult_id, "status": "completed"}


@router.put("/{consult_id}/cancel", summary="외부 판독 의뢰 취소")
async def cancel_consult(
    consult_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST))],
):
    """외부 판독 의뢰를 취소합니다."""
    result = await db.execute(text("""
        UPDATE external_consults SET status = 'cancelled', updated_at = NOW()
        WHERE id = :id AND status = 'requested'
        RETURNING id
    """), {"id": consult_id})
    await db.commit()
    row = result.mappings().first()
    if not row:
        raise NotFoundError("ExternalConsult", consult_id)
    return {"id": consult_id, "status": "cancelled"}
