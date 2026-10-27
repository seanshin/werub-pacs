"""VRT server-render capability self-test (vrt-rendering §2.4).

Probes the AI server and classifies what server-side rendering modes the
current network supports. The GPU box sits behind an SSH tunnel today
(no-op RTT ~595ms) but a direct high-speed link is planned — this test makes
the capability flip automatically when that link lands, instead of someone
having to remember to re-enable the feature.

Probe detail: one httpx client for all samples, so sample 1 includes
connection setup (cold) and samples 2+ ride the kept-alive connection (warm).
Warm latency approximates what a persistent WS render session would see,
which is why the interactive gate is judged on warm p95.
"""
import json
import logging
import time

import httpx
import redis as sync_redis
from sqlalchemy import text

from app.core.config import settings
from app.services.ai_worker import celery_app, _get_db_session

logger = logging.getLogger(__name__)

CAP_KEY = "pacs:vrt:capability"
OVERRIDE_KEY = "pacs:vrt:override"
INTERACTIVE_GATE_MS = 150   # warm p95 budget for camera-event -> frame loop
SAMPLES = 8


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[max(0, int(len(s) * 0.95) - 1)], 1)


def measure_ai_server_rtt(samples: int = SAMPLES) -> dict:
    """No-op probes against the AI server. Any HTTP response (incl. 405) counts
    as reachable — we are measuring the path, not an endpoint."""
    url = f"{settings.ai_server_url}/api/vrt-probe"
    times: list[float] = []
    reachable = False
    with httpx.Client(timeout=10.0) as client:
        for _ in range(samples):
            t0 = time.perf_counter()
            try:
                client.get(url)
                reachable = True
                times.append((time.perf_counter() - t0) * 1000)
            except Exception as e:
                logger.warning(f"vrt probe failed: {e}")
    cold = round(times[0], 1) if times else None
    warm = times[1:] if len(times) > 1 else []
    return {
        "reachable": reachable,
        "samples": len(times),
        "cold_ms": cold,
        "warm_median_ms": round(sorted(warm)[len(warm) // 2], 1) if warm else None,
        "warm_p95_ms": _p95(warm),
    }


def run_network_test() -> dict:
    m = measure_ai_server_rtt()
    capability = {
        "batch_supported": m["reachable"],
        "interactive_supported": bool(
            m["warm_p95_ms"] is not None and m["warm_p95_ms"] <= INTERACTIVE_GATE_MS
        ),
        "gate_ms": INTERACTIVE_GATE_MS,
        "rtt": m,
        "measured_at": int(time.time()),
    }
    try:
        r = sync_redis.Redis.from_url(settings.redis_url, decode_responses=True)
        r.set(CAP_KEY, json.dumps(capability))
    except Exception as e:
        logger.error(f"vrt capability store failed: {e}")
    return capability


def merge_override(capability: dict, override_raw: str | None) -> dict:
    """Admin override wins over the measured verdict (null/absent = auto)."""
    out = dict(capability)
    out["override"] = None
    if override_raw:
        try:
            ov = json.loads(override_raw)
            if isinstance(ov.get("interactive_supported"), bool):
                out["interactive_supported"] = ov["interactive_supported"]
                out["override"] = ov
        except Exception:
            pass
    return out


@celery_app.task(bind=True, max_retries=0)
def vrt_network_check(self):
    """Daily re-measure; notify admins when the verdict changes (e.g. the
    planned direct link gets installed and interactive flips on)."""
    try:
        r = sync_redis.Redis.from_url(settings.redis_url, decode_responses=True)
        prev_raw = r.get(CAP_KEY)
        prev = json.loads(prev_raw) if prev_raw else None
    except Exception:
        prev = None

    cap = run_network_test()
    changed = prev is not None and (
        prev.get("interactive_supported") != cap["interactive_supported"]
        or prev.get("batch_supported") != cap["batch_supported"]
    )
    if not changed:
        return {**cap, "notified": False}

    db = _get_db_session()
    if db:
        try:
            import uuid
            msg = (
                f"서버 렌더 네트워크 판정 변경 — 대화형: {cap['interactive_supported']}, "
                f"배치: {cap['batch_supported']} (warm p95 {cap['rtt']['warm_p95_ms']}ms)"
            )
            db.execute(text("""
                INSERT INTO notifications (id, type, title, message, urgency, target_role,
                    study_instance_uid, action_url, is_read, acknowledged, created_at)
                VALUES (:id, 'vrt_capability', :title, :msg, 'normal', 'admin',
                        NULL, '/pacs-admin/notifications', false, false, NOW())
            """), {"id": str(uuid.uuid4()), "title": "서버 렌더 지원 상태 변경", "msg": msg})
            db.commit()
        except Exception as e:
            logger.error(f"vrt capability notification failed: {e}")
        finally:
            db.close()
    logger.info(f"vrt capability changed: {cap}")
    return {**cap, "notified": True}
