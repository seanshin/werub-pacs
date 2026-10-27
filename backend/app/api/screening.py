"""Opportunistic AI screening API (opportunistic-ai feature).

Results list + stats (incl. AI-acceptance rate = governance gap-2 data source)
+ runtime config + reader ack/dismiss.
"""
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import RequireRole, get_current_user
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/screening", tags=["선제 AI 스크리닝"])

CONFIG_KEY = "pacs:screening:config"  # shared with services/opportunistic_screener.py


class ScreeningConfig(BaseModel):
    enabled: bool = True
    actionable_confidence: float = Field(0.85, ge=0, le=1)
    max_per_scan: int = Field(20, ge=1, le=200)
    modality_model: dict | None = None


class AckBody(BaseModel):
    dismissed: bool = False  # true = reader rejects the AI alert


@router.get("/results", summary="스크리닝 결과 목록")
async def list_results(
    db: Annotated[AsyncSession, Depends(get_db)],
    actionable_only: bool = Query(False),
    modality: str | None = Query(None),
    hours: int = Query(168, ge=1, le=2160),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.RESIDENT)),
):
    q = """SELECT study_instance_uid, modality, model_name, status, is_actionable,
                  is_critical, max_confidence, notified, acknowledged, dismissed,
                  screened_at, completed_at
           FROM ai_screening_results
           WHERE screened_at > now() - make_interval(hours => :h)"""
    p = {"h": hours, "lim": limit}
    if actionable_only:
        q += " AND is_actionable = true"
    if modality:
        q += " AND modality = :mod"; p["mod"] = modality.upper()
    q += " ORDER BY screened_at DESC LIMIT :lim"
    rows = (await db.execute(text(q), p)).mappings().all()
    return {"results": [dict(r) for r in rows]}


@router.get("/stats", summary="스크리닝 통계 (수용률 포함)")
async def stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    hours: int = Query(168, ge=1, le=2160),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
):
    overall = (await db.execute(text("""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE status='done') AS done,
               COUNT(*) FILTER (WHERE status='skipped') AS skipped,
               COUNT(*) FILTER (WHERE status='failed') AS failed,
               COUNT(*) FILTER (WHERE is_actionable) AS actionable,
               COUNT(*) FILTER (WHERE notified) AS notified,
               COUNT(*) FILTER (WHERE acknowledged) AS acknowledged,
               COUNT(*) FILTER (WHERE dismissed) AS dismissed
        FROM ai_screening_results
        WHERE screened_at > now() - make_interval(hours => :h)
    """), {"h": hours})).mappings().first()
    by_modality = (await db.execute(text("""
        SELECT modality, COUNT(*) AS total,
               COUNT(*) FILTER (WHERE is_actionable) AS actionable
        FROM ai_screening_results
        WHERE screened_at > now() - make_interval(hours => :h) AND status='done'
        GROUP BY modality ORDER BY total DESC
    """), {"h": hours})).mappings().all()

    notified = overall["notified"] or 0
    responded = (overall["acknowledged"] or 0) + (overall["dismissed"] or 0)
    return {
        "hours": hours,
        "total": overall["total"], "done": overall["done"],
        "skipped": overall["skipped"], "failed": overall["failed"],
        "actionable": overall["actionable"], "notified": notified,
        # AI-acceptance metric (governance gap-2): of alerted, how many accepted
        "acceptance": {
            "acknowledged": overall["acknowledged"], "dismissed": overall["dismissed"],
            "response_rate": round(responded / notified, 3) if notified else None,
            "acceptance_rate": round((overall["acknowledged"] or 0) / responded, 3) if responded else None,
        },
        "by_modality": [dict(r) for r in by_modality],
    }


@router.post("/results/{study_uid}/ack", summary="스크리닝 알림 수용/기각")
async def ack_result(
    study_uid: str,
    body: AckBody,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.RESIDENT)),
):
    # 행 존재 확인(404 구분) + actor 기록·교차사용자 덮어쓰기 방지(거버넌스 수용률 신뢰)
    exists = (await db.execute(text(
        "SELECT ack_by FROM ai_screening_results WHERE study_instance_uid = :uid"
    ), {"uid": study_uid})).first()
    if exists is None:
        raise HTTPException(404, "Screening result not found")
    # 이미 다른 판독의가 응답한 결정은 덮어쓰기 금지(본인 재변경은 허용)
    res = await db.execute(text("""
        UPDATE ai_screening_results
        SET acknowledged = :ack, dismissed = :dis, ack_at = now(), ack_by = :by
        WHERE study_instance_uid = :uid AND (ack_by IS NULL OR ack_by = :by)
    """), {"ack": not body.dismissed, "dis": body.dismissed, "uid": study_uid, "by": user.username})
    await db.commit()
    if res.rowcount == 0:
        raise HTTPException(409, "이미 다른 판독의가 응답한 스크리닝 결과입니다")
    return {"study_instance_uid": study_uid, "dismissed": body.dismissed, "ack_by": user.username}


@router.get("/config", summary="스크리닝 설정 조회")
async def get_config(request: Request, user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False))):
    from app.services.opportunistic_screener import get_screening_config
    return get_screening_config()


@router.put("/config", summary="스크리닝 설정 변경")
async def put_config(
    body: ScreeningConfig,
    request: Request,
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        await request.app.state.redis.set(CONFIG_KEY, json.dumps(payload))
    except Exception as e:
        raise HTTPException(503, f"Config store unavailable: {e}")
    logger.info(f"screening config updated by {user.username}: {payload}")
    return payload
