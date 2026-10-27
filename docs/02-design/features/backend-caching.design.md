# Design: Backend Redis Caching Optimization

**Feature**: backend-caching  
**Phase**: Design  
**Based On**: Plan document (backend-caching.plan.md)  
**Design Date**: 2026-05-13  
**Status**: Ready for Implementation  

---

## Architecture Overview

### Redis Cache Layer Structure

```
┌─────────────────────────────────────────────────┐
│                  FastAPI Endpoints               │
│   (GET /worklist, GET /auth/me, etc.)           │
└─────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────┐
│          Cache Middleware / Decorators           │
│   (@cached, @invalidate_on_write)               │
└─────────────────────────────────────────────────┘
                        ↓
        ┌───────────────┬───────────────┐
        ↓               ↓               ↓
    ┌────────┐    ┌─────────┐    ┌──────────┐
    │ Redis  │    │ Database│    │ Orthanc  │
    │ Cache  │    │(async)  │    │ REST API │
    └────────┘    └─────────┘    └──────────┘
   (5min, 1h)    (Fallback)      (Fallback)
```

### Cache Storage Location
- **Redis Instance**: `127.0.0.1:6379`
- **Connection Pool**: AsyncRedis in `backend/app/core/cache.py`
- **Namespace Prefix**: `pacs:` (to avoid conflicts with Celery keys)
- **Memory Limit**: 100MB (configured in Docker redis service)
- **Eviction Policy**: `allkeys-lru` (least recently used)

---

## Cache Strategy Details

### Strategy 1: Worklist Cache

**Purpose**: Cache paginated study list queries  
**Use Case**: `/api/v1/worklist?modality=CR&status=completed&page=1&limit=20`

**Cache Key Structure**:
```
pacs:worklist:{user_id}:{query_hash}
```

**Query Hash Calculation**:
```python
query_hash = hashlib.md5(
    f"{modality}:{status}:{patient_name}:{sort_by}:{page}:{limit}".encode()
).hexdigest()[:12]
```

**TTL**: 300 seconds (5 minutes)

**Data Stored**:
```json
{
  "studies": [...],
  "total_count": 125,
  "page": 1,
  "limit": 20,
  "cached_at": "2026-05-13T10:30:00Z"
}
```

**Cache Hit Rate Target**: 80%  
**Estimated Size**: ~2KB per entry, 100 concurrent users = 200KB

**Implementation Location**:
- Decorator: `backend/app/core/cache.py` → `@cached(ttl=300, key_prefix='worklist')`
- Usage: `backend/app/api/worklist.py` → `get_worklist()` endpoint

**Invalidation Triggers**:
1. TTL expiry (300s)
2. POST `/api/v1/studies` (new study created)
3. PATCH `/api/v1/studies/{id}` (study modified)
4. DELETE `/api/v1/studies/{id}` (study deleted)
5. POST `/dicom-web/studies` (STOW-RS upload)
6. Manual admin refresh: POST `/api/v1/admin/cache/purge?type=worklist`

**Invalidation Strategy**:
```python
# On study mutation, invalidate all worklist entries for that user
async def invalidate_user_worklist(user_id: str):
    pattern = f"pacs:worklist:{user_id}:*"
    keys = await redis.keys(pattern)
    if keys:
        await redis.delete(*keys)
```

**Error Handling**:
- Redis down → Skip cache, query DB directly (graceful fallback)
- Cache hit but data expired (stale) → Use cached data + refresh in background
- Query too complex → Bypass cache entirely

---

### Strategy 2: User Permissions Cache

**Purpose**: Cache RBAC role + resource permissions  
**Use Case**: JWT validation, per-request permission checks

**Cache Key Structure**:
```
pacs:permissions:{user_id}
```

**TTL**: Session lifetime (tied to JWT expiry)  
**Actual TTL**: Extracted from JWT `exp` claim, max 24 hours

**Data Stored**:
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "role": "radiologist",
  "permissions": ["read:studies", "write:reports", "read:ai_jobs"],
  "department": "radiology",
  "cached_at": "2026-05-13T10:30:00Z",
  "jwt_exp": 1715600400
}
```

**Cache Hit Rate Target**: 95%  
**Estimated Size**: ~500 bytes per user, 50 concurrent users = 25KB

**Implementation Location**:
- Cache set: `backend/app/api/auth.py` → `POST /auth/login` & `/auth/refresh`
- Cache check: `backend/app/core/security.py` → `get_current_user()` dependency

**Invalidation Triggers**:
1. JWT expiry (automatic via TTL)
2. User logout: DELETE `pacs:permissions:{user_id}`
3. Role/permission change: DELETE `pacs:permissions:{user_id}`
4. Manual admin revoke: POST `/api/v1/admin/permissions/revoke?user_id=...`

**Invalidation Strategy**:
```python
# On logout, immediately delete permissions
async def logout_user(user_id: str):
    await redis.delete(f"pacs:permissions:{user_id}")
    await AuditLog.create(action="logout", user_id=user_id)
```

**Error Handling**:
- Redis down → Query permissions from DB (slower but works)
- Cache miss → Query DB and populate cache
- Stale data (user role changed but cache valid) → Version check via cache version number

---

### Strategy 3: Orthanc Metadata Cache

**Purpose**: Cache study/series metadata from Orthanc REST API  
**Use Case**: Metadata lookups, study detail endpoints

**Cache Key Structure**:
```
pacs:orthanc:studies:{study_id}
pacs:orthanc:series:{series_id}
pacs:orthanc:studies:{study_id}:series-list
```

**TTL**: 3600 seconds (1 hour)

**Data Stored** (Study Level):
```json
{
  "study_id": "1.2.840.113619.2.408.3.5201.1",
  "study_uid": "1.2.840.113619.2.408.3.5201.1",
  "patient_id": "12345",
  "patient_name": "Kim^Myoungsu",
  "study_date": "20260511",
  "study_time": "103045",
  "modality": "CR",
  "institution_name": "Seoul Hospital",
  "series_count": 3,
  "series_list": [...],
  "cached_at": "2026-05-13T10:30:00Z"
}
```

**Cache Hit Rate Target**: 70%  
**Estimated Size**: ~10KB per study, 1000 studies = 10MB

**Implementation Location**:
- Wrapper: `backend/app/services/orthanc_client.py` (new module)
- Usage: `backend/app/api/dicomweb.py`, `backend/app/api/worklist.py`

**Caching Logic**:
```python
# In orthanc_client.py
async def get_study_metadata(study_id: str, use_cache=True):
    cache_key = f"pacs:orthanc:studies:{study_id}"
    
    if use_cache:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
    
    # Miss → Query Orthanc
    metadata = await orthanc_rest_client.get(f"/studies/{study_id}")
    
    # Store in cache with 1h TTL
    await redis.setex(cache_key, 3600, json.dumps(metadata))
    return metadata
```

**Invalidation Triggers**:
1. TTL expiry (3600s)
2. POST `/dicom-web/studies` (STOW-RS upload) → Invalidate study + all series
3. Manual admin refresh: POST `/api/v1/admin/cache/purge?type=orthanc`
4. Periodic refresh: Background job every 30 minutes

**Invalidation Strategy**:
```python
# On STOW-RS upload, invalidate affected study
async def invalidate_study_cache(study_id: str):
    pattern = f"pacs:orthanc:studies:{study_id}*"
    keys = await redis.keys(pattern)
    if keys:
        await redis.delete(*keys)
```

**Error Handling**:
- Redis down → Query Orthanc directly (no cache, slower)
- Orthanc down → Return cached data if available (stale but better than error)
- Metadata mismatch → Validate cache_timestamp vs Orthanc last_mod

---

### Strategy 4: AI Model Metadata Cache

**Purpose**: Cache AI model registry and metadata  
**Use Case**: Model selection, inference parameter validation

**Cache Key Structure**:
```
pacs:ai_models:list
pacs:ai_models:{model_id}
pacs:ai_models:{model_id}:versions
```

**TTL**: 86400 seconds (24 hours)

**Data Stored** (List):
```json
[
  {
    "model_id": "model_20250513_cr_detect",
    "name": "CR Detection v1.0",
    "type": "detection",
    "modality": ["CR"],
    "engine": "onnx",
    "version": "1.0.0",
    "input_shape": [512, 512, 1],
    "output_format": "sr",
    "enabled": true,
    "created_at": "2025-05-13"
  },
  ...
]
```

**Cache Hit Rate Target**: 99%  
**Estimated Size**: ~1KB per model, 50 models = 50KB

**Implementation Location**:
- Cache population: `backend/app/services/ai_worker.py` → `load_models()`
- Cache check: `backend/app/api/ai.py` → inference endpoints

**Caching Logic**:
```python
# In ai_worker.py at startup
async def initialize_model_cache():
    models = load_models_from_filesystem()
    await redis.setex(
        "pacs:ai_models:list",
        86400,
        json.dumps([model.to_dict() for model in models])
    )

# In ai.py at inference request
async def get_models(use_cache=True):
    if use_cache:
        cached = await redis.get("pacs:ai_models:list")
        if cached:
            return json.loads(cached)
    
    # Fallback: reload from filesystem
    return load_models_from_filesystem()
```

**Invalidation Triggers**:
1. TTL expiry (86400s / 24 hours)
2. Model file added/removed (manual filesystem operation)
3. Admin trigger: POST `/api/v1/admin/cache/purge?type=ai_models`
4. Startup initialization (auto-load on app restart)

**Invalidation Strategy**:
```python
# Admin endpoint to refresh models
@router.post("/admin/cache/purge")
async def purge_cache(cache_type: str = Query(...)):
    if cache_type == "ai_models":
        await redis.delete("pacs:ai_models:list")
        models = load_models_from_filesystem()
        await redis.setex("pacs:ai_models:list", 86400, json.dumps(...))
```

**Error Handling**:
- Redis down → Read from filesystem (no caching)
- Filesystem change not reflected → Use 24h TTL or manual refresh

---

## Cache Key Collision Prevention

### Namespace Isolation
All keys use `pacs:` prefix to avoid collision with Celery queue keys:
```
pacs:worklist:*        (worklist queries)
pacs:permissions:*     (user permissions)
pacs:orthanc:*         (Orthanc metadata)
pacs:ai_models:*       (AI model registry)
```

### User/Query Isolation
- Worklist keys include `{user_id}` → No cross-user data leaks
- Permissions keys include `{user_id}` → Isolated per session
- Orthanc keys use `{study_id}` → Unique DICOM identifiers
- AI model keys global (same for all users)

### Hash Collision Mitigation
Query hash uses MD5 of query parameters (modality, status, filters) truncated to 12 chars:
```python
query_hash = hashlib.md5(
    f"{modality}:{status}:{patient_name}:{sort}:{page}:{limit}".encode()
).hexdigest()[:12]
```

Risk: **Very low** (12-char MD5 = 281 trillion combinations, <1 collision per billion queries)

---

## Data Consistency Strategy

### Consistency Guarantee Levels

| Cache Strategy | Consistency | Method | Stale Data Risk |
|---|---|---|---|
| Worklist | Eventual | Invalidation on write | 5 minutes max |
| Permissions | Strong | Immediate delete on logout | None (token refresh) |
| Orthanc Metadata | Eventual | TTL + invalidation on upload | 1 hour max |
| AI Models | Eventual | Daily refresh + manual trigger | 24 hours max |

### Cache Aside Pattern (Write-Through Not Used)
- On **read**: Check cache → Redis miss → Query source → Store in cache
- On **write**: Invalidate cache → Update source → Done

**Rationale**: Medical data (DICOM) is read-heavy; write invalidation is sufficient.

### Stale Data Handling
```python
# If cached data is older than TTL, still serve but refresh in background
async def get_with_refresh(cache_key, source_fn, ttl, refresh_after):
    cached = await redis.get(cache_key)
    if cached:
        metadata = json.loads(cached)
        age = time.time() - metadata["cached_at"]
        if age > refresh_after:
            # Background refresh (don't block user)
            asyncio.create_task(refresh_cache(cache_key, source_fn, ttl))
        return metadata
    
    # Miss → Fetch and cache
    data = await source_fn()
    data["cached_at"] = time.time()
    await redis.setex(cache_key, ttl, json.dumps(data))
    return data
```

---

## Invalidation Trigger Mapping

### Event-Based Invalidation Matrix

| Event | Cache Affected | Strategy | Priority |
|---|---|---|---|
| POST `/dicom-web/studies` (upload) | Worklist, Orthanc | Delete pattern | HIGH |
| PATCH `/api/v1/studies/{id}` | Worklist, Orthanc | Delete pattern | HIGH |
| POST `/auth/login` | Permissions | Set new key | HIGH |
| POST `/auth/logout` | Permissions | Delete key | CRITICAL |
| Role/permission change | Permissions | Delete key | HIGH |
| Model file added | AI Models | Delete + reload | MEDIUM |
| Admin purge request | All (type-specific) | Delete pattern | MEDIUM |
| TTL expiry | All | Auto-expire | AUTO |

### Implementation: Cache Invalidation Decorator

```python
# In backend/app/core/cache.py

def invalidate_on_write(*cache_patterns):
    """
    Decorator to invalidate cache patterns on successful write operation.
    Usage:
        @invalidate_on_write('pacs:worklist:*', 'pacs:orthanc:*')
        async def create_study(...): ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)
            for pattern in cache_patterns:
                keys = await redis.keys(pattern)
                if keys:
                    await redis.delete(*keys)
            return result
        return wrapper
    return decorator
```

**Usage in endpoints**:
```python
# In backend/app/api/dicomweb.py
@router.post("/studies")
@invalidate_on_write('pacs:worklist:*', 'pacs:orthanc:*')
async def create_study(...):
    # STOW-RS implementation
    ...
```

---

## Error Handling & Fallback Strategy

### Redis Unavailability

**Scenario**: Redis connection fails

```python
async def get_cached(key: str, source_fn, ttl: int, fallback_to_source=True):
    try:
        cached = await redis.get(key)
        if cached:
            return json.loads(cached)
    except (RedisConnectionError, TimeoutError) as e:
        logger.warning(f"Redis error: {e}, falling back to source")
        if not fallback_to_source:
            raise
    
    # Fallback: Query source (DB/Orthanc)
    data = await source_fn()
    
    # Try to cache (non-blocking)
    try:
        await asyncio.wait_for(
            redis.setex(key, ttl, json.dumps(data)),
            timeout=0.5  # Don't block user if Redis slow
        )
    except asyncio.TimeoutError:
        logger.warning("Cache write timeout, continuing without cache")
    
    return data
```

**Impact**: 10-20% latency increase (without cache), but service continues

### Memory Exhaustion

**Configured Eviction**: `allkeys-lru` (least recently used)

**Monitoring**:
```python
# Background task every 5 minutes
async def monitor_redis_memory():
    info = await redis.info("memory")
    usage_percent = (info["used_memory"] / 100_000_000) * 100
    if usage_percent > 90:
        logger.error(f"Redis memory critical: {usage_percent}%")
        # Consider clearing less-critical caches (AI models, Orthanc metadata)
        await redis.delete("pacs:ai_models:*")
```

### Data Validation

**Cache integrity check** (on read):
```python
async def get_validated(cache_key: str, validator_fn):
    cached = await redis.get(cache_key)
    if cached:
        data = json.loads(cached)
        if await validator_fn(data):  # e.g., verify study still exists
            return data
        else:
            await redis.delete(cache_key)  # Remove invalid entry
    
    # Fallback...
```

---

## Implementation Sequence

### Phase 1: Infrastructure (2 hours)

**Files to Create**:
1. `backend/app/core/cache.py` — Redis connection, decorators, utilities
2. `backend/app/core/cache_config.py` — Cache TTL constants, settings
3. `backend/app/services/orthanc_client.py` — Orthanc REST wrapper with caching

**Code Structure**:
```
backend/app/core/cache.py:
├── async_redis: AsyncRedis instance
├── @cached(ttl, key_prefix) decorator
├── @invalidate_on_write(*patterns) decorator
├── get_cached(key, source, ttl) helper
└── purge_pattern(pattern) helper

backend/app/core/cache_config.py:
├── CACHE_TTL_WORKLIST = 300
├── CACHE_TTL_PERMISSIONS = 86400
├── CACHE_TTL_ORTHANC = 3600
├── CACHE_TTL_MODELS = 86400
└── CACHE_NAMESPACE = "pacs:"

backend/app/services/orthanc_client.py:
├── OrthancCachedClient class
├── get_study_metadata(study_id, use_cache=True)
├── get_series_metadata(series_id, use_cache=True)
└── invalidate_cache(study_id)
```

### Phase 2: Worklist + Permissions (3 hours)

**Files to Modify**:
1. `backend/app/api/worklist.py` — Add cache layer to GET /worklist
2. `backend/app/api/auth.py` — Set permissions cache on login
3. `backend/app/core/security.py` — Check permissions cache in get_current_user

**Changes**:
```python
# In worklist.py
@router.get("/worklist")
@cached(ttl=300, key_prefix='worklist')
async def get_worklist(filters: WorklistFilters, user: User = Depends(get_current_user)):
    # Existing logic, decorator handles caching
    return studies

# In auth.py (login endpoint)
@router.post("/login")
async def login(credentials: LoginRequest):
    user = authenticate_user(credentials)
    tokens = create_tokens(user)
    
    # Cache permissions
    await redis.setex(
        f"pacs:permissions:{user.id}",
        extract_exp_from_jwt(tokens.access_token),
        json.dumps(user_to_permissions_dict(user))
    )
    
    return tokens
```

### Phase 3: Orthanc Metadata (2 hours)

**Files to Modify**:
1. `backend/app/api/dicomweb.py` — Wrap Orthanc calls with cache layer
2. `backend/app/api/studies.py` — Use OrthancCachedClient

**Changes**:
```python
# Replace direct Orthanc calls with cached wrapper
orthanc_client = OrthancCachedClient(redis=redis)

async def get_study_detail(study_id: str):
    # No longer: orthanc.get(f"/studies/{study_id}")
    # Instead:
    return await orthanc_client.get_study_metadata(study_id, use_cache=True)
```

### Phase 4: AI Models + Integration (3 hours)

**Files to Modify**:
1. `backend/app/services/ai_worker.py` — Initialize AI model cache at startup
2. `backend/app/api/ai.py` — Check cache before querying filesystem

**New Admin Endpoints** (in `backend/app/api/admin.py`):
```python
@router.post("/cache/purge")
@require_role(Role.ADMIN)
async def purge_cache(cache_type: str = Query(...)):
    """Admin endpoint to manually purge cache by type."""
    if cache_type == "all":
        await redis.flushdb()
    elif cache_type == "worklist":
        keys = await redis.keys("pacs:worklist:*")
        if keys:
            await redis.delete(*keys)
    elif cache_type == "orthanc":
        keys = await redis.keys("pacs:orthanc:*")
        if keys:
            await redis.delete(*keys)
    elif cache_type == "ai_models":
        await redis.delete("pacs:ai_models:*")
        # Reload
        ...
    return {"status": "purged", "type": cache_type}
```

---

## Testing Strategy

### Unit Tests
```python
# tests/test_cache.py
├── test_cached_decorator_hit()
├── test_cached_decorator_miss()
├── test_invalidate_decorator()
├── test_cache_ttl_expiry()
└── test_redis_unavailable_fallback()

# tests/test_cache_consistency.py
├── test_worklist_invalidation_on_study_create()
├── test_permissions_invalidation_on_logout()
├── test_orthanc_metadata_invalidation_on_upload()
└── test_ai_models_cache_refresh()
```

### Integration Tests
```python
# tests/integration/test_caching_e2e.py
├── test_worklist_cache_hit_rate_80percent()
├── test_permissions_cache_hit_rate_95percent()
├── test_orthanc_cache_hit_rate_70percent()
├── test_ai_models_cache_hit_rate_99percent()
└── test_all_caches_no_stale_data_beyond_ttl()
```

### Load Tests
```bash
# tests/load/locustfile.py
locust -f locustfile.py --host=http://localhost:8001 \
  --users 100 --spawn-rate 10 --run-time 10m

# Expected: 30-40% reduction in average response time
```

---

## Performance Metrics & Monitoring

### Metrics to Track
```python
# In background task every 60 seconds
async def collect_cache_metrics():
    info = await redis.info()
    metrics = {
        "redis_memory_mb": info["used_memory"] / 1_000_000,
        "connected_clients": info["connected_clients"],
        "evicted_keys": info["evicted_keys"],
        "hits": info["keyspace_hits"],
        "misses": info["keyspace_misses"],
        "hit_rate": info["keyspace_hits"] / (info["keyspace_hits"] + info["keyspace_misses"]),
    }
    logger.info(f"Cache metrics: {metrics}")
```

### Success Criteria
- ✅ Worklist query time: 500ms → 50ms (90% improvement)
- ✅ Permissions check: 10ms → 1ms (90% improvement)
- ✅ Overall API latency: 40% reduction
- ✅ Cache hit rate: 70%+ across all strategies
- ✅ Zero stale data incidents in 7-day trial
- ✅ Match Rate: 90% → 95%+

---

## Documentation & Code Comments

### Architecture Diagram (in Design Doc)
Place in repo: `docs/architecture/cache-strategy.md`

### Code Comments
```python
# Every cache decorator and invalidation trigger must include:
"""
CACHING STRATEGY: Worklist cache with 5-minute TTL
- Hit rate target: 80%
- Invalidation: Study mutations (POST/PATCH/DELETE)
- Fallback: Query PostgreSQL if Redis unavailable
"""
```

### API Documentation
Update OpenAPI docs with cache headers:
```python
@router.get("/worklist", 
    response_model=WorklistResponse,
    responses={
        200: {
            "description": "Paginated study list",
            "headers": {
                "X-Cache": {
                    "description": "HIT (from Redis) or MISS (from DB)",
                    "schema": {"type": "string"}
                }
            }
        }
    }
)
```

---

## Deployment Considerations

### Docker Compose Update
```yaml
# In docker-compose.yml
redis:
  image: redis:7-alpine
  command: redis-server --maxmemory 100mb --maxmemory-policy allkeys-lru
  ports:
    - "127.0.0.1:6379:6379"
  volumes:
    - redis_data:/data
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 5s
    timeout: 3s
    retries: 5
```

### Environment Variables
```bash
# .env for backend
REDIS_URL=redis://127.0.0.1:6379/0
CACHE_ENABLED=true
CACHE_TTL_WORKLIST=300
CACHE_TTL_PERMISSIONS=86400
CACHE_TTL_ORTHANC=3600
CACHE_TTL_MODELS=86400
```

### Production Checklist
- ✅ Redis persistence enabled (RDB snapshots)
- ✅ Memory limits configured (100MB)
- ✅ Eviction policy set (allkeys-lru)
- ✅ Monitoring/alerting on Redis memory
- ✅ Cache invalidation tested end-to-end
- ✅ Graceful fallback verified (Redis down scenario)

---

## Open Questions & Design Decisions

### Decision: Cache-Aside vs Write-Through
- **Chosen**: Cache-Aside (read from cache, write to source, invalidate)
- **Rationale**: DICOM data is read-heavy (100:1 read-write ratio). Write-through would complicate error handling.

### Decision: Shared vs Per-User Caches
- **Chosen**: Mix (worklist/orthanc shared, permissions per-user)
- **Rationale**: Permissions are sensitive (per-user required); metadata is shared (read-only).

### Decision: TTL vs Lazy Invalidation
- **Chosen**: Both (TTL for background cleanup, explicit invalidation for correctness)
- **Rationale**: Lazy invalidation ensures correctness; TTL prevents memory bloat.

### Decision: Distributed Cache Lock (Redis WATCH)
- **Chosen**: Not needed initially (single backend instance)
- **Future**: Multi-instance deployments (Phase 7) may need Redis Locks

---

## Next Steps

1. ✅ Plan approved → Design complete
2. ⏳ Implementation (`/pdca do backend-caching`)
3. ⏳ Gap analysis (`/pdca analyze backend-caching`)
4. ⏳ Completion report (`/pdca report backend-caching`)

---

## Related Documents
- [Cache Constants](../../src/cache_config.py) (auto-generated after Phase 1)
