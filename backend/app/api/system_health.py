"""System Health & Storage Management API.

In-app monitoring: container status, disk usage, retention policy.
"""
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import RequireRole
from app.models.user import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/system", tags=["System Health"])


@router.get("/health-detail", summary="시스템 상세 건강 상태")
async def system_health_detail(
    request: Request,
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
    db: AsyncSession = Depends(get_db),
):
    """모든 서비스 상태, 디스크, DB, 캐시 상태를 반환합니다."""
    import redis.asyncio as aioredis

    health = {"timestamp": datetime.now(timezone.utc).isoformat(), "services": {}}

    # Orthanc
    try:
        resp = await request.app.state.http_client.get("/statistics")
        if resp.status_code == 200:
            stats = resp.json()
            health["services"]["orthanc"] = {
                "status": "ok",
                "patients": stats.get("CountPatients"),
                "studies": stats.get("CountStudies"),
                "instances": stats.get("CountInstances"),
                "disk_mb": stats.get("TotalDiskSizeMB"),
            }
        else:
            health["services"]["orthanc"] = {"status": "error", "code": resp.status_code}
    except Exception as e:
        health["services"]["orthanc"] = {"status": "error", "detail": str(e)[:100]}

    # Redis
    try:
        await request.app.state.redis.ping()
        info = await request.app.state.redis.info("memory")
        health["services"]["redis"] = {
            "status": "ok",
            "used_memory_mb": round(info.get("used_memory", 0) / 1024 / 1024, 1),
            "connected_clients": (await request.app.state.redis.info("clients")).get("connected_clients"),
        }
    except Exception as e:
        health["services"]["redis"] = {"status": "error", "detail": str(e)[:100]}

    # PostgreSQL
    try:
        result = await db.execute(text("SELECT pg_database_size('openpacs') as size"))
        db_size = result.scalar()
        table_result = await db.execute(text("""
            SELECT relname as table, pg_total_relation_size(relid) as size
            FROM pg_catalog.pg_statio_user_tables
            ORDER BY pg_total_relation_size(relid) DESC LIMIT 10
        """))
        tables = [{"table": r._mapping["table"], "size_mb": round(r._mapping["size"] / 1024 / 1024, 2)} for r in table_result]

        health["services"]["database"] = {
            "status": "ok",
            "total_size_mb": round(db_size / 1024 / 1024, 1) if db_size else 0,
            "top_tables": tables,
        }
    except Exception as e:
        health["services"]["database"] = {"status": "error", "detail": str(e)[:100]}

    # Backup freshness (backup-dr) — not_configured until the cron is enabled
    try:
        from app.services.backup_monitor import STATUS_KEY, classify_backup_status
        raw = await request.app.state.redis.get(STATUS_KEY)
        health["services"]["backup"] = classify_backup_status(raw)
    except Exception as e:
        health["services"]["backup"] = {"status": "unknown", "detail": str(e)[:100]}

    # Host disk (pacs-fundamentals) — Orthanc 논리 용량이 아니라 실제 호스트 fs를 본다
    try:
        from app.services.storage_monitor import read_host_disk
        health["services"]["host_disk"] = read_host_disk()
    except Exception as e:
        health["services"]["host_disk"] = {"status": "unknown", "detail": str(e)[:100]}

    # AI 서버 — beat가 남긴 마지막 프로브 결과(여기서 직접 프로브하면 health가
    # 외부 장애에 물린다). 2026-08-03: 무감시로 2주+ 다운이 방치된 이력.
    try:
        from app.services.ai_health_monitor import STATUS_KEY as AI_STATUS_KEY, classify_ai_status
        raw = await request.app.state.redis.get(AI_STATUS_KEY)
        health["services"]["ai_server"] = classify_ai_status(raw)
    except Exception as e:
        health["services"]["ai_server"] = {"status": "unknown", "detail": str(e)[:100]}

    # Storage alerts
    orthanc_disk = health["services"].get("orthanc", {}).get("disk_mb", 0) or 0
    alerts = []
    if orthanc_disk > 50000:
        alerts.append({"level": "warning", "message": f"Orthanc 스토리지 {orthanc_disk}MB — 50GB 초과"})
    if orthanc_disk > 200000:
        alerts.append({"level": "critical", "message": f"Orthanc 스토리지 {orthanc_disk}MB — 200GB 초과, 정리 필요"})
    hd = health["services"]["host_disk"]
    if hd.get("status") in ("warning", "critical"):
        alerts.append({"level": hd["status"],
                       "message": f"호스트 디스크 {hd['used_pct']}% 사용 — 잔여 {hd['free_gb']}GB"})
    ai = health["services"]["ai_server"]
    if ai.get("status") in ("down", "degraded", "stale"):
        alerts.append({"level": "warning" if ai["status"] != "down" else "critical",
                       "message": f"AI 서버 {ai['status']}"
                                  f"({ai.get('reason') or ai.get('detail') or ''}) — "
                                  f"추론·스크리닝·판독보조 중단"})

    health["alerts"] = alerts

    return health


@router.get("/storage/stats", summary="스토리지 사용량 상세")
async def storage_stats(
    request: Request,
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
):
    """Orthanc 스토리지 사용량을 모달리티/연도별로 분석합니다."""
    orthanc = request.app.state.http_client

    # Get all studies with metadata
    resp = await orthanc.post("/tools/find", json={
        "Level": "Study", "Query": {}, "Expand": True,
    })
    if resp.status_code != 200:
        raise HTTPException(502, "Orthanc 연결 실패")

    studies = resp.json()

    by_year = {}
    by_modality = {}

    for s in studies:
        tags = s.get("MainDicomTags", {})
        date = tags.get("StudyDate", "")[:4] or "unknown"
        modality = tags.get("ModalitiesInStudy", "OT")

        by_year[date] = by_year.get(date, 0) + 1
        by_modality[modality] = by_modality.get(modality, 0) + 1

    resp2 = await orthanc.get("/statistics")
    total = resp2.json() if resp2.status_code == 200 else {}

    return {
        "total_studies": total.get("CountStudies", len(studies)),
        "total_instances": total.get("CountInstances", 0),
        "total_disk_mb": total.get("TotalDiskSizeMB", 0),
        "by_year": dict(sorted(by_year.items(), reverse=True)),
        "by_modality": dict(sorted(by_modality.items(), key=lambda x: -x[1])),
    }


@router.get("/audit/summary", summary="감사 로그 요약")
async def audit_summary(
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(RequireRole(Role.ADMIN, allow_btg=False)),
    db: AsyncSession = Depends(get_db),
):
    """최근 N일간 감사 로그 요약 (액션별, 사용자별)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # By action
    result = await db.execute(text("""
        SELECT action, count(*) as cnt
        FROM audit_logs WHERE created_at >= :since
        GROUP BY action ORDER BY cnt DESC
    """), {"since": since})
    by_action = [dict(r._mapping) for r in result]

    # By user
    result = await db.execute(text("""
        SELECT username AS user_name, count(*) as cnt
        FROM audit_logs WHERE created_at >= :since
        GROUP BY username ORDER BY cnt DESC LIMIT 20
    """), {"since": since})
    by_user = [dict(r._mapping) for r in result]

    # Total
    result = await db.execute(text(
        "SELECT count(*) FROM audit_logs WHERE created_at >= :since"
    ), {"since": since})
    total = result.scalar()

    return {
        "period_days": days,
        "total_logs": total,
        "by_action": by_action,
        "by_user": by_user,
    }
