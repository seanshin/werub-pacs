"""Orthanc REST API Client with Redis Caching

Wraps httpx AsyncClient to add transparent caching of Orthanc metadata queries
(studies, series, patient data, etc.) with configurable TTL and invalidation.
"""

import json
import logging
from typing import Any, Optional

import httpx

from app.core.cache import get_cache_manager
from app.core.cache_config import (
    CACHE_KEY_ORTHANC_STUDIES,
    CACHE_KEY_ORTHANC_SERIES,
    CACHE_NAMESPACE,
    CACHE_TTL_ORTHANC,
)

logger = logging.getLogger(__name__)


class OrthancCachedClient:
    """
    Cached wrapper around Orthanc REST API client.

    Caches study and series metadata with 1-hour TTL to reduce load on Orthanc
    and improve query latency for DICOMweb and worklist endpoints.
    """

    def __init__(self, http_client: httpx.AsyncClient):
        """
        Initialize Orthanc cached client.

        Args:
            http_client: httpx.AsyncClient configured with Orthanc base URL and auth
        """
        self.http_client = http_client
        self.cache = get_cache_manager()

    async def get_study_metadata(
        self,
        study_id: str,
        use_cache: bool = True,
        ttl: int = CACHE_TTL_ORTHANC,
    ) -> Optional[dict]:
        """
        Get study metadata from Orthanc with optional caching.

        Args:
            study_id: Orthanc study UUID
            use_cache: If True, check cache before querying Orthanc
            ttl: Cache TTL in seconds (default 1 hour)

        Returns:
            Study metadata dict or None if not found
        """
        cache_key = f"{CACHE_KEY_ORTHANC_STUDIES}:{study_id}"

        # Try cache first
        if use_cache:
            cached_data = await self.cache.get(cache_key)
            if cached_data:
                try:
                    logger.debug(f"Orthanc cache HIT: {study_id}")
                    return json.loads(cached_data)
                except json.JSONDecodeError as e:
                    logger.warning(f"Error deserializing cached study {study_id}: {e}")

        # Cache miss - query Orthanc
        try:
            response = await self.http_client.get(f"/studies/{study_id}")
            if response.status_code == 404:
                return None

            response.raise_for_status()
            metadata = response.json()

            # Store in cache
            try:
                await self.cache.set(
                    cache_key,
                    json.dumps(metadata, default=str),
                    ttl=ttl,
                )
                logger.debug(f"Orthanc cache SET: {study_id}")
            except Exception as e:
                logger.warning(f"Error caching study {study_id}: {e}")

            return metadata

        except httpx.HTTPError as e:
            logger.error(f"Error fetching study {study_id} from Orthanc: {e}")
            return None

    async def get_series_metadata(
        self,
        series_id: str,
        use_cache: bool = True,
        ttl: int = CACHE_TTL_ORTHANC,
    ) -> Optional[dict]:
        """
        Get series metadata from Orthanc with optional caching.

        Args:
            series_id: Orthanc series UUID
            use_cache: If True, check cache before querying Orthanc
            ttl: Cache TTL in seconds (default 1 hour)

        Returns:
            Series metadata dict or None if not found
        """
        cache_key = f"{CACHE_KEY_ORTHANC_SERIES}:{series_id}"

        # Try cache first
        if use_cache:
            cached_data = await self.cache.get(cache_key)
            if cached_data:
                try:
                    logger.debug(f"Orthanc cache HIT: {series_id}")
                    return json.loads(cached_data)
                except json.JSONDecodeError as e:
                    logger.warning(f"Error deserializing cached series {series_id}: {e}")

        # Cache miss - query Orthanc
        try:
            response = await self.http_client.get(f"/series/{series_id}")
            if response.status_code == 404:
                return None

            response.raise_for_status()
            metadata = response.json()

            # Store in cache
            try:
                await self.cache.set(
                    cache_key,
                    json.dumps(metadata, default=str),
                    ttl=ttl,
                )
                logger.debug(f"Orthanc cache SET: {series_id}")
            except Exception as e:
                logger.warning(f"Error caching series {series_id}: {e}")

            return metadata

        except httpx.HTTPError as e:
            logger.error(f"Error fetching series {series_id} from Orthanc: {e}")
            return None

    async def get_series_list(
        self,
        study_id: str,
        use_cache: bool = True,
        ttl: int = CACHE_TTL_ORTHANC,
    ) -> list:
        """
        Get list of series UIDs for a study.

        Args:
            study_id: Orthanc study UUID
            use_cache: If True, check cache before querying Orthanc
            ttl: Cache TTL in seconds (default 1 hour)

        Returns:
            List of series UIDs
        """
        cache_key = f"{CACHE_NAMESPACE}orthanc:studies:{study_id}:series-list"

        # Try cache first
        if use_cache:
            cached_data = await self.cache.get(cache_key)
            if cached_data:
                try:
                    logger.debug(f"Orthanc series list cache HIT: {study_id}")
                    return json.loads(cached_data)
                except json.JSONDecodeError as e:
                    logger.warning(f"Error deserializing cached series list {study_id}: {e}")

        # Cache miss - get from study metadata
        try:
            study_metadata = await self.get_study_metadata(study_id, use_cache=True)
            if not study_metadata:
                return []

            series_list = study_metadata.get("Series", [])

            # Store in cache
            try:
                await self.cache.set(
                    cache_key,
                    json.dumps(series_list, default=str),
                    ttl=ttl,
                )
                logger.debug(f"Orthanc series list cache SET: {study_id}")
            except Exception as e:
                logger.warning(f"Error caching series list {study_id}: {e}")

            return series_list

        except Exception as e:
            logger.error(f"Error fetching series list for study {study_id}: {e}")
            return []

    async def invalidate_study_cache(self, study_id: str) -> int:
        """
        Invalidate all cache entries related to a study.

        Called after STOW-RS upload, study modification, or study deletion
        to ensure fresh metadata on next query.

        Args:
            study_id: Orthanc study UUID

        Returns:
            Number of cache keys deleted
        """
        keys_to_delete = [
            f"{CACHE_KEY_ORTHANC_STUDIES}:{study_id}",
            f"{CACHE_NAMESPACE}orthanc:studies:{study_id}:series-list",
            # Series keys will be invalidated individually by caller if needed
        ]

        count = 0
        for key in keys_to_delete:
            if await self.cache.delete(key):
                count += 1

        if count > 0:
            logger.info(f"Invalidated {count} cache keys for study {study_id}")

        return count

    async def invalidate_series_cache(self, series_id: str) -> bool:
        """
        Invalidate cache entry for a specific series.

        Args:
            series_id: Orthanc series UUID

        Returns:
            True if key was deleted, False otherwise
        """
        cache_key = f"{CACHE_KEY_ORTHANC_SERIES}:{series_id}"
        success = await self.cache.delete(cache_key)

        if success:
            logger.info(f"Invalidated cache key for series {series_id}")

        return success
