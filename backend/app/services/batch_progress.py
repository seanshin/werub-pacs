"""Cross-process batch progress bridge (K3).

celery 워커가 FastAPI websocket 모듈(`api/batch_websocket`)을 직접 import하면 워커
startup에서 ImportError(get_async_db)로 크래시 → 배치 정규화 태스크가 아예 실행 불가였음.
해결: celery 태스크는 여기서 **Redis pub/sub로 진행상황을 발행**(sync, FastAPI 의존 없음),
backend의 websocket 엔드포인트가 같은 채널을 구독해 클라이언트로 전달한다.
"""
import json
import logging

import redis as sync_redis

from app.core.config import settings

logger = logging.getLogger(__name__)


def channel(batch_id: str) -> str:
    return f"batch:ws:{batch_id}"


def _publish(batch_id: str, payload: dict):
    try:
        r = sync_redis.Redis.from_url(settings.redis_url)
        r.publish(channel(batch_id), json.dumps(payload, default=str))
        r.close()
    except Exception as e:
        logger.warning(f"batch progress publish failed ({batch_id}): {e}")


def publish_batch_progress(batch_id: str, **kw):
    _publish(batch_id, {"type": "progress", "batch_id": batch_id, **kw})


def publish_batch_complete(batch_id: str, **kw):
    _publish(batch_id, {"type": "complete", "batch_id": batch_id, **kw})


def publish_batch_error(batch_id: str, error: str):
    _publish(batch_id, {"type": "error", "batch_id": batch_id, "error": error})
