"""Opportunistic AI screening worker (opportunistic-ai feature).

Proactively runs a modality-mapped AI model on every incoming study (the
2025-26 PACS trend, vs OpenPACS's on-demand AI) and alerts the reader on
actionable findings. Reuses the existing scan pattern + run_inference +
notification — the screener only creates jobs and collects/notifies results.

One beat task does both phases each cycle:
  (A) scan new studies -> create opportunistic InferenceJob -> run_inference.delay
  (B) collect completed opportunistic screenings -> mark actionable -> notify
"""
import json
import logging
import uuid
from datetime import datetime, timezone

import redis as sync_redis
from sqlalchemy import text

from app.core.config import settings
from app.services.ai_worker import celery_app, _get_orthanc_client
from app.services.dicom_auto_validate import _get_sync_db

logger = logging.getLogger(__name__)

CONFIG_KEY = "pacs:screening:config"

# Default modality -> screening model. Overridable via Redis config. Empty/None
# value or unmapped modality = skip. Falls back to AIModel registry by modality.
DEFAULT_MODALITY_MODEL = {
    "CR": "chest-xray-analyzer",
    "DX": "chest-xray-analyzer",
    "CT": None,   # registry pick
    "MR": None,
    # US/OT/MG/RF skipped by default (no value)
}


def _get_redis():
    return sync_redis.Redis.from_url(settings.redis_url, decode_responses=True)


def get_screening_config() -> dict:
    cfg = {
        "enabled": settings.screening_enabled,
        "actionable_confidence": settings.screening_actionable_confidence,
        "max_per_scan": settings.screening_max_per_scan,
        "modality_model": dict(DEFAULT_MODALITY_MODEL),
    }
    try:
        raw = _get_redis().get(CONFIG_KEY)
        if raw:
            ov = json.loads(raw)
            for k in ("enabled", "actionable_confidence", "max_per_scan"):
                if k in ov:
                    cfg[k] = ov[k]
            if isinstance(ov.get("modality_model"), dict):
                cfg["modality_model"].update(ov["modality_model"])
    except Exception as e:
        logger.warning(f"screening config read failed, defaults: {e}")
    return cfg


def _primary_modality(modalities: str) -> str:
    # ModalitiesInStudy like "CT\\SR" or "CR" — take the first imaging one
    for m in (modalities or "").replace("\\", ",").split(","):
        m = m.strip().upper()
        if m and m not in ("SR", "KO", "PR"):
            return m
    return (modalities or "").split(",")[0].strip().upper()


def _pick_model(db, modality: str, cfg: dict):
    """Return (model_id, model_name) for the modality, or None to skip."""
    mapped = cfg["modality_model"].get(modality, "__unset__")
    if mapped == "__unset__":
        # modality not configured at all -> skip
        return None
    if mapped:
        row = db.execute(text(
            "SELECT id, name FROM ai_models WHERE name = :n AND is_active = true"
        ), {"n": mapped}).first()
        if row:
            return (str(row[0]), row[1])
    # config said screen this modality but no explicit/active model -> registry pick
    row = db.execute(text("""
        SELECT id, name FROM ai_models
        WHERE is_active = true AND modalities LIKE :m
        ORDER BY total_runs DESC LIMIT 1
    """), {"m": f"%{modality}%"}).first()
    return (str(row[0]), row[1]) if row else None


def _alert_target(db, study_uid: str):
    """Reader to alert: assigned reader -> on-call -> role fallback."""
    row = db.execute(text("""
        SELECT assigned_to_username FROM reading_assignments
        WHERE study_instance_uid = :s AND is_current = true AND status != 'completed'
        ORDER BY assigned_at DESC LIMIT 1
    """), {"s": study_uid}).first()
    if row and row[0]:
        return row[0]
    now = datetime.now(timezone.utc)
    row = db.execute(text("""
        SELECT radiologist_username FROM oncall_schedule
        WHERE schedule_date = :d AND start_time <= :t AND end_time >= :t
        ORDER BY is_primary DESC LIMIT 1
    """), {"d": now.date(), "t": now.time().replace(microsecond=0)}).first()
    return row[0] if row and row[0] else None  # None -> role-only notification


@celery_app.task(name="app.services.opportunistic_screener.scan_and_collect",
                 bind=True, max_retries=1)
def scan_and_collect(self):
    cfg = get_screening_config()
    if not cfg["enabled"]:
        return {"enabled": False}

    from app.services.beat_lock import acquire_beat_lock, release_beat_lock
    if not acquire_beat_lock("opportunistic_screener"):
        logger.info("opportunistic_screener: previous run still active, skipping")
        return {"skipped": "locked"}

    client = _get_orthanc_client()
    db = _get_sync_db()
    queued, notified = 0, 0
    try:
        # ── (A) scan new studies ────────────────────────────────────────────
        # K5: 언바운드 set 금지 — 최근 50 study만 스캔하므로 최근 screening 5천건이면 충분
        seen = {r[0] for r in db.execute(text(
            "SELECT study_instance_uid FROM ai_screening_results ORDER BY screened_at DESC LIMIT 5000"
        )).all()}
        resp = client.get("/studies", params={"since": 0, "limit": 50})
        study_ids = resp.json() if resp.status_code == 200 else []
        for sid in study_ids:
            if queued >= cfg["max_per_scan"]:
                break
            try:
                sr = client.get(f"/studies/{sid}")
                if sr.status_code != 200:
                    continue
                sd = sr.json()
                tags = sd.get("MainDicomTags", {})
                uid = tags.get("StudyInstanceUID", "")
                if not uid or uid in seen:
                    continue
                modality = _primary_modality(tags.get("ModalitiesInStudy", ""))
                if not modality:
                    # Study-level ModalitiesInStudy is often absent in Orthanc;
                    # fall back to the first series' Modality (0008,0060).
                    series = sd.get("Series", [])
                    if series:
                        try:
                            ser = client.get(f"/series/{series[0]}")
                            if ser.status_code == 200:
                                modality = (ser.json().get("MainDicomTags", {})
                                            .get("Modality", "") or "").strip().upper()
                        except Exception:
                            pass
                pick = _pick_model(db, modality, cfg)
                if not pick:
                    db.execute(text("""
                        INSERT INTO ai_screening_results
                            (id, study_instance_uid, modality, status)
                        VALUES (:id, :uid, :mod, 'skipped')
                        ON CONFLICT (study_instance_uid) DO NOTHING
                    """), {"id": str(uuid.uuid4()), "uid": uid, "mod": modality})
                    db.commit()
                    seen.add(uid)
                    continue
                model_id, model_name = pick
                job_id = str(uuid.uuid4())
                db.execute(text("""
                    INSERT INTO inference_jobs
                        (id, model_id, model_name, study_instance_uid, orthanc_study_id,
                         status, priority, progress, retry_count, findings_count, is_critical,
                         trigger_type, requested_by, created_at, updated_at)
                    VALUES (:id, :mid, :mn, :uid, :oid, 'QUEUED', 'LOW', 0, 0, 0, false,
                            'opportunistic', 'system', NOW(), NOW())
                """), {"id": job_id, "mid": model_id, "mn": model_name,
                       "uid": uid, "oid": sid})
                db.execute(text("""
                    INSERT INTO ai_screening_results
                        (id, study_instance_uid, modality, model_name, inference_job_id, status)
                    VALUES (:id, :uid, :mod, :mn, :jid, 'pending')
                    ON CONFLICT (study_instance_uid) DO NOTHING
                """), {"id": str(uuid.uuid4()), "uid": uid, "mod": modality,
                       "mn": model_name, "jid": job_id})
                db.commit()
                seen.add(uid)
                try:
                    from app.services.ai_worker import run_inference
                    run_inference.delay(job_id)
                except Exception as e:
                    logger.warning(f"screening enqueue failed {uid}: {e}")
                queued += 1
            except Exception as e:
                # rollback 필수 — INSERT 부분실패가 세션을 abort시키면 다음 study부터
                # 전부 실패(연쇄). 단일 sync 세션 재사용이라 rollback 없이는 스캔 전량 중단.
                db.rollback()
                logger.warning(f"screening scan study {sid} failed: {e}")
                continue

        # ── (B) collect completed screenings → notify ──────────────────────
        pending = db.execute(text("""
            SELECT s.id, s.study_instance_uid, s.inference_job_id,
                   j.status, j.is_critical, j.max_confidence, j.results
            FROM ai_screening_results s
            JOIN inference_jobs j ON j.id = s.inference_job_id
            WHERE s.status = 'pending'
        """)).mappings().all()
        for s in pending:
            jstatus = s["status"]  # job_status_enum stores NAMES (uppercase)
            if jstatus not in ("COMPLETED", "FAILED"):
                continue
            if jstatus == "FAILED":
                db.execute(text(
                    "UPDATE ai_screening_results SET status='failed', completed_at=NOW() WHERE id=:id"
                ), {"id": s["id"]})
                db.commit()
                continue
            is_crit = bool(s["is_critical"])
            conf = float(s["max_confidence"] or 0)
            actionable = is_crit or conf >= cfg["actionable_confidence"]
            db.execute(text("""
                UPDATE ai_screening_results
                SET status='done', is_actionable=:a, is_critical=:c, max_confidence=:f,
                    findings=:fd, completed_at=NOW()
                WHERE id=:id
            """), {"a": actionable, "c": is_crit, "f": conf,
                   "fd": json.dumps((s["results"] or {}).get("findings", [])),
                   "id": s["id"]})
            if actionable:
                _notify_actionable(db, s["study_instance_uid"], is_crit, conf)
                db.execute(text(
                    "UPDATE ai_screening_results SET notified=true WHERE id=:id"
                ), {"id": s["id"]})
                notified += 1
            db.commit()

        logger.info(f"opportunistic screening: queued={queued}, notified={notified}")
        return {"queued": queued, "notified": notified}
    except Exception as e:
        logger.error(f"scan_and_collect failed: {e}")
        return {"error": str(e)[:200]}
    finally:
        release_beat_lock("opportunistic_screener")
        client.close()
        db.close()


def _notify_actionable(db, study_uid: str, is_critical: bool, conf: float):
    target = _alert_target(db, study_uid)
    urgency = "urgent" if is_critical else "non_urgent"
    msg = (f"AI 선제 스크리닝(참고용 — 판독 대체 아님): "
           f"{'위험 ' if is_critical else ''}소견 가능성 (신뢰도 {conf:.0%}). 확인 바랍니다.")
    db.execute(text("""
        INSERT INTO notifications (id, type, title, message, urgency, target_role,
            target_username, study_instance_uid, action_url, is_read, acknowledged, created_at)
        VALUES (:id, 'ai_screening', :title, :msg, :urg, 'radiologist',
                :user, :uid, :url, false, false, NOW())
    """), {"id": str(uuid.uuid4()), "title": "AI 선제 스크리닝 알림", "msg": msg,
           "urg": urgency, "user": target, "uid": study_uid,
           "url": f"/pacs-admin/reading/view?study={study_uid}"})
