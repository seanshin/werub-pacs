"""Predictive prefetch API (3d-ai-performance Track A).

- study-opened events from the viewer: the only reliable open signal, since
  DICOMweb traffic bypasses this backend (nginx -> Orthanc direct). The event
  doubles as instrumentation (load_ms baseline) and hit-marking for accuracy.
- stats / config for operations.
"""
import json
import logging
import uuid
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

router = APIRouter(prefix="/api/v1/prefetch", tags=["예측 프리페치"])

CONFIG_KEY = "pacs:prefetch:config"  # shared with services/prefetch_worker.py
EVENT_RATE_LIMIT = 30  # events per minute per user


class StudyOpenedEvent(BaseModel):
    study_instance_uid: str = Field(..., min_length=1, max_length=128)
    load_ms: int | None = Field(None, ge=0, le=600_000)


class LoadMeasuredEvent(BaseModel):
    study_instance_uid: str = Field(..., min_length=1, max_length=128)
    load_ms: int | None = Field(None, ge=0, le=600_000)            # first image rendered
    volume_complete_ms: int | None = Field(None, ge=0, le=600_000)  # full 3D volume loaded


class PrefetchConfig(BaseModel):
    enabled: bool = True
    next_n: int = Field(2, ge=0, le=10)
    prior_n: int = Field(1, ge=0, le=5)
    max_frames_per_study: int = Field(2000, ge=100, le=20000)


async def _rate_limited(request: Request, username: str) -> bool:
    """True if over the per-user event budget. Fail-open: this protects the
    prefetch queue, not auth — Redis being down must not break the viewer."""
    try:
        redis = request.app.state.redis
        key = f"pacs:prefetch:rl:{username}"
        n = await redis.incr(key)
        if n == 1:
            await redis.expire(key, 60)
        return n > EVENT_RATE_LIMIT
    except Exception:
        return False


@router.post("/events/study-opened", status_code=202, summary="뷰어 열람 시작 이벤트")
async def study_opened(
    body: StudyOpenedEvent,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(get_current_user),
):
    """뷰어(werub-ai)가 검사를 열 때 호출. 프리페치 계획을 발행하고,
    이 검사가 사전 워밍되었는지 대조하여 적중(hit)을 기록합니다."""
    if await _rate_limited(request, user.username):
        raise HTTPException(429, "Too many viewer events")

    uid = body.study_instance_uid

    # Hit-marking: any warm of this study in the last 24h counts once
    hit_row = (await db.execute(text("""
        UPDATE prefetch_history SET hit = true, hit_at = now(), open_load_ms = :lm
        WHERE id = (
            SELECT id FROM prefetch_history
            WHERE study_instance_uid = :uid AND hit = false
              AND warmed_at > now() - interval '24 hours'
            ORDER BY warmed_at DESC LIMIT 1
        )
        RETURNING id
    """), {"uid": uid, "lm": body.load_ms})).first()

    await db.execute(text("""
        INSERT INTO viewer_open_events (id, study_instance_uid, username, load_ms, was_prefetched)
        VALUES (:id, :uid, :u, :lm, :wp)
    """), {"id": str(uuid.uuid4()), "uid": uid, "u": user.username,
           "lm": body.load_ms, "wp": hit_row is not None})
    await db.commit()

    if settings.prefetch_enabled:
        try:
            from app.services.prefetch_worker import plan_prefetch
            plan_prefetch.delay(user.username, uid, "study_opened")
        except Exception as e:
            logger.warning(f"plan_prefetch enqueue failed: {e}")

    return {"accepted": True, "was_prefetched": hit_row is not None}


@router.post("/events/load-measured", status_code=202, summary="뷰어 로드 시간 보고")
async def load_measured(
    body: LoadMeasuredEvent,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(get_current_user),
):
    """첫 영상 렌더 완료 후 호출 — 직전 study-opened 이벤트에 로드 시간을 채웁니다.
    열람 이벤트(즉시 발사, 워밍 트리거)와 분리해 측정이 워밍을 지연시키지 않게 함."""
    if await _rate_limited(request, user.username):
        raise HTTPException(429, "Too many viewer events")

    # first-image render time: fill the most recent open row that lacks it
    if body.load_ms is not None:
        await db.execute(text("""
            UPDATE viewer_open_events SET load_ms = :lm
            WHERE id = (
                SELECT id FROM viewer_open_events
                WHERE study_instance_uid = :uid AND username = :u AND load_ms IS NULL
                  AND opened_at > now() - interval '10 minutes'
                ORDER BY opened_at DESC LIMIT 1
            )
        """), {"uid": body.study_instance_uid, "u": user.username, "lm": body.load_ms})
        await db.execute(text("""
            UPDATE prefetch_history SET open_load_ms = :lm
            WHERE id = (
                SELECT id FROM prefetch_history
                WHERE study_instance_uid = :uid AND hit = true AND open_load_ms IS NULL
                  AND hit_at > now() - interval '10 minutes'
                ORDER BY hit_at DESC LIMIT 1
            )
        """), {"uid": body.study_instance_uid, "lm": body.load_ms})

    # full-volume load time (progressive-loading measurement): fill the most
    # recent open row for this study/user that lacks it
    if body.volume_complete_ms is not None:
        await db.execute(text("""
            UPDATE viewer_open_events SET volume_complete_ms = :vm
            WHERE id = (
                SELECT id FROM viewer_open_events
                WHERE study_instance_uid = :uid AND username = :u AND volume_complete_ms IS NULL
                  AND opened_at > now() - interval '10 minutes'
                ORDER BY opened_at DESC LIMIT 1
            )
        """), {"uid": body.study_instance_uid, "u": user.username, "vm": body.volume_complete_ms})

    await db.commit()
    return {"accepted": True}


@router.get("/stats", summary="프리페치 적중률/성능 통계")
async def prefetch_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    hours: int = Query(24, ge=1, le=720),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST)),
):
    warm = (await db.execute(text("""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE hit) AS hits,
               COALESCE(SUM(frames_warmed), 0) AS frames,
               COALESCE(SUM(bytes_warmed), 0) AS bytes,
               COALESCE(AVG(duration_ms), 0) AS avg_duration_ms
        FROM prefetch_history
        WHERE warmed_at > now() - make_interval(hours => :h)
          AND status IN ('done', 'partial')
    """), {"h": hours})).mappings().first()

    by_reason = (await db.execute(text("""
        SELECT reason, COUNT(*) AS total, COUNT(*) FILTER (WHERE hit) AS hits
        FROM prefetch_history
        WHERE warmed_at > now() - make_interval(hours => :h)
          AND status IN ('done', 'partial')
        GROUP BY reason
    """), {"h": hours})).mappings().all()

    opens = (await db.execute(text("""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE was_prefetched) AS warmed,
               AVG(load_ms) FILTER (WHERE was_prefetched) AS load_ms_warmed,
               AVG(load_ms) FILTER (WHERE NOT was_prefetched) AS load_ms_cold,
               -- progressive 3D loading: first usable image vs full volume loaded
               AVG(load_ms) FILTER (WHERE volume_complete_ms IS NOT NULL) AS first_image_ms,
               AVG(volume_complete_ms) AS volume_complete_ms,
               COUNT(*) FILTER (WHERE volume_complete_ms IS NOT NULL) AS volume_samples
        FROM viewer_open_events
        WHERE opened_at > now() - make_interval(hours => :h)
    """), {"h": hours})).mappings().first()

    total = warm["total"] or 0
    return {
        "hours": hours,
        "warmed_studies": total,
        "hit_rate": round((warm["hits"] or 0) / total, 3) if total else None,
        "frames_warmed": int(warm["frames"]),
        "bytes_warmed": int(warm["bytes"]),
        "avg_warm_duration_ms": round(float(warm["avg_duration_ms"])),
        "by_reason": [dict(r) for r in by_reason],
        "viewer_opens": {
            "total": opens["total"],
            "warmed": opens["warmed"],
            "avg_load_ms_warmed": round(float(opens["load_ms_warmed"])) if opens["load_ms_warmed"] is not None else None,
            "avg_load_ms_cold": round(float(opens["load_ms_cold"])) if opens["load_ms_cold"] is not None else None,
        },
        # Progressive 3D volume loading: gap between first usable image and full
        # volume = how much sooner the radiologist gets a workable MPR/3D.
        "progressive_volume": {
            "samples": opens["volume_samples"],
            "avg_first_image_ms": round(float(opens["first_image_ms"])) if opens["first_image_ms"] is not None else None,
            "avg_volume_complete_ms": round(float(opens["volume_complete_ms"])) if opens["volume_complete_ms"] is not None else None,
        },
    }


@router.get("/config", summary="프리페치 설정 조회")
async def get_config(
    request: Request,
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    cfg = PrefetchConfig(
        enabled=settings.prefetch_enabled,
        next_n=settings.prefetch_next_n,
        prior_n=settings.prefetch_prior_n,
        max_frames_per_study=settings.prefetch_max_frames_per_study,
    ).model_dump()
    try:
        raw = await request.app.state.redis.get(CONFIG_KEY)
        if raw:
            cfg.update({k: v for k, v in json.loads(raw).items() if k in cfg})
    except Exception:
        pass
    return cfg


@router.put("/config", summary="프리페치 설정 변경")
async def put_config(
    body: PrefetchConfig,
    request: Request,
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    try:
        await request.app.state.redis.set(CONFIG_KEY, json.dumps(body.model_dump()))
    except Exception as e:
        raise HTTPException(503, f"Config store unavailable: {e}")
    logger.info(f"prefetch config updated by {user.username}: {body.model_dump()}")
    return body.model_dump()
