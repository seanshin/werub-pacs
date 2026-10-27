"""Redis Cache Configuration

Defines TTL values, cache patterns, and memory limits for all caching strategies.
"""

# Cache namespace to avoid conflicts with Celery keys
CACHE_NAMESPACE = "pacs:"

# TTL values (seconds)
CACHE_TTL_WORKLIST = 300          # 5 minutes - study list queries
CACHE_TTL_PERMISSIONS = 86400     # 24 hours - user permissions (overridden by JWT exp)
CACHE_TTL_ORTHANC = 3600          # 1 hour - Orthanc metadata
CACHE_TTL_MODELS = 86400          # 24 hours - AI model registry

# Redis memory limits
CACHE_MAX_MEMORY = 100_000_000    # 100 MB
CACHE_EVICTION_POLICY = "allkeys-lru"  # Least recently used

# Cache key patterns (for bulk operations)
CACHE_PATTERN_WORKLIST = f"{CACHE_NAMESPACE}worklist:*"
CACHE_PATTERN_PERMISSIONS = f"{CACHE_NAMESPACE}permissions:*"
CACHE_PATTERN_ORTHANC = f"{CACHE_NAMESPACE}orthanc:*"
CACHE_PATTERN_MODELS = f"{CACHE_NAMESPACE}ai_models:*"
CACHE_PATTERN_ALL = f"{CACHE_NAMESPACE}*"

# Cache key prefixes
CACHE_KEY_WORKLIST = f"{CACHE_NAMESPACE}worklist"
CACHE_KEY_PERMISSIONS = f"{CACHE_NAMESPACE}permissions"
CACHE_KEY_ORTHANC_STUDIES = f"{CACHE_NAMESPACE}orthanc:studies"
CACHE_KEY_ORTHANC_SERIES = f"{CACHE_NAMESPACE}orthanc:series"
CACHE_KEY_MODELS = f"{CACHE_NAMESPACE}ai_models"
