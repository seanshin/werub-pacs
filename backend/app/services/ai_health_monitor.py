"""AI 서버 가용성 감시 (pacs-fundamentals 2축 — 운영 가시성).

계기(2026-08-03 실측): `ai_server_url`(당시 https://example.org/ollama)이 전 경로
404로 사라졌는데 **2주 넘게 아무 신호도 없었다** — 추론 잡 0건, 선제 스크리닝은
`{'queued': 0}`로 정상 성공 보고, 에러 로그 0. 백업·호스트 디스크는 감시하면서
정작 **전 AI 기능(추론·선제 스크리닝·거버넌스·ai_assist·정규화 AI)이 공유하는
단일 의존성**은 무감시였다.

설계:
- 30분 beat가 `{ai_server_url}/api/tags`(Ollama 표준 목록 EP)를 GET → 상태 판정.
- 알림은 **상태 전이에서만**(down 진입 / 복구) — 매 주기 재발송하면 거버넌스
  준수 알림처럼 알림 피로가 된다. Redis에 마지막 상태를 두고 변화 시에만 통지.
- 판정은 순수 함수(`classify_ai_probe`)로 분리해 system_health(async)와 공유.
- 실패해도 태스크는 예외를 올리지 않는다(감시가 큐를 오염시키면 안 됨).
"""
import json
import logging
import time
import uuid

import httpx
import redis as sync_redis
from sqlalchemy import text

from app.core.config import settings
from app.services.ai_worker import celery_app, _get_db_session

logger = logging.getLogger(__name__)

STATE_KEY = "pacs:ai_server:state"       # 마지막 통지 상태(ok/bad) — 전이 감지용
STATUS_KEY = "pacs:ai_server:status"     # 마지막 프로브 결과 전체 — health-detail이 읽음
STATE_TTL = 30 * 24 * 3600
STALE_AFTER_SEC = 2 * 3600               # 30분 beat 기준 넉넉한 유예(워커 정지 감지)
PROBE_PATH = "/api/tags"                 # Ollama 모델 목록 — 인증 불요·부작용 없음
PROBE_TIMEOUT = 10.0


def classify_ai_status(raw: str | None) -> dict:
    """저장된 마지막 프로브 결과 → health-detail용 상태.

    health-detail이 매 호출마다 외부를 프로브하면 응답이 외부 장애에 물린다.
    beat가 남긴 결과를 읽되, 결과 자체가 낡았으면(워커 정지) 그 사실을 드러낸다."""
    if not raw:
        return {"status": "unknown", "detail": "아직 프로브 기록 없음"}
    try:
        st = json.loads(raw)
    except Exception:
        return {"status": "unknown", "detail": "unparseable status"}
    age = time.time() - float(st.get("ts", 0))
    st["age_minutes"] = round(age / 60, 1)
    if age > STALE_AFTER_SEC and st.get("status") != "not_configured":
        st["status"] = "stale"
        st["detail"] = f"마지막 프로브 {st['age_minutes']}분 전 — 감시 태스크 확인 필요"
    return st


def classify_ai_probe(status_code: int | None, elapsed_ms: int | None,
                      err: str | None = None, model_count: int | None = None) -> dict:
    """프로브 결과 → 상태. 순수 함수(beat·health API 공유)."""
    if err is not None:
        return {"status": "down", "reason": "unreachable", "detail": err[:200]}
    if status_code != 200:
        # 404는 "호스트는 살아있는데 AI 경로가 사라짐" — 실제로 겪은 형태라 구분한다
        reason = "path_not_found" if status_code == 404 else "http_error"
        return {"status": "down", "reason": reason, "http_status": status_code,
                "latency_ms": elapsed_ms}
    if model_count == 0:
        # 200인데 모델이 0 — 엉뚱한 서비스가 같은 경로를 점유했을 수 있다
        return {"status": "degraded", "reason": "no_models",
                "http_status": 200, "latency_ms": elapsed_ms, "model_count": 0}
    return {"status": "ok", "http_status": 200, "latency_ms": elapsed_ms,
            "model_count": model_count}


def _parse_model_count(payload) -> int | None:
    """Ollama /api/tags = {"models": [...]}. 다른 서비스가 점유하면 None."""
    if not isinstance(payload, dict):
        return None
    models = payload.get("models")
    return len(models) if isinstance(models, list) else None


def probe_ai_server(url: str | None = None, timeout: float = PROBE_TIMEOUT) -> dict:
    """동기 프로브(Celery 컨텍스트). 반환에 target을 담아 알림에서 주소를 밝힌다."""
    base = (url or settings.ai_server_url or "").rstrip("/")
    if not base:
        return {"status": "not_configured", "target": ""}
    target = f"{base}{PROBE_PATH}"
    t0 = time.monotonic()
    try:
        resp = httpx.get(target, timeout=timeout, follow_redirects=True)
    except Exception as e:
        return {**classify_ai_probe(None, None, err=f"{type(e).__name__}: {e}"),
                "target": target}
    elapsed = int((time.monotonic() - t0) * 1000)
    count = None
    if resp.status_code == 200:
        try:
            count = _parse_model_count(resp.json())
        except Exception:
            count = None
    return {**classify_ai_probe(resp.status_code, elapsed, model_count=count),
            "target": target}


def _notify_admin(title: str, msg: str, urgency: str) -> str:
    db = _get_db_session()
    if not db:
        logger.error("ai_server alert: DB unavailable — %s", msg)
        return "db_unavailable"
    try:
        db.execute(text("""
            INSERT INTO notifications (id, type, title, message, urgency, target_role,
                study_instance_uid, action_url, is_read, acknowledged, created_at)
            VALUES (:id, 'ai_server_alert', :title, :msg, :urgency, 'admin',
                    NULL, '/pacs-admin/notifications', false, false, NOW())
        """), {"id": str(uuid.uuid4()), "title": title, "msg": msg, "urgency": urgency})
        db.commit()
        logger.warning("ai_server alert created: %s", msg)
        return "created"
    except Exception as e:
        logger.error("ai_server alert insert failed: %s", e)
        return f"error: {e}"
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=0)
def check_ai_server(self):
    """AI 서버 프로브 → 상태 **전이** 시에만 admin 알림."""
    st = {**probe_ai_server(), "ts": time.time()}

    # health-detail이 읽을 마지막 결과는 상태와 무관하게 항상 남긴다
    try:
        r = sync_redis.Redis.from_url(settings.redis_url, decode_responses=True)
        r.set(STATUS_KEY, json.dumps(st), ex=STATE_TTL)
    except Exception as e:
        logger.warning("ai_server status store unavailable: %s", e)
        return {**st, "alert": "state_unavailable"}

    if st["status"] == "not_configured":
        return st                     # 미설정은 의도적 무음(설치 초기)

    # down/degraded는 하나의 "이상" 상태로 묶어 전이를 판정
    cur = "ok" if st["status"] == "ok" else "bad"
    try:
        prev = r.get(STATE_KEY)
        r.set(STATE_KEY, cur, ex=STATE_TTL)
    except Exception as e:
        logger.warning("ai_server state store unavailable: %s", e)
        return {**st, "alert": "state_unavailable"}

    if prev == cur:
        return {**st, "alert": "suppressed"}   # 상태 유지 → 재발송 안 함

    if cur == "bad":
        detail = st.get("detail") or f"HTTP {st.get('http_status')}"
        alert = _notify_admin(
            "AI 서버 응답 이상",
            f"AI 서버에 접근할 수 없습니다 ({st['target']} — {st['reason']}: {detail}). "
            f"추론·선제 스크리닝·판독 보조·AI 거버넌스가 모두 중단됩니다. "
            f"AI_SERVER_URL 설정과 서버 상태를 확인하세요.",
            "high")
    elif prev is None:
        # 첫 관측이 정상이면 통지 불필요(부팅 때마다 알림이 뜨는 것 방지)
        return {**st, "alert": "baseline"}
    else:
        alert = _notify_admin(
            "AI 서버 복구",
            f"AI 서버가 정상 응답합니다 ({st['target']}, 모델 {st.get('model_count')}개, "
            f"{st.get('latency_ms')}ms).",
            "normal")
    return {**st, "alert": alert, "transition": f"{prev}→{cur}"}
