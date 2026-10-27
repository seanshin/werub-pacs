"""Backup freshness monitor (backup-dr).

backup-openpacs.sh writes its outcome to Redis (pacs:backup:status); this beat
task alerts admins when that status is failed or stale (>26h). A missing key
means backups were never enabled — deliberately silent, so the monitor can ship
before the cron is registered (구현만, 실백업 미가동 단계).
"""
import json
import logging
import time
import uuid

import redis as sync_redis
from sqlalchemy import text

from app.core.config import settings
from app.services.ai_worker import celery_app, _get_db_session

logger = logging.getLogger(__name__)

STATUS_KEY = "pacs:backup:status"
ALERT_LOCK_KEY = "pacs:backup:alerted"
ALERT_LOCK_TTL = 24 * 3600          # one alert per day at most
STALE_AFTER_SEC = 26 * 3600          # daily backup + 2h grace


def classify_backup_status(raw: str | None) -> dict:
    """Pure classification — shared by the sync Celery task and async system_health
    (each fetches the Redis key with its own client)."""
    if not raw:
        return {"status": "not_configured"}
    try:
        st = json.loads(raw)
    except Exception:
        return {"status": "unknown", "detail": "unparseable status"}
    age = time.time() - float(st.get("ts", 0))
    state = "ok"
    if not st.get("ok"):
        state = "failed"
    elif age > STALE_AFTER_SEC:
        state = "stale"
    return {
        "status": state,
        "last_ts": st.get("ts"),
        "age_hours": round(age / 3600, 1),
        "db_bytes": st.get("db_bytes"),
        "dicom_files": st.get("dicom_files"),
        "err": st.get("err") or None,
    }


def read_backup_status() -> dict:
    """Sync read for Celery context."""
    try:
        r = sync_redis.Redis.from_url(settings.redis_url, decode_responses=True)
        raw = r.get(STATUS_KEY)
    except Exception as e:
        return {"status": "unknown", "detail": f"redis: {e}"[:100]}
    return classify_backup_status(raw)


@celery_app.task(bind=True, max_retries=0)
def check_backup_freshness(self):
    st = read_backup_status()
    if st["status"] in ("ok", "not_configured"):
        return st

    # failed/stale/unknown → notify admins, at most once per ALERT_LOCK_TTL
    try:
        r = sync_redis.Redis.from_url(settings.redis_url, decode_responses=True)
        if not r.set(ALERT_LOCK_KEY, st["status"], nx=True, ex=ALERT_LOCK_TTL):
            return {**st, "alert": "suppressed"}
    except Exception as e:
        logger.warning(f"backup alert lock unavailable: {e}")

    db = _get_db_session()
    if not db:
        logger.error(f"backup status {st['status']} but DB unavailable for alert")
        return {**st, "alert": "db_unavailable"}
    try:
        msg = {
            "failed": f"백업 실패: {st.get('err') or '원인 불명'}",
            "stale": f"백업이 {st.get('age_hours')}시간 동안 실행되지 않았습니다.",
            "unknown": f"백업 상태 확인 불가: {st.get('detail', '')}",
        }[st["status"]]
        db.execute(text("""
            INSERT INTO notifications (id, type, title, message, urgency, target_role,
                study_instance_uid, action_url, is_read, acknowledged, created_at)
            VALUES (:id, 'backup_alert', :title, :msg, 'high', 'admin',
                    NULL, '/pacs-admin/notifications', false, false, NOW())
        """), {"id": str(uuid.uuid4()), "title": "백업 이상", "msg": msg})
        db.commit()
        logger.warning(f"backup alert created: {st['status']} — {msg}")
        return {**st, "alert": "created"}
    except Exception as e:
        logger.error(f"backup alert insert failed: {e}")
        return {**st, "alert": f"error: {e}"}
    finally:
        db.close()
