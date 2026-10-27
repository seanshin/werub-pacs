"""Celery beat 태스크 overlap 방지 락 (H1).

beat가 5분마다 같은 태스크를 발행하는데 이전 실행이 안 끝났으면(Orthanc 느림 등)
두 인스턴스가 동시에 같은 study를 처리 → 중복 INSERT/추론/에스컬레이션. Redis NX 락으로
직렬화. TTL은 스케줄 간격보다 짧게(크래시 시 자동만료로 영구 skip 방지).

fail-open: Redis 장애 시 락 획득은 True로 간주(태스크를 막지 않음 — 락은 최적화이지
정확성 요건이 아님).
"""
import logging

import redis as sync_redis

from app.core.config import settings

logger = logging.getLogger(__name__)


def _key(name: str) -> str:
    return f"pacs:beatlock:{name}"


def acquire_beat_lock(name: str, ttl: int = 270) -> bool:
    """Redis NX 락 획득. 이미 점유 중이면 False(=skip), 미점유면 True. Redis 장애=True(fail-open)."""
    try:
        r = sync_redis.Redis.from_url(settings.redis_url)
        ok = bool(r.set(_key(name), "1", nx=True, ex=ttl))
        r.close()
        return ok
    except Exception as e:
        logger.warning(f"beat lock acquire failed ({name}), proceeding: {e}")
        return True


def release_beat_lock(name: str):
    try:
        r = sync_redis.Redis.from_url(settings.redis_url)
        r.delete(_key(name))
        r.close()
    except Exception:
        pass
