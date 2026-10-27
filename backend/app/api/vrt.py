"""VRT server-render capability API (vrt-rendering §2.4).

The viewer reads /capability to decide whether to show server-render UI;
admins can re-test on demand (e.g. right after the planned direct GPU link
is installed) or override the verdict.
"""
import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.prefetch import _rate_limited
from app.core.database import get_db
from app.core.security import RequireRole, get_current_user
from app.models.user import Role, User
from app.services.vrt_capability import (
    CAP_KEY,
    OVERRIDE_KEY,
    merge_override,
    run_network_test,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/vrt", tags=["VRT 렌더링"])


class OverrideBody(BaseModel):
    interactive_supported: bool | None = None  # null = 자동 판정 복귀


class ProtocolEvent(BaseModel):
    study_instance_uid: str = Field(..., min_length=1, max_length=128)
    protocol_id: str = Field(..., min_length=1, max_length=64)


class PresetEvent(BaseModel):
    study_instance_uid: str = Field(..., min_length=1, max_length=128)
    preset_name: str = Field(..., min_length=1, max_length=64)


# sync def — FastAPI runs it in the threadpool; the probe takes ~5s on the
# current tunnel and must not block the event loop.
@router.post("/network-test", summary="AI 서버 네트워크 측정·지원 판정")
def network_test(user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False))):
    cap = run_network_test()
    logger.info(f"vrt network test by {user.username}: {cap}")
    return cap


@router.get("/capability", summary="서버 렌더 지원 여부 조회")
async def get_capability(
    request: Request,
    user: User = Depends(get_current_user),
):
    redis = request.app.state.redis
    raw = await redis.get(CAP_KEY)
    if not raw:
        return {"status": "not_tested", "batch_supported": False,
                "interactive_supported": False}
    capability = json.loads(raw)
    return {"status": "tested", **merge_override(capability, await redis.get(OVERRIDE_KEY))}


@router.post("/events/protocol", status_code=202, summary="3D 레이아웃 사용 텔레메트리")
async def protocol_event(
    body: ProtocolEvent,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(get_current_user),
):
    """뷰어가 3D 계열 행잉 프로토콜로 전환할 때 호출 — Phase 2(서버 GPU 렌더) 수요 근거."""
    if await _rate_limited(request, user.username):
        raise HTTPException(429, "Too many viewer events")
    await db.execute(text("""
        INSERT INTO vrt_metrics (id, study_instance_uid, username, protocol_id)
        VALUES (:id, :uid, :u, :p)
    """), {"id": str(uuid.uuid4()), "uid": body.study_instance_uid,
           "u": user.username, "p": body.protocol_id})
    await db.commit()
    return {"accepted": True}


@router.post("/events/preset", status_code=202, summary="VR 프리셋 사용 텔레메트리")
async def preset_event(
    body: PresetEvent,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(get_current_user),
):
    """뷰어에서 VR 프리셋을 적용할 때 호출 — 프리셋 큐레이션(C2) 수요 근거."""
    if await _rate_limited(request, user.username):
        raise HTTPException(429, "Too many viewer events")
    await db.execute(text("""
        INSERT INTO vrt_metrics (id, study_instance_uid, username, protocol_id, preset_name)
        VALUES (:id, :uid, :u, 'preset', :pn)
    """), {"id": str(uuid.uuid4()), "uid": body.study_instance_uid,
           "u": user.username, "pn": body.preset_name})
    await db.commit()
    return {"accepted": True}


@router.get("/metrics/summary", summary="3D 사용 통계 (수요 근거)")
async def metrics_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
):
    # preset 이벤트(protocol_id='preset')는 by_protocol 집계에서 분리한다
    rows = (await db.execute(text("""
        SELECT protocol_id, COUNT(*) AS uses, COUNT(DISTINCT username) AS users,
               COUNT(DISTINCT study_instance_uid) AS studies
        FROM vrt_metrics
        WHERE created_at > now() - interval '30 days' AND preset_name IS NULL
        GROUP BY protocol_id ORDER BY uses DESC
    """))).mappings().all()
    presets = (await db.execute(text("""
        SELECT preset_name, COUNT(*) AS uses, COUNT(DISTINCT username) AS users,
               COUNT(DISTINCT study_instance_uid) AS studies
        FROM vrt_metrics
        WHERE created_at > now() - interval '30 days' AND preset_name IS NOT NULL
        GROUP BY preset_name ORDER BY uses DESC
    """))).mappings().all()
    return {"days": 30, "by_protocol": [dict(r) for r in rows],
            "by_preset": [dict(r) for r in presets]}


@router.put("/override", summary="지원 여부 수동 오버라이드 (관리자)")
async def put_override(
    body: OverrideBody,
    request: Request,
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    redis = request.app.state.redis
    if body.interactive_supported is None:
        await redis.delete(OVERRIDE_KEY)
        logger.info(f"vrt override cleared by {user.username}")
        return {"override": None, "mode": "auto"}
    await redis.set(OVERRIDE_KEY, json.dumps({
        "interactive_supported": body.interactive_supported,
        "by": user.username,
    }))
    logger.info(f"vrt override set by {user.username}: {body.interactive_supported}")
    return {"override": {"interactive_supported": body.interactive_supported}, "mode": "manual"}
