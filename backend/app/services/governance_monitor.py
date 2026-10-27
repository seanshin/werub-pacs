"""AI model governance monitor (ai-governance feature).

Daily beat: (1) roll up yesterday's inference_jobs + screening acceptance into
model_performance_daily, (2) detect drift vs a 30-day baseline, (3) check
clinical/research + certification compliance, (4) alert admins on new drift /
SaMD violations. Reuses the established scan/notify infra.

inference_jobs.status stores enum NAMES (COMPLETED/FAILED) — v11.7 lesson.
"""
import json
import logging
import uuid

import redis as sync_redis
from sqlalchemy import text

from app.core.config import settings
from app.services.ai_worker import celery_app
from app.services.dicom_auto_validate import _get_sync_db

logger = logging.getLogger(__name__)

DRIFT_KEY = "pacs:governance:drift"
COMPLIANCE_KEY = "pacs:governance:compliance"
CONFIG_KEY = "pacs:governance:config"
DRIFT_ALERT_LOCK = "pacs:governance:drift_alerted:"
# SaMD 위반 판정 창 — 드리프트 baseline(30d)과 맞춘다. 창이 없으면 과거 1건이
# 영구히 매일 재알림된다(v13.37 수정 계기).
COMPLIANCE_WINDOW_DAYS = 30


def _get_redis():
    return sync_redis.Redis.from_url(settings.redis_url, decode_responses=True)


def get_thresholds() -> dict:
    cfg = {
        "success_drop": settings.governance_drift_success_drop,
        "time_increase": settings.governance_drift_time_increase,
        "acceptance_drop": settings.governance_drift_acceptance_drop,
        "min_samples": settings.governance_min_samples,
        "retention_days": settings.governance_retention_days,
    }
    try:
        raw = _get_redis().get(CONFIG_KEY)
        if raw:
            cfg.update({k: v for k, v in json.loads(raw).items() if k in cfg})
    except Exception as e:
        # Redis 설정 로드 실패 시 기본 임계값으로 — 드리프트 판정이 잘못된 값으로
        # 돌아갈 수 있으니 무음 금지(logger.warning)
        logger.warning(f"governance config load failed, using defaults: {e}")
    return cfg


def _rollup(db, day_expr: str = "CURRENT_DATE - 1"):
    """Upsert one day's per-model rollup. day_expr is a SQL date expression."""
    db.execute(text(f"""
        INSERT INTO model_performance_daily
            (id, day, model_name, total_jobs, completed, failed, success_rate,
             avg_inference_ms, critical_count, screened_actionable,
             acknowledged, dismissed, acceptance_rate)
        SELECT uuid_generate_v4(), j.day, j.model_name, j.total, j.completed, j.failed,
               CASE WHEN j.total > 0 THEN j.completed::float / j.total ELSE NULL END,
               j.avg_ms, j.critical,
               COALESCE(s.actionable, 0), COALESCE(s.ack, 0), COALESCE(s.dis, 0),
               CASE WHEN COALESCE(s.ack,0)+COALESCE(s.dis,0) > 0
                    THEN s.ack::float / (s.ack + s.dis) ELSE NULL END
        FROM (
            SELECT ({day_expr})::date AS day, model_name,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE status='COMPLETED') AS completed,
                   COUNT(*) FILTER (WHERE status='FAILED') AS failed,
                   ROUND(AVG(inference_time_ms) FILTER (WHERE status='COMPLETED'))::int AS avg_ms,
                   COUNT(*) FILTER (WHERE is_critical) AS critical
            FROM inference_jobs
            WHERE created_at::date = ({day_expr})::date
            GROUP BY model_name
        ) j
        LEFT JOIN (
            SELECT model_name,
                   COUNT(*) FILTER (WHERE is_actionable) AS actionable,
                   COUNT(*) FILTER (WHERE acknowledged) AS ack,
                   COUNT(*) FILTER (WHERE dismissed) AS dis
            FROM ai_screening_results
            WHERE screened_at::date = ({day_expr})::date
            GROUP BY model_name
        ) s ON s.model_name = j.model_name
        ON CONFLICT (day, model_name) DO UPDATE SET
            total_jobs=EXCLUDED.total_jobs, completed=EXCLUDED.completed,
            failed=EXCLUDED.failed, success_rate=EXCLUDED.success_rate,
            avg_inference_ms=EXCLUDED.avg_inference_ms, critical_count=EXCLUDED.critical_count,
            screened_actionable=EXCLUDED.screened_actionable,
            acknowledged=EXCLUDED.acknowledged, dismissed=EXCLUDED.dismissed,
            acceptance_rate=EXCLUDED.acceptance_rate
    """))


def _rollup_ondemand(db, day_expr: str = "CURRENT_DATE - 1"):
    """on-demand 수용률은 acceptance_at 기준(검토 시점)으로 독립 집계 — 추론 생성일이
    아니라서 _rollup의 job-생성일 키와 다름. 행 부재 시 NOT NULL 카운트는 0으로 INSERT,
    충돌 시 ondemand 컬럼만 갱신(실제 job 집계 보존)."""
    db.execute(text(f"""
        INSERT INTO model_performance_daily
            (id, day, model_name, total_jobs, completed, failed, critical_count,
             screened_actionable, acknowledged, dismissed,
             ondemand_total, ondemand_accepted, ondemand_acceptance_rate)
        SELECT uuid_generate_v4(), ({day_expr})::date, model_name, 0, 0, 0, 0, 0, 0, 0,
               COUNT(*) FILTER (WHERE acceptance IS NOT NULL),
               COUNT(*) FILTER (WHERE acceptance = 'accepted'),
               CASE WHEN COUNT(*) FILTER (WHERE acceptance IS NOT NULL) > 0
                    THEN COUNT(*) FILTER (WHERE acceptance = 'accepted')::float
                         / COUNT(*) FILTER (WHERE acceptance IS NOT NULL) ELSE NULL END
        FROM inference_jobs
        WHERE trigger_type = 'manual' AND acceptance_at::date = ({day_expr})::date
        GROUP BY model_name
        ON CONFLICT (day, model_name) DO UPDATE SET
            ondemand_total=EXCLUDED.ondemand_total, ondemand_accepted=EXCLUDED.ondemand_accepted,
            ondemand_acceptance_rate=EXCLUDED.ondemand_acceptance_rate
    """))


def _assess_drift(db, th: dict) -> list[dict]:
    """Compare recent 7d vs prior 30d baseline per model."""
    rows = db.execute(text("""
        SELECT model_name,
               AVG(success_rate) FILTER (WHERE day > CURRENT_DATE - 7) AS rec_succ,
               AVG(success_rate) FILTER (WHERE day <= CURRENT_DATE - 7 AND day > CURRENT_DATE - 37) AS base_succ,
               AVG(avg_inference_ms) FILTER (WHERE day > CURRENT_DATE - 7) AS rec_ms,
               AVG(avg_inference_ms) FILTER (WHERE day <= CURRENT_DATE - 7 AND day > CURRENT_DATE - 37) AS base_ms,
               AVG(acceptance_rate) FILTER (WHERE day > CURRENT_DATE - 7) AS rec_acc,
               AVG(acceptance_rate) FILTER (WHERE day <= CURRENT_DATE - 7 AND day > CURRENT_DATE - 37) AS base_acc,
               SUM(total_jobs) FILTER (WHERE day > CURRENT_DATE - 7) AS rec_n,
               SUM(total_jobs) FILTER (WHERE day <= CURRENT_DATE - 7 AND day > CURRENT_DATE - 37) AS base_n
        FROM model_performance_daily
        WHERE day > CURRENT_DATE - 37
        GROUP BY model_name
    """)).mappings().all()
    out = []
    for r in rows:
        rec_n, base_n = r["rec_n"] or 0, r["base_n"] or 0
        if rec_n < th["min_samples"] or base_n < th["min_samples"]:
            out.append({"model": r["model_name"], "status": "insufficient_data",
                        "recent_jobs": rec_n, "baseline_jobs": base_n})
            continue
        reasons = []
        if r["base_succ"] is not None and r["rec_succ"] is not None and \
                (r["base_succ"] - r["rec_succ"]) >= th["success_drop"]:
            reasons.append(f"success -{(r['base_succ']-r['rec_succ'])*100:.0f}pp")
        if r["base_ms"] and r["rec_ms"] and \
                (r["rec_ms"] - r["base_ms"]) / r["base_ms"] >= th["time_increase"]:
            reasons.append(f"latency +{(r['rec_ms']-r['base_ms'])/r['base_ms']*100:.0f}%")
        if r["base_acc"] is not None and r["rec_acc"] is not None and \
                (r["base_acc"] - r["rec_acc"]) >= th["acceptance_drop"]:
            reasons.append(f"acceptance -{(r['base_acc']-r['rec_acc'])*100:.0f}pp")
        out.append({"model": r["model_name"],
                    "status": "drift" if reasons else "ok", "reasons": reasons})
    return out


def _assess_compliance(db, window_days: int = COMPLIANCE_WINDOW_DAYS) -> dict:
    """SaMD 준수 점검.

    ★research_used_clinically는 **최근 window_days 내** 임상 알림만 센다. 원래는
    기간 제한이 없어서, 한 번 발생한 위반이 **영구히 매일 재알림**됐다(2026-08-03
    실측: 2026-06-12자 actionable 1건 때문에 30일간 19회 동일 알림 — 알림 피로로
    정작 새 위반을 묻는다). 드리프트 판정이 7d/30d 창을 쓰는 것과 같은 이유.
    이력 자체는 `_all_time`으로 계속 노출해 "지운 것처럼" 보이지 않게 한다.
    """
    # clinical_use stores the enum NAME (uppercase) — v11.7 lesson. Using the
    # lowercase value here would silently miss every SaMD violation.
    research_clinical = db.execute(text("""
        SELECT DISTINCT m.name FROM ai_models m
        JOIN ai_screening_results s ON s.model_name = m.name
        WHERE m.clinical_use = 'RESEARCH' AND s.is_actionable = true
          AND s.screened_at > now() - make_interval(days => :w)
    """), {"w": window_days}).all()
    research_clinical_all = db.execute(text("""
        SELECT DISTINCT m.name FROM ai_models m
        JOIN ai_screening_results s ON s.model_name = m.name
        WHERE m.clinical_use = 'RESEARCH' AND s.is_actionable = true
    """)).all()
    uncert_clinical = db.execute(text("""
        SELECT name FROM ai_models
        WHERE clinical_use = 'CLINICAL' AND (certification IS NULL OR certification = '')
    """)).all()
    stale = db.execute(text("""
        SELECT m.name FROM ai_models m
        WHERE m.is_active = true AND NOT EXISTS (
            SELECT 1 FROM inference_jobs j
            WHERE j.model_name = m.name AND j.created_at > now() - interval '30 days')
    """)).all()
    return {
        # 알림 대상 = 현재 진행 중인 위반(최근 창)
        "research_used_clinically": [r[0] for r in research_clinical],  # SaMD 위반
        # 이력 — 대시보드가 "과거에 있었음"을 계속 보여줄 수 있도록 별도 유지
        "research_used_clinically_all_time": [r[0] for r in research_clinical_all],
        "compliance_window_days": window_days,
        "uncertified_clinical": [r[0] for r in uncert_clinical],
        "stale_active": [r[0] for r in stale],
    }


def _notify_admin(db, ntype: str, title: str, msg: str):
    db.execute(text("""
        INSERT INTO notifications (id, type, title, message, urgency, target_role,
            study_instance_uid, action_url, is_read, acknowledged, created_at)
        VALUES (:id, :t, :title, :msg, 'high', 'admin', NULL,
                '/pacs-admin/ai', false, false, NOW())
    """), {"id": str(uuid.uuid4()), "t": ntype, "title": title, "msg": msg})


# on-demand 수용률 컬럼 + 거버넌스 액션 로그(자동격리/재활성 이력) 멱등 마이그레이션.
_SCHEMA_DDL = (
    "ALTER TABLE model_performance_daily ADD COLUMN IF NOT EXISTS ondemand_total INT",
    "ALTER TABLE model_performance_daily ADD COLUMN IF NOT EXISTS ondemand_accepted INT",
    "ALTER TABLE model_performance_daily ADD COLUMN IF NOT EXISTS ondemand_acceptance_rate FLOAT",
    """CREATE TABLE IF NOT EXISTS model_governance_actions (
        id UUID PRIMARY KEY,
        model_name TEXT NOT NULL,
        action TEXT NOT NULL,
        reason TEXT,
        actor TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
)


def _ensure_schema(db):
    for ddl in _SCHEMA_DDL:
        try:
            db.execute(text(ddl))
        except Exception:
            db.rollback()
    db.commit()


def _record_action(db, model_name: str, action: str, reason: str, actor: str):
    db.execute(text("""
        INSERT INTO model_governance_actions (id, model_name, action, reason, actor, created_at)
        VALUES (:id, :m, :a, :r, :actor, NOW())
    """), {"id": str(uuid.uuid4()), "m": model_name, "a": action, "r": reason, "actor": actor})


def _quarantine_model(db, model_name: str, reason: str) -> bool:
    """드리프트 서킷브레이커 — 활성 모델만 INACTIVE로 격리(is_active=false → 추론 비선택).
    이미 비활성이면 no-op. status는 enum NAME(대문자)."""
    res = db.execute(text("""
        UPDATE ai_models SET status = 'INACTIVE', is_active = false
        WHERE name = :n AND is_active = true
        RETURNING name
    """), {"n": model_name})
    if res.first():
        _record_action(db, model_name, "auto_quarantine", reason, "governance_monitor")
        return True
    return False


@celery_app.task(name="app.services.governance_monitor.rollup_and_assess",
                 bind=True, max_retries=1)
def rollup_and_assess(self):
    th = get_thresholds()
    db = _get_sync_db()
    try:
        _ensure_schema(db)
        # (1) rollup yesterday + today (today partial, refreshes on next run)
        _rollup(db, "CURRENT_DATE - 1")
        _rollup(db, "CURRENT_DATE")
        _rollup_ondemand(db, "CURRENT_DATE - 1")
        _rollup_ondemand(db, "CURRENT_DATE")
        # retention
        db.execute(text(
            "DELETE FROM model_performance_daily WHERE day < CURRENT_DATE - :d"
        ), {"d": th["retention_days"]})
        db.commit()

        # (2) drift
        drift = _assess_drift(db, th)
        r = _get_redis()
        try:
            r.set(DRIFT_KEY, json.dumps(drift))
        except Exception:
            pass
        quarantined = []
        for d in drift:
            if d.get("status") == "drift":
                reason = ", ".join(d["reasons"])
                # 서킷브레이커: config on이면 드리프트 모델 자동 격리(is_active=false).
                # default off — SaMD 안전, 수동 재활성 필요.
                if settings.governance_auto_quarantine and _quarantine_model(db, d["model"], reason):
                    quarantined.append(d["model"])
                    db.commit()
                    _notify_admin(db, "model_quarantine", "AI 모델 자동 격리",
                                  f"{d['model']} 드리프트({reason}) — 자동 비활성화됨. 재검토 후 재활성 필요")
                    continue
                lock = f"{DRIFT_ALERT_LOCK}{d['model']}"
                if r.set(lock, "1", nx=True, ex=86400):
                    _notify_admin(db, "model_drift", "AI 모델 드리프트 감지",
                                  f"{d['model']}: {reason} — 검토 필요")

        # (3) compliance
        comp = _assess_compliance(db)
        try:
            r.set(COMPLIANCE_KEY, json.dumps(comp))
        except Exception:
            pass
        for name in comp["research_used_clinically"]:
            lock = f"pacs:governance:samd_alerted:{name}"
            if r.set(lock, "1", nx=True, ex=86400):
                _notify_admin(db, "governance_compliance", "SaMD 분리 위반",
                              f"연구용 모델 {name}이 최근 {COMPLIANCE_WINDOW_DAYS}일 내 "
                              f"임상 알림을 생성 — clinical_use 확인 필요")
        db.commit()
        logger.info(f"governance: drift={sum(1 for d in drift if d.get('status')=='drift')}, "
                    f"quarantined={quarantined}, "
                    f"compliance_violations={len(comp['research_used_clinically'])}")
        return {"drift": drift, "quarantined": quarantined, "compliance": comp}
    except Exception as e:
        logger.error(f"rollup_and_assess failed: {e}")
        return {"error": str(e)[:200]}
    finally:
        db.close()
