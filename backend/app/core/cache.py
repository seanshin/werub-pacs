"""Redis Cache Manager and Decorators

Provides AsyncRedis connection management, caching decorators, and cache utilities
for all OpenPACS caching strategies (worklist, permissions, Orthanc metadata, AI models).
"""

import asyncio
import hashlib
import json
import logging
from functools import wraps
from typing import Any, Callable, Optional

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.cache_config import (
    CACHE_NAMESPACE,
    CACHE_TTL_WORKLIST,
    CACHE_TTL_PERMISSIONS,
    CACHE_TTL_ORTHANC,
    CACHE_TTL_MODELS,
)

logger = logging.getLogger(__name__)


class CacheManager:
    """Singleton Redis cache manager with health checks and graceful fallback."""

    _instance: Optional["CacheManager"] = None
    _redis: Optional[Redis] = None
    available: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def connect(self, redis_url: str) -> None:
        """Connect to Redis at startup."""
        try:
            self._redis = await aioredis.from_url(redis_url, decode_responses=True)
            # Test connection
            await self._redis.ping()
            self.available = True
            logger.info("✅ Redis cache connected")
        except Exception as e:
            logger.warning(f"⚠️ Redis connection failed: {e}. Cache unavailable, will fallback to DB.")
            self.available = False

    async def disconnect(self) -> None:
        """Close Redis connection at shutdown."""
        if self._redis:
            try:
                await self._redis.close()
                logger.info("Redis cache disconnected")
            except Exception as e:
                logger.warning(f"Error closing Redis: {e}")

    async def get(self, key: str) -> Optional[str]:
        """Get value from cache. Returns None if not found or Redis unavailable."""
        if not self.available or not self._redis:
            return None

        try:
            value = await asyncio.wait_for(self._redis.get(key), timeout=0.5)
            return value
        except asyncio.TimeoutError:
            logger.warning(f"Redis timeout on GET {key}")
            return None
        except RedisError as e:
            logger.warning(f"Redis error on GET {key}: {e}")
            self.available = False
            return None

    async def set(self, key: str, value: str, ttl: int = 300) -> bool:
        """Set value in cache with TTL. Returns True if successful."""
        if not self.available or not self._redis:
            return False

        try:
            await asyncio.wait_for(
                self._redis.setex(key, ttl, value),
                timeout=0.5
            )
            return True
        except asyncio.TimeoutError:
            logger.warning(f"Redis timeout on SET {key}")
            return False
        except RedisError as e:
            logger.warning(f"Redis error on SET {key}: {e}")
            self.available = False
            return False

    async def delete(self, *keys: str) -> bool:
        """Delete keys from cache. Returns True if at least one key deleted."""
        if not self.available or not self._redis or not keys:
            return False

        try:
            result = await asyncio.wait_for(
                self._redis.delete(*keys),
                timeout=0.5
            )
            return result > 0
        except asyncio.TimeoutError:
            logger.warning(f"Redis timeout on DELETE {keys}")
            return False
        except RedisError as e:
            logger.warning(f"Redis error on DELETE {keys}: {e}")
            self.available = False
            return False

    async def keys(self, pattern: str) -> list:
        """Get keys matching pattern. Returns empty list if Redis unavailable."""
        if not self.available or not self._redis:
            return []

        try:
            keys = await asyncio.wait_for(
                self._redis.keys(pattern),
                timeout=1.0
            )
            return keys
        except asyncio.TimeoutError:
            logger.warning(f"Redis timeout on KEYS {pattern}")
            return []
        except RedisError as e:
            logger.warning(f"Redis error on KEYS {pattern}: {e}")
            self.available = False
            return []

    async def info(self, section: str = "memory") -> dict:
        """Get Redis info. Returns empty dict if unavailable."""
        if not self.available or not self._redis:
            return {}

        try:
            return await asyncio.wait_for(
                self._redis.info(section),
                timeout=1.0
            )
        except (asyncio.TimeoutError, RedisError) as e:
            logger.warning(f"Redis error on INFO {section}: {e}")
            return {}


# Global cache manager instance
_cache_manager = CacheManager()


def get_cache_manager() -> CacheManager:
    """Get the global cache manager instance."""
    return _cache_manager


def calculate_query_hash(
    modality: Optional[str] = None,
    status: Optional[str] = None,
    patient_name: Optional[str] = None,
    sort_by: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> str:
    """
    Calculate deterministic hash of query parameters.
    Returns 12-character hex string.
    """
    params = f"{modality}:{status}:{patient_name}:{sort_by}:{page}:{limit}"
    return hashlib.md5(params.encode()).hexdigest()[:12]


def cached(
    ttl: int = CACHE_TTL_WORKLIST,
    key_prefix: str = None,
    include_params: list = None,
):
    """
    Decorator to cache function results with specified TTL.

    Usage:
        @cached(ttl=300, key_prefix='worklist', include_params=['scheduled_date', 'modality', 'status_filter', 'limit', 'offset'])
        async def list_worklist(scheduled_date, modality, ..., user):
            return {...}

    Args:
        ttl: Time-to-live in seconds
        key_prefix: Cache key prefix (e.g., 'worklist', 'permissions')
        include_params: List of parameter names to include in cache key hash. If None, uses all kwargs except 'user' and 'db'.

    The cache key is constructed as: {NAMESPACE}{key_prefix}:{user_id}:{query_hash}
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            cache_mgr = get_cache_manager()

            # Extract user_id and create cache key
            # (assumes 'user' is in kwargs as User object with .id attribute)
            user = kwargs.get("user")
            if not user or not hasattr(user, "id"):
                # No user context, skip caching
                return await func(*args, **kwargs)

            user_id = str(user.id)

            # Create cache key from function params
            # Determine which parameters to include in hash
            params_to_include = include_params or [
                k for k in kwargs.keys() if k not in ["user", "db"]
            ]

            # Build query hash from specified parameters
            hash_parts = []
            for param_name in sorted(params_to_include):
                value = kwargs.get(param_name)
                if value is not None:
                    # Convert date/time objects to strings for hashing
                    if hasattr(value, "isoformat"):
                        value = value.isoformat()
                    hash_parts.append(f"{param_name}={value}")

            query_string = "|".join(hash_parts) or "default"
            query_hash = hashlib.md5(query_string.encode()).hexdigest()[:12]

            cache_key = f"{CACHE_NAMESPACE}{key_prefix}:{user_id}:{query_hash}"

            # Try to get from cache
            try:
                cached_data = await cache_mgr.get(cache_key)
                if cached_data:
                    logger.debug(f"Cache HIT: {cache_key}")
                    return json.loads(cached_data)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Error deserializing cache {cache_key}: {e}")

            # Cache miss - call function
            result = await func(*args, **kwargs)

            # Store in cache (non-blocking)
            if result is not None:
                try:
                    json_data = json.dumps(result, default=str)
                    await cache_mgr.set(cache_key, json_data, ttl=ttl)
                    logger.debug(f"Cache SET: {cache_key}")
                except (json.JSONEncodeError, Exception) as e:
                    logger.warning(f"Error caching result for {cache_key}: {e}")

            return result

        return wrapper

    return decorator


def invalidate_on_write(*patterns: str):
    """
    Decorator to invalidate cache patterns after successful function execution.

    Usage:
        @invalidate_on_write('pacs:worklist:*', 'pacs:orthanc:*')
        async def create_study(...):
            # Implementation
            return result
            # After return, specified patterns are invalidated

    Args:
        *patterns: Cache key patterns to invalidate (e.g., 'pacs:worklist:*')
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Call the function first
            result = await func(*args, **kwargs)

            # On success, invalidate patterns
            cache_mgr = get_cache_manager()
            for pattern in patterns:
                try:
                    keys = await cache_mgr.keys(pattern)
                    if keys:
                        await cache_mgr.delete(*keys)
                        logger.debug(f"Cache INVALIDATE: {pattern} ({len(keys)} keys)")
                except Exception as e:
                    logger.warning(f"Error invalidating cache pattern {pattern}: {e}")

            return result

        return wrapper

    return decorator


async def get_cached(
    key: str,
    source_fn: Callable,
    ttl: int = CACHE_TTL_ORTHANC,
    fallback_to_source: bool = True,
) -> Any:
    """
    Get value from cache, fall back to source function if miss.

    Args:
        key: Cache key
        source_fn: Async function to call on cache miss
        ttl: Time-to-live for cache entry
        fallback_to_source: If False, return None on cache miss

    Returns:
        Cached or sourced data
    """
    cache_mgr = get_cache_manager()

    # Try to get from cache
    try:
        cached_data = await cache_mgr.get(key)
        if cached_data:
            logger.debug(f"Cache HIT: {key}")
            return json.loads(cached_data)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Error reading cache {key}: {e}")

    # Cache miss - call source
    if not fallback_to_source:
        return None

    data = await source_fn()

    # Store in cache (non-blocking, don't block on slow cache)
    if data is not None:
        try:
            json_data = json.dumps(data, default=str)
            await asyncio.wait_for(
                cache_mgr.set(key, json_data, ttl=ttl),
                timeout=0.5
            )
            logger.debug(f"Cache SET: {key}")
        except (asyncio.TimeoutError, json.JSONEncodeError, Exception) as e:
            logger.warning(f"Error caching {key}: {e}")

    return data


async def purge_pattern(pattern: str) -> int:
    """
    Purge all keys matching pattern.

    Args:
        pattern: Cache key pattern (e.g., 'pacs:worklist:*')

    Returns:
        Number of keys deleted
    """
    cache_mgr = get_cache_manager()

    try:
        keys = await cache_mgr.keys(pattern)
        if keys:
            await cache_mgr.delete(*keys)
            logger.info(f"Purged {len(keys)} cache keys matching {pattern}")
            return len(keys)
        return 0
    except Exception as e:
        logger.warning(f"Error purging cache pattern {pattern}: {e}")
        return 0


async def purge_all() -> int:
    """Purge all PACS cache keys."""
    return await purge_pattern(f"{CACHE_NAMESPACE}*")
