"""Shared async Redis client for application-wide use.

Provides a singleton ``redis_client`` instance that can be imported by any
module that needs direct Redis access (e.g., ConfigService cache lookups).

Usage::

    from app.core.redis_client import redis_client

    await redis_client.get("my-key")
    await redis_client.set("my-key", "value", ex=300)

The connection is created lazily on first use and is safe to share across
concurrent coroutines (redis.asyncio connection pool handles multiplexing).
"""
from __future__ import annotations

import logging
from typing import Optional

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton client
# ---------------------------------------------------------------------------
# Created once at import time using the configured Redis URL.
# The underlying connection pool connects lazily on first command.
redis_client: aioredis.Redis = aioredis.from_url(
    settings.redis_url,
    decode_responses=True,
    encoding="utf-8",
    socket_connect_timeout=5,
    socket_timeout=5,
    retry_on_timeout=True,
)

def get_redis_client() -> aioredis.Redis:
    """Return the shared Redis client instance."""
    return redis_client


__all__ = ["redis_client", "get_redis_client"]
