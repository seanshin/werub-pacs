"""Storage fundamentals monitor (pacs-fundamentals 1축 — 데이터 안전).

1) check_host_disk (30분): 호스트 파일시스템 실제 사용률 감시. 기존 system_health는
   Orthanc 논리 용량만 봐서(50GB 임계) 호스트 디스크가 차도 알림이 없었다 —
   2026-07-11 실측에서 Orthanc 95MB인데 호스트 86%였던 갭. `/app/export-staging`은
   backend·celery-worker 모두 호스트 바인드 마운트라 statvfs가 호스트 fs를 반영한다.
2) check_retention_candidates (매월): StudyDate가 보존기간(기본 5년, 의료법 제22조)을
   지난 **활성** study를 세어 admin에 아카이브 후보로 알림. 자동 삭제는 하지 않는다 —
   아카이브/purge는 기존 /api/v1/archive 수동 경로(5년 잠금 포함)가 담당.
"""
import json
import logging
import shutil
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import redis as sync_redis
from sqlalchemy import text

from app.core.config import settings
from app.services.ai_worker import celery_app, _get_db_session

logger = logging.getLogger(__name__)

DISK_ALERT_LOCK = "pacs:disk:alerted"           # value = level
DISK_WARN_LOCK_TTL = 24 * 3600                  # warning: 1회/일
DISK_CRIT_LOCK_TTL = 6 * 3600                   # critical: 1회/6시간
RETENTION_LOCK = "pacs:retention:alerted"
RETENTION_LOCK_TTL = 20 * 24 * 3600             # 월간 태스크 중복 방지


def read_host_disk(path: str | None = None) -> dict:
    """Pure-ish read — system_health(async)와 beat(sync)가 공유."""
    p = path or settings.disk_watch_path
    try:
        du = shutil.disk_usage(p)
    except Exception as e:
        return {"status": "unknown", "detail": str(e)[:100], "path": p}
    used_pct = round(du.used / du.total * 100, 1)
    status = "ok"
    if used_pct >= settings.disk_crit_pct:
        status = "critical"
    elif used_pct >= settings.disk_warn_pct:
        status = "warning"
    return {
        "status": status,
        "used_pct": used_pct,
        "free_gb": round(du.free / 2**30, 1),
        "total_gb": round(du.total / 2**30, 1),
        "path": p,
    }


def _notify_admin(title: str, msg: str, urgency: str, ntype: str) -> str:
    db = _get_db_session()
    if not db:
        logger.error(f"{ntype}: DB unavailable for alert — {msg}")
        return "db_unavailable"
    try:
        db.execute(text("""
            INSERT INTO notifications (id, type, title, message, urgency, target_role,
                study_instance_uid, action_url, is_read, acknowledged, created_at)
            VALUES (:id, :type, :title, :msg, :urgency, 'admin',
                    NULL, '/pacs-admin/notifications', false, false, NOW())
        """), {"id": str(uuid.uuid4()), "type": ntype, "title": title,
               "msg": msg, "urgency": urgency})
        db.commit()
        logger.warning(f"{ntype} alert created: {msg}")
        return "created"
    except Exception as e:
        logger.error(f"{ntype} alert insert failed: {e}")
        return f"error: {e}"
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=0)
def check_host_disk(self):
    st = read_host_disk()
    if st["status"] in ("ok", "unknown"):
        if st["status"] == "unknown":
            logger.warning(f"host disk check unavailable: {st.get('detail')}")
        return st

    ttl = DISK_CRIT_LOCK_TTL if st["status"] == "critical" else DISK_WARN_LOCK_TTL
    try:
        r = sync_redis.Redis.from_url(settings.redis_url, decode_responses=True)
        prev = r.get(DISK_ALERT_LOCK)
        # 같은 레벨이면 TTL 내 재알림 억제, 레벨이 올라가면(warning→critical) 즉시 재알림
        if prev == st["status"]:
            return {**st, "alert": "suppressed"}
        r.set(DISK_ALERT_LOCK, st["status"], ex=ttl)
    except Exception as e:
        logger.warning(f"disk alert lock unavailable: {e}")

    urgency = "critical" if st["status"] == "critical" else "urgent"
    alert = _notify_admin(
        "디스크 용량 경고",
        f"호스트 디스크 사용률 {st['used_pct']}% (잔여 {st['free_gb']}GB / "
        f"전체 {st['total_gb']}GB) — {st['status']}. 정리 또는 증설이 필요합니다.",
        urgency, "disk_alert",
    )
    return {**st, "alert": alert}


def _retention_cutoff_yyyymmdd(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=settings.retention_years * 365)
    return cutoff.strftime("%Y%m%d")


def find_retention_candidates_sync(limit: int = 500) -> dict:
    """StudyDate ≤ 보존 컷오프인 활성 study — Orthanc DICOM 날짜범위 질의."""
    cutoff = _retention_cutoff_yyyymmdd()
    with httpx.Client(
        base_url=settings.orthanc_url,
        auth=(settings.orthanc_username, settings.orthanc_password),
        timeout=30,
    ) as client:
        resp = client.post("/tools/find", json={
            "Level": "Study",
            "Query": {"StudyDate": f"19000101-{cutoff}"},
            "Expand": True,
            "RequestedTags": ["StudyDate", "ModalitiesInStudy"],
            "Limit": limit,
        })
        resp.raise_for_status()
        studies = resp.json()
    candidates = [{
        "orthanc_id": s.get("ID"),
        "study_instance_uid": s.get("MainDicomTags", {}).get("StudyInstanceUID"),
        "study_date": s.get("MainDicomTags", {}).get("StudyDate"),
        "modalities": s.get("RequestedTags", {}).get("ModalitiesInStudy", ""),
    } for s in studies]
    return {"cutoff": cutoff, "retention_years": settings.retention_years,
            "count": len(candidates), "candidates": candidates}


@celery_app.task(bind=True, max_retries=0)
def check_retention_candidates(self):
    try:
        result = find_retention_candidates_sync()
    except Exception as e:
        logger.error(f"retention candidate scan failed: {e}")
        return {"status": "error", "detail": str(e)[:100]}
    if result["count"] == 0:
        return {"status": "ok", **{k: result[k] for k in ("cutoff", "count")}}

    try:
        r = sync_redis.Redis.from_url(settings.redis_url, decode_responses=True)
        if not r.set(RETENTION_LOCK, str(result["count"]), nx=True, ex=RETENTION_LOCK_TTL):
            return {"status": "ok", "count": result["count"], "alert": "suppressed"}
    except Exception as e:
        logger.warning(f"retention alert lock unavailable: {e}")

    alert = _notify_admin(
        "보존기간 만료 검사 알림",
        f"보존기간({result['retention_years']}년)이 지난 검사 {result['count']}건이 "
        f"활성 상태입니다 (StudyDate ≤ {result['cutoff']}). 아카이브를 검토하세요.",
        "normal", "retention_alert",
    )
    return {"status": "ok", "count": result["count"], "alert": alert}
