"""API endpoints for SLA escalation rules and actions.

Extends existing display-only SLA (dashboard.py) with:
- Configurable thresholds per modality
- Automatic escalation rules (reassign, notify)
- Escalation history tracking
- Role-based escalation chains
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_async_db
from app.core.auth import get_current_user
from app.core.security import RequireRole
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sla", tags=["SLA Escalation"])


# ─── Models ───

class ModalityThreshold(BaseModel):
    modality: str  # CT, MR, CR, DX, US, etc. or "default"
    warning_minutes: int = 30
    critical_minutes: int = 60
    auto_escalate: bool = True

class EscalationRule(BaseModel):
    id: Optional[str] = None
    name: str
    trigger: str  # "warning" or "critical"
    action: str   # "reassign", "notify", "escalate_to_supervisor"
    target_role: Optional[str] = None  # radiologist, admin
    target_username: Optional[str] = None
    enabled: bool = True

class SLAConfigPayload(BaseModel):
    thresholds: list[ModalityThreshold]
    rules: list[EscalationRule]

class EscalationLogEntry(BaseModel):
    study_instance_uid: str
    escalation_type: str  # warning_escalated, critical_escalated, auto_reassigned
    action_taken: str
    from_user: Optional[str] = None
    to_user: Optional[str] = None
    notes: Optional[str] = None


# ─── Table setup ───

SETUP_SQL = """
CREATE TABLE IF NOT EXISTS sla_escalation_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    study_instance_uid TEXT NOT NULL,
    escalation_type TEXT NOT NULL,
    action_taken TEXT NOT NULL,
    from_user TEXT,
    to_user TEXT,
    notes TEXT,
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    sla_minutes INT
);
CREATE INDEX IF NOT EXISTS idx_sla_esc_study ON sla_escalation_log(study_instance_uid);
CREATE INDEX IF NOT EXISTS idx_sla_esc_time ON sla_escalation_log(triggered_at DESC);
"""

async def _ensure_tables(db: AsyncSession):
    try:
        await db.execute(text(SETUP_SQL))
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS openpacs_config (
                key TEXT PRIMARY KEY,
                value JSONB NOT NULL DEFAULT '{}',
                updated_by TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        await db.commit()
    except Exception:
        await db.rollback()


# ─── Default config ───

DEFAULT_THRESHOLDS = [
    {"modality": "default", "warning_minutes": 30, "critical_minutes": 60, "auto_escalate": True},
    {"modality": "CT", "warning_minutes": 30, "critical_minutes": 45, "auto_escalate": True},
    {"modality": "MR", "warning_minutes": 45, "critical_minutes": 90, "auto_escalate": True},
    {"modality": "CR", "warning_minutes": 30, "critical_minutes": 60, "auto_escalate": True},
    {"modality": "US", "warning_minutes": 60, "critical_minutes": 120, "auto_escalate": False},
    {"modality": "DX", "warning_minutes": 30, "critical_minutes": 60, "auto_escalate": True},
]

DEFAULT_RULES = [
    {"id": "rule-1", "name": "경고 알림", "trigger": "warning", "action": "notify", "target_role": "radiologist", "enabled": True},
    {"id": "rule-2", "name": "위험 재배정", "trigger": "critical", "action": "reassign", "target_role": "radiologist", "enabled": True},
    {"id": "rule-3", "name": "위험 상급 에스컬레이션", "trigger": "critical", "action": "escalate_to_supervisor", "target_role": "admin", "enabled": False},
]


# ─── Config Endpoints ───

@router.get("/config")
async def get_sla_config(
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """Get SLA thresholds and escalation rules."""
    try:
        result = await db.execute(
            text("SELECT value FROM openpacs_config WHERE key = 'sla_config'")
        )
        row = result.scalar_one_or_none()
        if row:
            data = json.loads(row) if isinstance(row, str) else row
            return data
    except Exception:
        pass

    return {"thresholds": DEFAULT_THRESHOLDS, "rules": DEFAULT_RULES}


@router.put("/config")
async def update_sla_config(
    payload: SLAConfigPayload,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    """Update SLA config. Admin only."""
    # Assign IDs to rules without them
    for rule in payload.rules:
        if not rule.id:
            rule.id = f"rule-{uuid.uuid4().hex[:8]}"

    data = payload.model_dump()
    value_json = json.dumps(data, ensure_ascii=False)

    await db.execute(text("""
        INSERT INTO openpacs_config (key, value, updated_by)
        VALUES ('sla_config', :val, :user)
        ON CONFLICT (key) DO UPDATE SET value = :val, updated_by = :user, updated_at = NOW()
    """), {"val": value_json, "user": user.username})
    await db.commit()

    logger.info("SLA config updated by %s", user.username)
    return {"status": "ok", "message": "SLA 설정이 저장되었습니다"}


# ─── Escalation Endpoints ───

@router.post("/escalate")
async def trigger_escalation(
    entry: EscalationLogEntry,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST, allow_btg=False)),
):
    """Manually trigger an escalation for a study."""
    esc_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO sla_escalation_log (id, study_instance_uid, escalation_type, action_taken,
            from_user, to_user, notes, triggered_at)
        VALUES (:id, :study_uid, :esc_type, :action, :from_user, :to_user, :notes, NOW())
    """), {
        "id": esc_id, "study_uid": entry.study_instance_uid,
        "esc_type": entry.escalation_type, "action": entry.action_taken,
        "from_user": entry.from_user or user.username,
        "to_user": entry.to_user, "notes": entry.notes,
    })
    await db.commit()

    logger.info("SLA escalation triggered for %s by %s", entry.study_instance_uid, user.username)
    return {"id": esc_id, "message": "에스컬레이션이 등록되었습니다"}


@router.get("/escalations")
async def list_escalations(
    study_uid: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """List escalation history."""
    where = "WHERE 1=1"
    params: dict = {"limit": limit, "offset": offset}
    if study_uid:
        where += " AND study_instance_uid = :study_uid"
        params["study_uid"] = study_uid

    result = await db.execute(text(f"""
        SELECT id, study_instance_uid, escalation_type, action_taken,
               from_user, to_user, notes, triggered_at, resolved_at, sla_minutes
        FROM sla_escalation_log {where}
        ORDER BY triggered_at DESC
        LIMIT :limit OFFSET :offset
    """), params)

    rows = result.fetchall()
    items = [{
        "id": str(r[0]), "study_instance_uid": r[1], "escalation_type": r[2],
        "action_taken": r[3], "from_user": r[4], "to_user": r[5], "notes": r[6],
        "triggered_at": r[7].isoformat() if r[7] else None,
        "resolved_at": r[8].isoformat() if r[8] else None,
        "sla_minutes": r[9],
    } for r in rows]

    count_result = await db.execute(text(f"SELECT COUNT(*) FROM sla_escalation_log {where}"), params)
    total = count_result.scalar() or 0

    return {"items": items, "total": total}


@router.patch("/escalations/{escalation_id}/resolve")
async def resolve_escalation(
    escalation_id: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(RequireRole(Role.ADMIN, Role.RADIOLOGIST, Role.TECHNOLOGIST, allow_btg=False)),
):
    """Mark an escalation as resolved. Staff only."""
    result = await db.execute(
        text("SELECT id FROM sla_escalation_log WHERE id = :id"),
        {"id": escalation_id},
    )
    if not result.fetchone():
        raise HTTPException(404, "에스컬레이션을 찾을 수 없습니다")

    await db.execute(
        text("UPDATE sla_escalation_log SET resolved_at = NOW() WHERE id = :id"),
        {"id": escalation_id},
    )
    await db.commit()

    return {"status": "resolved", "message": "에스컬레이션이 해결되었습니다"}


@router.get("/stats")
async def sla_stats(
    days: int = Query(7, le=90),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """SLA escalation statistics."""
    result = await db.execute(text("""
        SELECT escalation_type, COUNT(*) as cnt
        FROM sla_escalation_log
        WHERE triggered_at > NOW() - MAKE_INTERVAL(days => :days)
        GROUP BY escalation_type
    """), {"days": days})
    by_type = {r[0]: r[1] for r in result.fetchall()}

    resolved_result = await db.execute(text("""
        SELECT
            COUNT(*) as total,
            COUNT(resolved_at) as resolved,
            AVG(EXTRACT(EPOCH FROM (COALESCE(resolved_at, NOW()) - triggered_at)) / 60) as avg_resolution_min
        FROM sla_escalation_log
        WHERE triggered_at > NOW() - MAKE_INTERVAL(days => :days)
    """), {"days": days})
    row = resolved_result.fetchone()

    return {
        "period_days": days,
        "total": row[0] if row else 0,
        "resolved": row[1] if row else 0,
        "unresolved": (row[0] - row[1]) if row else 0,
        "avg_resolution_minutes": round(row[2] or 0, 1) if row else 0,
        "by_type": by_type,
    }


@router.post("/check-now", summary="SLA 즉시 체크")
async def sla_check_now(
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    """수동으로 SLA 체크를 즉시 실행합니다. Celery beat 스케줄과 별도. Admin only."""

    from app.services.sla_scheduler import check_sla
    task = check_sla.delay()
    return {
        "task_id": task.id,
        "status": "queued",
        "message": "SLA 체크가 큐에 등록되었습니다. 5분 내 결과가 반영됩니다.",
    }


@router.get("/scheduler-status", summary="SLA 스케줄러 상태")
async def sla_scheduler_status(
    user: User = Depends(get_current_user),
):
    """Celery beat SLA 스케줄러 상태를 조회합니다."""
    from app.services.ai_worker import celery_app

    scheduled = celery_app.conf.get("beat_schedule", {})
    sla_tasks = {k: {
        "task": v["task"],
        "interval_seconds": v.get("schedule", 0),
    } for k, v in scheduled.items() if "sla" in k.lower()}

    # Check last execution from Redis
    import redis
    try:
        r = redis.from_url(celery_app.conf.broker_url)
        last_check = r.get("sla:last_check")
        last_result = r.get("sla:last_result")
    except Exception:
        last_check = None
        last_result = None

    return {
        "scheduler": "celery-beat",
        "tasks": sla_tasks,
        "last_check": last_check.decode() if last_check else None,
        "last_result": json.loads(last_result) if last_result else None,
    }
