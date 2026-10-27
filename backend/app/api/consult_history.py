"""Study별 협진 이력 통합 조회 API."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/v1/consult-history", tags=["협진 이력"])


@router.get("/{study_uid}", summary="Study별 협진 이력 통합 조회")
async def get_consult_history(
    study_uid: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """해당 Study의 외부 의뢰 + 세컨드 오피니언 + 피어 리뷰 이력을 시간순 반환."""
    items = []

    # External consults
    ec = await db.execute(text("""
        SELECT id, consult_type as type, institution_name, physician_name,
               reason, urgency, status, access_token,
               requested_by_name, requested_at, responded_at,
               external_findings, external_impression
        FROM external_consults WHERE study_instance_uid = :uid
        ORDER BY requested_at DESC
    """), {"uid": study_uid})
    for r in ec.mappings():
        d = dict(r)
        d["kind"] = "external_consult"
        d["label"] = {"external_read": "외부 판독", "subspecialty": "세부전공", "teleradiology": "원격판독"}.get(d.get("type", ""), "외부 의뢰")
        d["portal_url"] = f"/pacs-admin/consult-portal?token={d['access_token']}" if d.get("access_token") else None
        d.pop("access_token", None)
        items.append(d)

    # Second opinions
    so = await db.execute(text("""
        SELECT id, question, external_email, response, status, requester,
               created_at as requested_at, responded_at, access_token
        FROM second_opinions WHERE study_instance_uid = :uid
        ORDER BY created_at DESC
    """), {"uid": study_uid})
    for r in so.mappings():
        d = dict(r)
        d["kind"] = "second_opinion"
        d["label"] = "세컨드 오피니언"
        d["requested_by_name"] = d.pop("requester", None)
        d["reason"] = d.pop("question", None)
        d["portal_url"] = f"/pacs-admin/consult-portal?token={d['access_token']}" if d.get("access_token") else None
        d.pop("access_token", None)
        items.append(d)

    # Peer reviews
    pr = await db.execute(text("""
        SELECT id, original_reader, reviewer, agreement, comment,
               status, assigned_at as requested_at, completed_at as responded_at
        FROM peer_reviews WHERE study_instance_uid = :uid
        ORDER BY assigned_at DESC
    """), {"uid": study_uid})
    for r in pr.mappings():
        d = dict(r)
        d["kind"] = "peer_review"
        d["label"] = "피어 리뷰"
        d["requested_by_name"] = d.pop("original_reader", None)
        d["physician_name"] = d.pop("reviewer", None)
        items.append(d)

    # Sort by time desc
    items.sort(key=lambda x: str(x.get("requested_at", "")), reverse=True)

    return {
        "study_uid": study_uid,
        "total": len(items),
        "items": items,
    }
