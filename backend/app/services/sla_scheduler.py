"""SLA Auto-Escalation Scheduler.

Celery beat task that periodically checks unread studies against SLA thresholds
and automatically triggers escalation actions.

Flow:
1. Every 5 minutes, fetch unread studies from reading queue
2. Compare elapsed time against modality-specific thresholds
3. If threshold exceeded → create escalation log entry
4. Execute escalation action (reassign, notify, etc.)
5. Avoid duplicate escalations for same study/level
"""
import json
import logging
import uuid
from datetime import datetime, timezone

import httpx

from app.services.ai_worker import celery_app
from app.core.config import settings

logger = logging.getLogger(__name__)


_sync_engine = None


def _get_sync_db():
    """Get synchronous DB session for Celery tasks (cached bounded-pool engine).
    A NEW create_engine per call leaks pooled connections that are never
    disposed → idle connections accumulate over hours. Cache the engine once."""
    global _sync_engine
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    if _sync_engine is None:
        sync_url = settings.database_url.replace("+asyncpg", "").replace("postgresql+asyncpg://", "postgresql://")
        _sync_engine = create_engine(sync_url, pool_size=2, max_overflow=3,
                                     pool_pre_ping=True, pool_recycle=1800)
    return Session(_sync_engine)


def _get_sla_config(db_session) -> dict:
    """Load SLA config from openpacs_config table."""
    from sqlalchemy import text
    try:
        result = db_session.execute(
            text("SELECT value FROM openpacs_config WHERE key = 'sla_config'")
        )
        row = result.scalar_one_or_none()
        if row:
            return json.loads(row) if isinstance(row, str) else row
    except Exception:
        pass

    # Defaults
    return {
        "thresholds": [
            {"modality": "default", "warning_minutes": 30, "critical_minutes": 60, "auto_escalate": True},
            {"modality": "CT", "warning_minutes": 30, "critical_minutes": 45, "auto_escalate": True},
            {"modality": "MR", "warning_minutes": 45, "critical_minutes": 90, "auto_escalate": True},
        ],
        "rules": [
            {"id": "rule-1", "name": "경고 알림", "trigger": "warning", "action": "notify", "target_role": "radiologist", "enabled": True},
            {"id": "rule-2", "name": "위험 재배정", "trigger": "critical", "action": "reassign", "target_role": "radiologist", "enabled": True},
        ],
    }


def _get_threshold(thresholds: list, modality: str) -> dict:
    """Find threshold for a modality, falling back to default."""
    for t in thresholds:
        if t["modality"].upper() == modality.upper():
            return t
    for t in thresholds:
        if t["modality"] == "default":
            return t
    return {"modality": "default", "warning_minutes": 30, "critical_minutes": 60, "auto_escalate": True}


def _already_escalated(db_session, study_uid: str, esc_type: str) -> bool:
    """Check if this study already has an unresolved escalation of this type."""
    from sqlalchemy import text
    try:
        result = db_session.execute(text(
            "SELECT COUNT(*) FROM sla_escalation_log "
            "WHERE study_instance_uid = :uid AND escalation_type = :type AND resolved_at IS NULL"
        ), {"uid": study_uid, "type": esc_type})
        return (result.scalar() or 0) > 0
    except Exception:
        return False


def _create_escalation(db_session, study_uid: str, esc_type: str, action: str,
                       sla_minutes: int, to_user: str = None, notes: str = None):
    """Insert escalation log entry."""
    from sqlalchemy import text
    try:
        db_session.execute(text("""
            INSERT INTO sla_escalation_log (id, study_instance_uid, escalation_type,
                action_taken, from_user, to_user, notes, triggered_at, sla_minutes)
            VALUES (:id, :uid, :type, :action, 'system', :to_user, :notes, NOW(), :sla_min)
        """), {
            "id": str(uuid.uuid4()), "uid": study_uid, "type": esc_type,
            "action": action, "to_user": to_user,
            "notes": notes, "sla_min": sla_minutes,
        })
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.error("Failed to create escalation: %s", e)


def _execute_action(action: str, target_role: str = None, target_username: str = None,
                    study_uid: str = None, sla_minutes: int = 0, modality: str = "",
                    threshold_min: int = 0, esc_type: str = ""):
    """Execute escalation action (notify, reassign, etc.) via alert service."""
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Can't run async from sync Celery task easily; use fire-and-forget
            _execute_action_sync(action, target_role, target_username,
                                 study_uid, sla_minutes, modality, threshold_min, esc_type)
            return
    except RuntimeError:
        pass

    _execute_action_sync(action, target_role, target_username,
                         study_uid, sla_minutes, modality, threshold_min, esc_type)


def _execute_action_sync(action: str, target_role: str = None, target_username: str = None,
                          study_uid: str = None, sla_minutes: int = 0, modality: str = "",
                          threshold_min: int = 0, esc_type: str = ""):
    """Sync version of action execution — creates notification in DB directly."""
    from sqlalchemy import text

    db = None
    try:
        db = _get_sync_db()

        # Determine urgency and title
        if "critical" in esc_type:
            urgency = "critical"
            title = f"SLA 위험: {modality} 판독 {sla_minutes}분 지연"
            msg = f"{modality} 검사가 {sla_minutes}분 경과 (임계값 {threshold_min}분). 즉시 판독 필요."
        else:
            urgency = "urgent"
            title = f"SLA 경고: {modality} 판독 {sla_minutes}분 경과"
            msg = f"{modality} 검사가 {sla_minutes}분 경과 (임계값 {threshold_min}분). 판독을 진행해 주세요."

        event_type = "sla_critical" if "critical" in esc_type else "sla_warning"
        action_url = f"/pacs-admin/reading/view?study={study_uid}" if study_uid else "/pacs-admin/reading"

        # Insert notification
        import uuid
        db.execute(text("""
            INSERT INTO notifications (id, type, title, message, urgency, target_role,
                target_username, study_instance_uid, action_url, is_read, acknowledged, created_at)
            VALUES (:id, :type, :title, :msg, :urgency, :role, :user, :study_uid, :url,
                    false, false, NOW())
        """), {
            "id": str(uuid.uuid4()), "type": event_type, "title": title,
            "msg": msg, "urgency": urgency,
            "role": target_role, "user": target_username,
            "study_uid": study_uid, "url": action_url,
        })

        # If critical, also notify admin
        if urgency == "critical" and target_role != "admin":
            db.execute(text("""
                INSERT INTO notifications (id, type, title, message, urgency, target_role,
                    study_instance_uid, action_url, is_read, acknowledged, created_at)
                VALUES (:id, :type, :title, :msg, 'critical', 'admin', :study_uid, :url,
                        false, false, NOW())
            """), {
                "id": str(uuid.uuid4()), "type": event_type,
                "title": f"[에스컬레이션] {title}", "msg": msg,
                "study_uid": study_uid, "url": "/pacs-admin/sla",
            })

        db.commit()
        logger.info("SLA %s notification created: study=%s %dmin", action, study_uid, sla_minutes)

    except Exception as e:
        if db:
            db.rollback()
        logger.error("Failed to create SLA notification: %s", e)
    finally:
        if db:
            db.close()


@celery_app.task(name="app.services.sla_scheduler.check_sla", bind=True, max_retries=0)
def check_sla(self):
    """Periodic task: check all unread studies against SLA thresholds.

    Runs every 5 minutes via Celery beat.
    """
    from app.services.beat_lock import acquire_beat_lock, release_beat_lock
    if not acquire_beat_lock("check_sla"):
        logger.info("check_sla: previous run still active, skipping")
        return {"checked": 0, "escalated": 0, "skipped": "locked"}
    db = None
    orthanc_client = None
    try:
        db = _get_sync_db()
        config = _get_sla_config(db)
        thresholds = config.get("thresholds", [])
        rules = config.get("rules", [])
        enabled_rules = [r for r in rules if r.get("enabled", True)]

        if not enabled_rules:
            logger.debug("SLA check: no enabled rules, skipping")
            return {"checked": 0, "escalated": 0}

        # Fetch unread studies from Orthanc
        orthanc_client = httpx.Client(
            base_url=settings.orthanc_url,
            auth=(settings.orthanc_username, settings.orthanc_password),
            timeout=30.0,
        )

        # Get recent studies (last 48 hours). 성능: Expand+RequestedTags로 1콜에 전체 메타
        # (기존 1+200 개별 GET + 시리즈 폴백 N+1 제거 — beat 5분 작업 대폭 단축).
        studies_resp = orthanc_client.post("/tools/find", json={
            "Level": "Study", "Query": {}, "Since": 0, "Limit": 200,
            "Expand": True, "RequestedTags": ["ModalitiesInStudy"],
        })
        if studies_resp.status_code != 200:
            logger.warning("SLA check: Orthanc find failed (%d)", studies_resp.status_code)
            return {"checked": 0, "escalated": 0, "error": "orthanc_unavailable"}

        studies = studies_resp.json()

        # Load existing reports to check read status
        from sqlalchemy import text
        # K5: 언바운드 풀로드 금지(5년 보존 성장) — 최근 10만건이면 SLA 대상(최근 미판독) 충분
        report_result = db.execute(text(
            "SELECT study_instance_uid, status FROM reports ORDER BY created_at DESC LIMIT 100000"
        ))
        report_status = {}
        for row in report_result.fetchall():
            if row[0] not in report_status:
                report_status[row[0]] = row[1]

        checked = 0
        escalated = 0
        now = datetime.now(timezone.utc)

        for study_data in studies:
            try:
                main_tags = study_data.get("MainDicomTags", {})
                study_uid = main_tags.get("StudyInstanceUID", "")

                # 완료된 판독만 제외 — report_status는 enum NAME(DRAFT/PRELIMINARY/FINAL/ADDENDUM,
                # 대문자). 기존 `!= "unread"`는 항상 참이라 DRAFT만 있어도 에스컬레이션서 빠지던 버그.
                # DRAFT/PRELIMINARY(미완료)는 SLA 위반 시 에스컬레이션 대상으로 유지.
                if study_uid in report_status and report_status[study_uid] in ("FINAL", "ADDENDUM"):
                    continue

                # Calculate elapsed time
                study_date = main_tags.get("StudyDate", "")
                study_time = main_tags.get("StudyTime", "")
                if not study_date or len(study_date) != 8:
                    continue

                st = (study_time or "000000")[:6]
                try:
                    study_dt = datetime.strptime(f"{study_date}{st}", "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                except ValueError:
                    continue

                elapsed_min = int((now - study_dt).total_seconds() / 60)
                if elapsed_min <= 0 or elapsed_min > 2880:  # skip > 48h
                    continue

                checked += 1

                # 성능: ModalitiesInStudy는 RequestedTags에 포함 → 시리즈 폴백 N+1 제거
                modality = study_data.get("RequestedTags", {}).get("ModalitiesInStudy", "")

                threshold = _get_threshold(thresholds, modality or "default")
                if not threshold.get("auto_escalate", True):
                    continue

                warning_min = threshold.get("warning_minutes", 30)
                critical_min = threshold.get("critical_minutes", 60)

                # Check critical first
                if elapsed_min >= critical_min:
                    esc_type = "critical_exceeded"
                    if not _already_escalated(db, study_uid, esc_type):
                        for rule in enabled_rules:
                            if rule.get("trigger") == "critical":
                                _create_escalation(db, study_uid, esc_type, rule["action"],
                                    sla_minutes=elapsed_min,
                                    to_user=rule.get("target_username"),
                                    notes=f"[자동] {modality} SLA 위험 ({elapsed_min}분 > {critical_min}분)")
                                _execute_action(rule["action"], rule.get("target_role"),
                                    rule.get("target_username"), study_uid, elapsed_min,
                                    modality=modality, threshold_min=critical_min, esc_type="critical_exceeded")
                                escalated += 1

                elif elapsed_min >= warning_min:
                    esc_type = "warning_exceeded"
                    if not _already_escalated(db, study_uid, esc_type):
                        for rule in enabled_rules:
                            if rule.get("trigger") == "warning":
                                _create_escalation(db, study_uid, esc_type, rule["action"],
                                    sla_minutes=elapsed_min,
                                    to_user=rule.get("target_username"),
                                    notes=f"[자동] {modality} SLA 경고 ({elapsed_min}분 > {warning_min}분)")
                                _execute_action(rule["action"], rule.get("target_role"),
                                    rule.get("target_username"), study_uid, elapsed_min,
                                    modality=modality, threshold_min=warning_min, esc_type="warning_exceeded")
                                escalated += 1

            except Exception as e:
                # A6 fix: loop var is study_data / uid is study_uid. `study_id`
                # was undefined → NameError here escaped to the outer except and
                # aborted the ENTIRE SLA sweep on any single malformed study.
                logger.debug("SLA check error for study %s: %s", study_uid, e)
                continue

        orthanc_client.close()

        logger.info("SLA check completed: checked=%d escalated=%d", checked, escalated)
        return {"checked": checked, "escalated": escalated}

    except Exception as e:
        logger.error("SLA check failed: %s", e)
        return {"checked": 0, "escalated": 0, "error": str(e)}
    finally:
        release_beat_lock("check_sla")
        # 에러 경로에서도 httpx.Client 누수 방지(5분 beat 반복 누적)
        if orthanc_client:
            orthanc_client.close()
        if db:
            db.close()


# ─── Auto-resolve escalations for completed readings ───

@celery_app.task(name="app.services.sla_scheduler.auto_resolve_escalations", bind=True, max_retries=0)
def auto_resolve_escalations(self):
    """Periodic task: auto-resolve escalations for studies that now have final reports."""
    db = None
    try:
        db = _get_sync_db()
        from sqlalchemy import text

        result = db.execute(text("""
            UPDATE sla_escalation_log e
            SET resolved_at = NOW()
            WHERE e.resolved_at IS NULL
              AND EXISTS (
                  SELECT 1 FROM reports r
                  WHERE r.study_instance_uid = e.study_instance_uid
                    AND r.status = 'FINAL'  -- enum NAME is uppercase; 'final' errors
              )
            RETURNING e.id
        """))
        resolved_ids = [str(r[0]) for r in result.fetchall()]
        db.commit()

        if resolved_ids:
            logger.info("Auto-resolved %d escalations: %s", len(resolved_ids), resolved_ids[:5])
        return {"resolved": len(resolved_ids)}

    except Exception as e:
        if db:
            db.rollback()
        logger.error("Auto-resolve failed: %s", e)
        return {"resolved": 0, "error": str(e)}
    finally:
        if db:
            db.close()
