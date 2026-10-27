"""AI model governance API (ai-governance feature).

Time-series trends, drift alerts, and clinical/research compliance — the
governable-AI layer over the existing model registry and inference history.
Drift/compliance read the beat-written Redis snapshots (fallback: compute live).
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
from app.core.security import RequireRole
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/governance", tags=["AI 거버넌스"])

DRIFT_KEY = "pacs:governance:drift"
COMPLIANCE_KEY = "pacs:governance:compliance"
CONFIG_KEY = "pacs:governance:config"


class GovConfig(BaseModel):
    success_drop: float = Field(0.15, ge=0, le=1)
    time_increase: float = Field(0.50, ge=0, le=10)
    acceptance_drop: float = Field(0.20, ge=0, le=1)
    min_samples: int = Field(20, ge=1, le=10000)
    retention_days: int = Field(365, ge=7, le=3650)


@router.get("/summary", summary="거버넌스 현황 요약")
async def summary(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False)),
):
    models = (await db.execute(text(
        "SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE is_active) AS active FROM ai_models"
    ))).mappings().first()
    acc = (await db.execute(text("""
        SELECT AVG(acceptance_rate) AS avg_acc
        FROM model_performance_daily WHERE day > CURRENT_DATE - 30 AND acceptance_rate IS NOT NULL
    """))).mappings().first()
    # on-demand 수용률 — 컬럼 부재(거버넌스 첫 롤업 전) 시 None (트랜잭션 abort 회피)
    od_acc = None
    has_od = (await db.execute(text("""
        SELECT EXISTS(SELECT 1 FROM information_schema.columns
            WHERE table_name='model_performance_daily' AND column_name='ondemand_acceptance_rate')
    """))).scalar()
    if has_od:
        od = (await db.execute(text("""
            SELECT AVG(ondemand_acceptance_rate) AS a FROM model_performance_daily
            WHERE day > CURRENT_DATE - 30 AND ondemand_acceptance_rate IS NOT NULL
        """))).mappings().first()
        od_acc = round(float(od["a"]), 3) if od["a"] is not None else None
    redis = request.app.state.redis
    drift = json.loads(await redis.get(DRIFT_KEY) or "[]")
    comp = json.loads(await redis.get(COMPLIANCE_KEY) or "{}")
    return {
        "total_models": models["total"], "active_models": models["active"],
        "avg_acceptance_rate_30d": round(float(acc["avg_acc"]), 3) if acc["avg_acc"] is not None else None,
        "avg_ondemand_acceptance_rate_30d": od_acc,
        "drift_alerts": sum(1 for d in drift if d.get("status") == "drift"),
        # 진행 중 위반(최근 창) — 과거 이력은 별도로 노출해 "사라진 것처럼" 보이지 않게 (v13.37)
        "compliance_violations": len(comp.get("research_used_clinically", [])),
        "compliance_violations_all_time": len(comp.get("research_used_clinically_all_time", [])),
        "auto_quarantine_enabled": settings.governance_auto_quarantine,
    }


@router.get("/models/{model_name}/trend", summary="모델 성능 시계열")
async def trend(
    model_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False)),
):
    # on-demand 컬럼은 ALTER-only(첫 거버넌스 beat 전엔 부재) → 가드해 500 회피
    has_od = (await db.execute(text("""
        SELECT EXISTS(SELECT 1 FROM information_schema.columns
            WHERE table_name='model_performance_daily' AND column_name='ondemand_acceptance_rate')
    """))).scalar()
    od_cols = ", ondemand_total, ondemand_acceptance_rate" if has_od else ""
    rows = (await db.execute(text(f"""
        SELECT day, total_jobs, completed, failed, success_rate, avg_inference_ms,
               critical_count, acceptance_rate{od_cols}
        FROM model_performance_daily
        WHERE model_name = :m AND day > CURRENT_DATE - make_interval(days => :d)
        ORDER BY day ASC
    """), {"m": model_name, "d": days})).mappings().all()
    return {"model_name": model_name, "days": days, "series": [dict(r) for r in rows]}


@router.get("/drift", summary="드리프트 경보")
async def drift(request: Request, user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False))):
    raw = await request.app.state.redis.get(DRIFT_KEY)
    return {"status": "computed" if raw else "not_yet_run", "models": json.loads(raw or "[]")}


@router.get("/compliance", summary="clinical/research·인증 준수 점검")
async def compliance(request: Request, user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False))):
    raw = await request.app.state.redis.get(COMPLIANCE_KEY)
    return json.loads(raw or "{}") or {"status": "not_yet_run"}


@router.get("/config", summary="거버넌스 임계값 조회")
async def get_config(request: Request, user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False))):
    from app.services.governance_monitor import get_thresholds
    return get_thresholds()


@router.put("/config", summary="거버넌스 임계값 변경")
async def put_config(
    body: GovConfig,
    request: Request,
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    await request.app.state.redis.set(CONFIG_KEY, json.dumps(body.model_dump()))
    logger.info(f"governance config updated by {user.username}: {body.model_dump()}")
    return body.model_dump()


@router.get("/actions", summary="거버넌스 액션 로그(자동격리/재활성)")
async def actions(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, allow_btg=False)),
):
    if not (await db.execute(text(
            "SELECT to_regclass('public.model_governance_actions') IS NOT NULL"))).scalar():
        return {"actions": []}
    rows = (await db.execute(text("""
        SELECT model_name, action, reason, actor, created_at
        FROM model_governance_actions ORDER BY created_at DESC LIMIT :l
    """), {"l": limit})).mappings().all()
    return {"actions": [dict(r) for r in rows]}


@router.post("/models/{model_name}/reactivate", summary="격리 모델 재활성(관리자)")
async def reactivate(
    model_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    # 액션 로그 테이블 보장(첫 beat 전 부재 시 감사 유실 방지) — 멱등
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS model_governance_actions (
            id UUID PRIMARY KEY, model_name TEXT NOT NULL, action TEXT NOT NULL,
            reason TEXT, actor TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())
    """))
    # 비활성(격리) 모델만 재활성 — status enum NAME 대문자
    res = await db.execute(text("""
        UPDATE ai_models SET status = 'ACTIVE', is_active = true
        WHERE name = :n AND is_active = false RETURNING name
    """), {"n": model_name})
    if not res.first():
        raise HTTPException(404, "비활성 모델을 찾을 수 없습니다(이미 활성이거나 미존재)")
    await db.execute(text("""
        INSERT INTO model_governance_actions (id, model_name, action, reason, actor, created_at)
        VALUES (:id, :m, 'manual_reactivate', '관리자 재활성', :actor, NOW())
    """), {"id": str(uuid.uuid4()), "m": model_name, "actor": user.username})
    await db.commit()
    logger.info(f"model {model_name} reactivated by {user.username}")
    return {"model_name": model_name, "status": "reactivated"}
