# Implementation Guide: Backend Redis Caching (Phase 3)

**Feature**: backend-caching  
**Phase**: Do (Implementation)  
**Design Reference**: `docs/02-design/features/backend-caching.design.md`  
**Start Date**: 2026-05-13  
**Target Completion**: 2026-05-20  

---

## Implementation Overview

Follow the 4-phase implementation sequence. Each phase is independent but builds on previous infrastructure.

**Estimated Timeline**:
- Phase 1 (Infrastructure): 2 hours
- Phase 2 (Worklist + Permissions): 3 hours
- Phase 3 (Orthanc Metadata): 2 hours
- Phase 4 (AI Models + Testing): 3 hours
- **Total**: 10 hours

---

## Phase 1: Cache Infrastructure (2 hours)

### 1.1 Create Core Cache Module

**File**: `backend/app/core/cache.py` (NEW)

Key components:
1. AsyncRedis connection pool with health checks
2. `@cached(ttl, key_prefix)` decorator for read operations
3. `@invalidate_on_write(*patterns)` decorator for write operations
4. Helper functions: `get_cached()`, `purge_pattern()`

```python
# Structure to implement:
import redis.asyncio as redis
from functools import wraps
import json
import hashlib

class CacheManager:
    _instance = None
    redis: redis.Redis = None
    
    @classmethod
    async def get_instance(cls) -> 'CacheManager':
        if cls._instance is None:
            cls._instance = CacheManager()
            await cls._instance.connect()
        return cls._instance
    
    async def connect(self):
        self.redis = await redis.from_url("redis://127.0.0.1:6379/0")
    
    async def get(self, key: str) -> str:
        """Get value from cache"""
        
    async def set(self, key: str, value: str, ttl: int):
        """Set value in cache with TTL"""
        
    async def delete(self, *keys: str):
        """Delete keys"""
        
    async def keys(self, pattern: str) -> list:
        """Get keys matching pattern"""

def cached(ttl: int, key_prefix: str = None):
    """Decorator to cache function results with TTL"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Implementation: check cache → call func → store in cache
            pass
        return wrapper
    return decorator

def invalidate_on_write(*patterns: str):
    """Decorator to invalidate cache patterns after write operation"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Implementation: call func → invalidate patterns
            pass
        return wrapper
    return decorator
```

**Checklist**:
- [ ] AsyncRedis connection initialized at app startup
- [ ] Health check implemented (redis.ping())
- [ ] Graceful fallback when Redis down (cache_manager.available flag)
- [ ] Error logging for cache operations

### 1.2 Create Cache Configuration Module

**File**: `backend/app/core/cache_config.py` (NEW)

```python
# Constants for all caches
CACHE_NAMESPACE = "pacs:"

CACHE_TTL_WORKLIST = 300          # 5 minutes
CACHE_TTL_PERMISSIONS = 86400     # 24 hours (or JWT exp)
CACHE_TTL_ORTHANC = 3600          # 1 hour
CACHE_TTL_MODELS = 86400          # 24 hours

CACHE_MAX_MEMORY = 100_000_000    # 100 MB
CACHE_EVICTION_POLICY = "allkeys-lru"

# Key patterns
CACHE_PATTERN_WORKLIST = f"{CACHE_NAMESPACE}worklist:*"
CACHE_PATTERN_PERMISSIONS = f"{CACHE_NAMESPACE}permissions:*"
CACHE_PATTERN_ORTHANC = f"{CACHE_NAMESPACE}orthanc:*"
CACHE_PATTERN_MODELS = f"{CACHE_NAMESPACE}ai_models:*"
```

**Checklist**:
- [ ] All constants defined
- [ ] Imported in cache.py for use in decorators

### 1.3 Create Orthanc Cached Client

**File**: `backend/app/services/orthanc_client.py` (NEW)

This wraps the existing Orthanc REST API calls with caching logic.

```python
# Key methods to implement:
class OrthancCachedClient:
    def __init__(self, redis_manager: CacheManager, orthanc_api):
        self.redis = redis_manager
        self.orthanc = orthanc_api
    
    async def get_study_metadata(self, study_id: str, use_cache=True):
        """Get study metadata with cache"""
        # Implementation: check cache → query Orthanc → store in cache
        pass
    
    async def get_series_metadata(self, series_id: str, use_cache=True):
        """Get series metadata with cache"""
        pass
    
    async def get_series_list(self, study_id: str, use_cache=True):
        """Get series list for study with cache"""
        pass
    
    async def invalidate_study_cache(self, study_id: str):
        """Invalidate all caches for a study"""
        pass
```

**Checklist**:
- [ ] Wraps existing Orthanc client
- [ ] Caches at appropriate granularity (study, series)
- [ ] Fallback to Orthanc if Redis unavailable
- [ ] Error handling for missing studies

---

## Phase 2: Worklist + Permissions (3 hours)

### 2.1 Add Cache to Worklist Endpoint

**File**: `backend/app/api/worklist.py` (MODIFY)

Current location of `GET /api/v1/worklist` endpoint.

**Changes**:
1. Add `@cached(ttl=CACHE_TTL_WORKLIST, key_prefix='worklist')` decorator
2. Ensure query parameters are deterministic (sort, hash filters)

```python
# Before:
@router.get("/worklist")
async def get_worklist(filters: WorklistFilters, user: User = Depends(get_current_user)):
    studies = await db.query(...)
    return studies

# After:
@router.get("/worklist")
@cached(ttl=CACHE_TTL_WORKLIST, key_prefix='worklist')
async def get_worklist(filters: WorklistFilters, user: User = Depends(get_current_user)):
    studies = await db.query(...)
    return studies
```

**Cache Key Calculation**:
- Use user_id + query hash (modality, status, filters)
- Hash must be deterministic (sorted params)

**Checklist**:
- [ ] Decorator applied to GET /worklist
- [ ] Query parameters normalized for consistent hashing
- [ ] Cache key includes user_id (no cross-user leaks)
- [ ] Manual test: same query called twice → second call hits cache

### 2.2 Cache Permissions on Login

**File**: `backend/app/api/auth.py` (MODIFY)

Endpoints: `POST /auth/login`, `POST /auth/refresh`

**Changes**:
1. After successful authentication, store permissions in Redis
2. Set TTL to JWT expiry time (extract from token `exp` claim)

```python
# After authentication succeeds:
async def cache_user_permissions(user: User, redis: CacheManager, jwt_exp: int):
    """Cache user permissions in Redis with TTL = JWT expiry"""
    permissions_data = {
        "user_id": str(user.id),
        "role": user.role,
        "permissions": get_permissions_for_role(user.role),
        "department": user.department,
        "cached_at": datetime.utcnow().isoformat(),
        "jwt_exp": jwt_exp
    }
    
    ttl = jwt_exp - int(datetime.utcnow().timestamp())
    cache_key = f"pacs:permissions:{user.id}"
    
    await redis.set(cache_key, json.dumps(permissions_data), ttl)
```

**Checklist**:
- [ ] Permissions cache populated on POST /auth/login
- [ ] Permissions cache refreshed on POST /auth/refresh
- [ ] TTL set to JWT expiry (not hardcoded 24h)
- [ ] Cache key includes user_id
- [ ] Manual test: login → check Redis has key

### 2.3 Check Permissions Cache in get_current_user

**File**: `backend/app/core/security.py` (MODIFY)

Location of JWT validation and `get_current_user()` dependency.

**Changes**:
1. Before querying DB for user permissions, check Redis
2. If cache hit, use cached permissions
3. If cache miss or Redis down, fall back to DB

```python
# Pseudocode:
async def get_current_user(token: str) -> User:
    payload = decode_jwt(token)
    user_id = payload.get("sub")
    
    # Check cache first
    cache_key = f"pacs:permissions:{user_id}"
    cached = await redis.get(cache_key)
    if cached:
        permissions = json.loads(cached)
        return permissions  # Use cached
    
    # Cache miss → query DB
    user = await db.get_user(user_id)
    # ... existing validation logic
    return user
```

**Checklist**:
- [ ] Redis check added to get_current_user before DB query
- [ ] Graceful fallback if Redis unavailable
- [ ] Response time reduced by ~90% (cache hit case)
- [ ] Manual test: multiple requests with same token → Redis queries only first

### 2.4 Add Logout Cache Invalidation

**File**: `backend/app/api/auth.py` (MODIFY)

Endpoint: `POST /auth/logout`

**Changes**:
1. On logout, delete permissions cache for that user

```python
@router.post("/logout")
async def logout(user: User = Depends(get_current_user)):
    # Delete cached permissions
    cache_key = f"pacs:permissions:{user.id}"
    await redis.delete(cache_key)
    
    # Create audit log
    await AuditLog.create(action="logout", user_id=user.id)
    
    return {"status": "logged_out"}
```

**Checklist**:
- [ ] Permissions cache deleted on logout
- [ ] Audit log created
- [ ] Manual test: logout → login → new session created

---

## Phase 3: Orthanc Metadata (2 hours)

### 3.1 Integrate OrthancCachedClient into Endpoints

**Files to Modify**:
- `backend/app/api/dicomweb.py` — DICOMweb endpoints
- `backend/app/api/studies.py` — Study detail endpoints
- Any other files calling Orthanc directly

**Changes**:
1. Replace direct Orthanc API calls with `OrthancCachedClient` methods
2. Ensure invalidation triggers on STOW-RS uploads

```python
# Before:
async def get_study_detail(study_id: str):
    response = await orthanc_api.get(f"/studies/{study_id}")
    return response

# After:
async def get_study_detail(study_id: str):
    orthanc_client = OrthancCachedClient(redis, orthanc_api)
    return await orthanc_client.get_study_metadata(study_id, use_cache=True)
```

**Checklist**:
- [ ] OrthancCachedClient used in all study/series queries
- [ ] Fallback works if Redis down
- [ ] Cache hits verified (spot-check logs)

### 3.2 Add Invalidation to STOW-RS Upload

**File**: `backend/app/api/dicomweb.py` (MODIFY)

Endpoint: `POST /studies` (STOW-RS)

**Changes**:
1. After successful upload, invalidate Orthanc + Worklist caches

```python
@router.post("/studies")
@invalidate_on_write('pacs:worklist:*', 'pacs:orthanc:*')
async def upload_dicom(files: List[UploadFile]):
    # Existing STOW-RS logic
    result = await upload_to_orthanc(files)
    # Decorator handles cache invalidation
    return result
```

**Checklist**:
- [ ] @invalidate_on_write decorator applied
- [ ] Worklist cache cleared on upload
- [ ] Orthanc cache cleared on upload
- [ ] Manual test: upload → query worklist → cache miss (expected after upload)

### 3.3 Add Invalidation to Study Mutations

**Files to Modify**:
- `backend/app/api/studies.py` — PATCH /studies/{id}
- Any other study mutation endpoints

**Changes**:
```python
@router.patch("/studies/{id}")
@invalidate_on_write('pacs:worklist:*', f'pacs:orthanc:studies:{id}')
async def update_study(id: str, data: StudyUpdate):
    result = await update_in_db(id, data)
    return result
```

**Checklist**:
- [ ] All write endpoints have @invalidate_on_write decorator
- [ ] Correct cache patterns invalidated for each operation
- [ ] Manual test: edit study → next worklist query hits DB (cache cleared)

---

## Phase 4: AI Models + Integration (3 hours)

### 4.1 Initialize AI Model Cache at Startup

**File**: `backend/app/services/ai_worker.py` (MODIFY)

Location of model loading logic.

**Changes**:
1. On app startup, load models and cache them
2. Set 24-hour TTL

```python
async def initialize_model_cache():
    """Called on app startup (in lifespan context)"""
    models = load_models_from_filesystem()
    
    model_list = [
        {
            "model_id": m.model_id,
            "name": m.name,
            "type": m.model_type,
            "modality": m.modality,
            "engine": m.engine,
            "version": m.version,
            "input_shape": m.input_shape,
            "output_format": m.output_format,
            "enabled": m.enabled,
        }
        for m in models
    ]
    
    cache_key = "pacs:ai_models:list"
    await redis.set(cache_key, json.dumps(model_list), ttl=CACHE_TTL_MODELS)
```

**Checklist**:
- [ ] Cache populated on app startup
- [ ] All model metadata cached
- [ ] TTL set to 24 hours
- [ ] Manual test: app startup → Redis has pacs:ai_models:list

### 4.2 Use Cache in AI Inference Endpoint

**File**: `backend/app/api/ai.py` (MODIFY)

Endpoints: Inference requests that reference models

**Changes**:
```python
async def get_available_models(use_cache=True):
    """Get list of available AI models from cache"""
    cache_key = "pacs:ai_models:list"
    
    if use_cache:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
    
    # Fallback: reload from filesystem
    return [m.to_dict() for m in load_models_from_filesystem()]
```

**Checklist**:
- [ ] Inference endpoints call get_available_models()
- [ ] Cache hit reduces model lookup time from ~50ms to ~1ms
- [ ] Fallback works if Redis down
- [ ] Manual test: inference request → no filesystem reads on cache hit

### 4.3 Add Admin Cache Purge Endpoints

**File**: `backend/app/api/admin.py` (MODIFY or CREATE)

**New Endpoint**: `POST /api/v1/admin/cache/purge`

```python
@router.post("/admin/cache/purge")
@require_role(Role.ADMIN)
async def purge_cache(cache_type: str = Query(...)):
    """
    Purge cache by type.
    
    Query params:
      - cache_type: "all", "worklist", "permissions", "orthanc", "ai_models"
    """
    if cache_type == "all":
        await redis.flushdb()
        return {"status": "purged", "type": "all"}
    
    pattern = {
        "worklist": "pacs:worklist:*",
        "permissions": "pacs:permissions:*",
        "orthanc": "pacs:orthanc:*",
        "ai_models": "pacs:ai_models:*",
    }.get(cache_type)
    
    if pattern:
        keys = await redis.keys(pattern)
        if keys:
            await redis.delete(*keys)
        
        # Refresh AI models cache if needed
        if cache_type == "ai_models":
            await initialize_model_cache()
        
        return {"status": "purged", "type": cache_type, "keys_deleted": len(keys)}
    
    raise ValueError(f"Unknown cache_type: {cache_type}")
```

**Checklist**:
- [ ] Endpoint implemented and requires admin role
- [ ] All cache types supported
- [ ] AI models cache refreshed after purge
- [ ] Manual test: call with admin token → caches cleared

### 4.4 Add Cache Statistics Endpoint (Optional)

**File**: `backend/app/api/admin.py`

**New Endpoint**: `GET /api/v1/admin/cache/stats`

```python
@router.get("/admin/cache/stats")
@require_role(Role.ADMIN)
async def get_cache_stats():
    """Get Redis cache statistics"""
    info = await redis.info("stats")
    return {
        "hits": info.get("keyspace_hits", 0),
        "misses": info.get("keyspace_misses", 0),
        "hit_rate": info.get("keyspace_hits") / (info.get("keyspace_hits") + info.get("keyspace_misses")) if (info.get("keyspace_hits") + info.get("keyspace_misses")) > 0 else 0,
        "memory_mb": info.get("used_memory", 0) / 1_000_000,
    }
```

**Checklist**:
- [ ] Endpoint returns cache hit/miss rates
- [ ] Memory usage visible
- [ ] Useful for monitoring cache effectiveness

---

## Testing Checklist

### Unit Tests
- [ ] `test_cached_decorator_with_hit()`
- [ ] `test_cached_decorator_with_miss()`
- [ ] `test_invalidate_decorator()`
- [ ] `test_redis_unavailable_fallback()`
- [ ] `test_cache_ttl_expiry()`

### Integration Tests
- [ ] `test_worklist_cache_invalidation_on_study_upload()`
- [ ] `test_permissions_cache_invalidation_on_logout()`
- [ ] `test_orthanc_cache_hit_reduces_latency()`
- [ ] `test_ai_models_cache_at_startup()`
- [ ] `test_admin_cache_purge_endpoint()`

### Manual Testing
- [ ] **Worklist cache**: Same query twice → 2nd is faster
- [ ] **Permissions cache**: Login → multiple requests → fast
- [ ] **Orthanc cache**: Study detail query → 70% latency reduction
- [ ] **AI models cache**: Inference request → model lookup <1ms
- [ ] **Redis down**: App continues working (no crashes)
- [ ] **Cache invalidation**: Upload → worklist refreshes

### Load Testing
```bash
# Use locust or Apache Bench
locust -f tests/load/locustfile.py --users 50 --spawn-rate 5

# Expected: 30-40% avg response time improvement
```

---

## Success Metrics

After implementation is complete:

✅ **Performance**
- Worklist query: 500ms → 50ms (90% improvement)
- Permissions check: 10ms → 1ms (90% improvement)
- Overall API latency: 40% reduction
- Cache hit rate: 70%+ across all strategies

✅ **Reliability**
- Zero stale data incidents (respect TTL)
- Graceful fallback when Redis unavailable
- No data corruption from cache collisions

✅ **Code Quality**
- All endpoints have proper decorators
- Error handling for Redis failures
- Test coverage ≥85%

✅ **Documentation**
- Design doc updated with implementation details
- Code comments explain caching strategy
- Admin endpoints documented in API spec

---

## Deployment Steps

After implementation complete:

1. **Build & Test Locally**
   ```bash
   docker-compose build backend
   docker-compose up backend redis
   # Run test suite
   pytest tests/
   ```

2. **Deploy to Server**
   ```bash
   scp -P 819 -r backend/app/ deploy@198.51.100.73:/home/deploy/openpacs/backend/
   ssh deploy@198.51.100.73 -p 819 "cd /home/deploy/hospital-run/infra/docker && docker compose restart backend"
   ```

3. **Verify in Production**
   ```bash
   curl -sk https://his.example.org/pacs-api/health  # Should be OK
   curl -sk https://his.example.org/pacs-api/api/v1/admin/cache/stats  # Check stats
   ```

4. **Monitor**
   - Check logs for any "Redis connection failed" errors
   - Monitor response times (should drop 40%)
   - Check cache hit rates via `/admin/cache/stats`

---

## Troubleshooting

### Issue: Redis connection refused
- Check Redis is running: `docker ps | grep redis`
- Check Redis port: `redis-cli ping`
- Check connection string in environment

### Issue: Cache hit rate is low (<50%)
- Check cache TTL is appropriate
- Verify query normalization (same params → same hash)
- Check if queries are deterministic

### Issue: Stale data served
- Verify invalidation triggers are firing
- Check TTL values match expected refresh rates
- Monitor cache invalidation in logs

### Issue: Memory usage high
- Check eviction policy is `allkeys-lru`
- Reduce TTL or cache sizes
- Use `/admin/cache/purge?cache_type=orthanc` manually

---

## Next Steps

1. ✅ Plan created
2. ✅ Design created
3. ⏳ **Implementation (Do phase)** — You are here
4. ⏳ Gap analysis (Check phase) — Compare design vs implementation
5. ⏳ Completion report (Report phase) — Document results

After implementation completion, run:
```bash
/pdca analyze backend-caching
```

---

## Code Files Summary

| Phase | File | Type | Lines |
|:-----:|------|:----:|:-----:|
| 1 | backend/app/core/cache.py | NEW | ~300 |
| 1 | backend/app/core/cache_config.py | NEW | ~30 |
| 1 | backend/app/services/orthanc_client.py | NEW | ~150 |
| 2 | backend/app/api/worklist.py | MODIFY | +5 lines (decorator) |
| 2 | backend/app/api/auth.py | MODIFY | +20 lines (cache) |
| 2 | backend/app/core/security.py | MODIFY | +10 lines (cache check) |
| 3 | backend/app/api/dicomweb.py | MODIFY | +5 lines (decorator) |
| 3 | backend/app/api/studies.py | MODIFY | +5 lines (decorator) |
| 4 | backend/app/services/ai_worker.py | MODIFY | +10 lines (cache init) |
| 4 | backend/app/api/ai.py | MODIFY | +10 lines (cache check) |
| 4 | backend/app/api/admin.py | MODIFY/NEW | +50 lines (endpoints) |

**Total New Code**: ~560 lines  
**Total Modified Lines**: ~65 lines

---

## Implementation Notes

1. **Start with Phase 1**: Don't skip infrastructure setup
2. **Test After Each Phase**: Verify cache hits before moving on
3. **Use Redis CLI to Inspect**: `redis-cli keys "pacs:*"` to see stored keys
4. **Logging is Your Friend**: Add detailed logs in cache.py for debugging
5. **Graceful Degradation**: Always have fallback when Redis unavailable

---

## Related Documents
