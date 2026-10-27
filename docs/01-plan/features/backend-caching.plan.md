# Plan: Backend Redis Caching Optimization (Phase 3)

**Feature**: backend-caching  
**Phase**: Plan  
**Priority**: CRITICAL  
**Start Date**: 2026-05-13  
**Target Completion**: 2026-05-20  
**Effort**: 8-10 hours  

---

## Executive Summary

The OpenPACS backend currently scores **90% on design-implementation compliance** with a critical gap: **Redis caching (0% implemented)**. This plan addresses the 4 high-impact caching strategies required to:
- Reduce API latency (especially DICOMweb queries)
- Minimize load on PostgreSQL and Orthanc
- Improve user experience during peak usage
- Prepare for multi-facility scaling (Phase 7)

**Expected Impact After Implementation**: Match Rate 95%+ | Query latency ↓40% | Cache hit rate 70%+

---

## Current State Analysis

### Pain Points (User Experience)
1. **Worklist queries**: Every page load hits PostgreSQL + Orthanc (slow during morning rounds)
2. **Permission checks**: RBAC checks go to DB every request (multiplies request count)
3. **DICOMweb metadata**: Orthanc REST API calls slow for study listings (>5 studies)
4. **AI model info**: Metadata refreshed from filesystem every inference (60+ calls/day unnecessary)

### Design vs. Implementation Gap
- **Design Specified**: 4 caching layers with TTLs
- **Implementation**: Redis initialized but only used for Celery queues
- **Match Score**: 0% on caching (5% weight in overall 90%)

### Prerequisites Met ✅
- Redis 7 running on 127.0.0.1:6379
- redis-py client imported in backend/app/core/cache.py
- Async context available in FastAPI endpoints

---

## Objectives

### Primary Goal
Implement 4 Redis cache strategies reducing query latency by 40%+ while maintaining data consistency.

### Success Criteria
1. All 4 cache layers operational with correct TTLs
2. Cache invalidation triggers working (on data mutation)
3. No stale data served >TTL (verified in testing)
4. Design-implementation match rate ≥95%
5. Zero performance regression on writes
6. Documentation updated (design + implementation comments)

---

## Caching Strategies

### Strategy 1: Worklist Cache (5-minute TTL)
**What**: Study list queries (`GET /api/v1/worklist?modality=CR&status=...`)  
**Why**: Same filters queried 50+ times/day; data changes rarely mid-day  
**How**:
- Cache key: `worklist:{user_id}:{query_hash}` (hash includes filters+pagination)
- TTL: 300 seconds (5 minutes)
- Size estimate: ~2KB per entry, 100 users = 200KB
- Invalidation: POST/PATCH/DELETE on studies, on periodic refresh (admin button)

**Expected benefit**: 80% cache hit rate | Query time 500ms → 50ms

---

### Strategy 2: User Permissions Cache (Session Lifetime)
**What**: RBAC role + resource permissions (`GET /api/v1/auth/me`)  
**Why**: Permission check called 5-10x per API call; never changes mid-session  
**How**:
- Cache key: `permissions:{user_id}`
- TTL: Set at login, expire when JWT refreshed or logout called
- Invalidation: On logout (delete key) or JWT expiry
- Secondary check: Include permission version in cached data, invalidate if version changes

**Expected benefit**: 95% cache hit rate | RBAC time 10ms → 1ms

---

### Strategy 3: Orthanc Metadata Cache (1-hour TTL)
**What**: Study/series metadata from Orthanc REST API (patient name, modality, date, etc.)  
**Why**: Metadata stable during clinical day; Orthanc response time ~200ms per call  
**How**:
- Cache key: `orthanc:studies:{study_id}` and `orthanc:series:{series_id}`
- TTL: 3600 seconds (1 hour)
- Size estimate: ~10KB per study, 1000 studies = 10MB (acceptable)
- Invalidation: On STOW-RS upload, 1h timeout, or admin refresh

**Expected benefit**: 70% cache hit rate | Study detail time 200ms → 20ms

---

### Strategy 4: AI Model Metadata Cache (24-hour TTL)
**What**: Model registry from `models/` folder (name, version, input shape, etc.)  
**Why**: Model files change rarely; metadata read 10+ times per inference call  
**How**:
- Cache key: `ai_models:list` and `ai_models:{model_id}`
- TTL: 86400 seconds (24 hours)
- Size: ~1KB per model, 50 models = 50KB (minimal)
- Invalidation: 24h timeout or manual refresh endpoint

**Expected benefit**: 99% cache hit rate | Model lookup time 50ms → 1ms

---

## Implementation Plan

### Phase 1: Cache Infrastructure (2 hours)
1. Create `backend/app/core/cache_manager.py` (TTL handling, invalidation)
2. Add Redis connection pool with async context
3. Implement cache decorators: `@cached(ttl=300)`, `@invalidate_on_write`
4. Add metrics: cache hit/miss rates

### Phase 2: Worklist & Permissions (3 hours)
1. Cache worklist queries in `GET /api/v1/worklist` (with query normalization)
2. Cache user permissions in JWT refresh + auth middleware
3. Invalidation hooks on POST/PATCH studies
4. Unit tests: verify TTL expiry, cache key uniqueness

### Phase 3: Orthanc Metadata (2 hours)
1. Wrap Orthanc REST calls with cache layer
2. Cache study detail, series list endpoints
3. Invalidation on STOW-RS, periodic refresh
4. Test with 10+ concurrent requests to verify hit rate

### Phase 4: AI Models & Testing (3 hours)
1. Cache model registry at startup, refresh on demand
2. Integration test: full inference pipeline with caching
3. E2E test: verify all 4 caches working together
4. Documentation: cache architecture diagram + TTL explanation

---

## Technical Specifications

### Redis Keys Namespace
```
worklist:{user_id}:{modality}:{status}:{page}
permissions:{user_id}
orthanc:studies:{study_id}
orthanc:series:{series_id}
ai_models:list
ai_models:{model_id}
```

### Cache Invalidation Strategy
| Event | Caches Affected | Action |
|-------|-----------------|--------|
| User logout | permissions:{user_id} | Delete key |
| Study created | worklist:*, orthanc:* | Invalidate worklist range |
| Study modified | orthanc:studies:{id} | Delete specific key |
| Permissions updated | permissions:{user_id} | Delete key |
| Model file changed | ai_models:* | Delete all model keys |

### Memory Management
- Redis eviction: `maxmemory-policy allkeys-lru` (100MB limit)
- Estimated steady state: 50MB (worklist 20MB + orthanc 20MB + permissions 5MB + models <1MB)
- Safety margin: 50% headroom for spikes

---

## Risk Assessment & Mitigation

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|-----------|
| Stale data served beyond TTL | User confusion | Low | Validate data freshness on critical reads |
| Redis down, app crashes | Unavailability | Low | Graceful fallback: cache miss → query DB |
| High memory usage | OOM, eviction | Medium | Monitor with Prometheus, set memory alerts |
| Cache key collision | Silent data corruption | Very Low | Use scoped keys with user_id/query hash |
| Invalidation race condition | Partial stale data | Medium | Use atomic operations (Redis WATCH/MULTI) |

---

## Success Metrics

### Performance Metrics
- API response time: 500ms → 300ms (40% reduction)
- Database query count: ↓35% (fewer hits on worklist)
- Cache hit rate: 70%+ across all strategies
- P99 latency: <200ms for cached queries

### Reliability Metrics
- Zero stale data incidents in 7-day trial
- Cache invalidation success: 100%
- Redis availability: 99.9%

### Code Quality Metrics
- Test coverage: ≥85% (cache + invalidation logic)
- Documentation: Design + code comments complete
- No new HTTPException (using AppException only)

---

## Dependencies & Prerequisites

### Infrastructure ✅
- Redis 7 running and accessible
- Redis client libraries (redis-py) installed
- Sufficient disk space for Docker volumes

### Code Dependencies
- `backend/app/core/security.py` (JWT handling) — already updated
- `backend/app/core/exceptions.py` (AppException) — already implemented
- `backend/app/api/dicomweb.py` (Orthanc queries) — ready for wrapping

### Testing Requirements
- Load test tool (locust or ab)
- Redis CLI for manual verification
- Integration test environment (Docker Compose)

---

## Open Questions & Assumptions

### Assumptions
1. **Orthanc data is stable within 1-hour windows** (reasonable for clinical workflow)
2. **User permissions don't change mid-session** (standard practice)
3. **Model files updated offline, not during live service** (expected for Phase 3)
4. **Cache misses are acceptable (fallback to query)** ✅

### Questions for User/Design Review
1. Should we implement cache warming (pre-load common queries at startup)? → Deferred to Phase 4
2. Should we add cache statistics dashboard (cache hit/miss rates)? → Phase 5 (monitoring)
3. Should we support manual cache invalidation endpoint for admins? → Yes, add `/admin/cache/purge`

---

## Timeline & Milestones

| Milestone | Date | Status |
|-----------|------|--------|
| Plan approval | 2026-05-13 | In Progress |
| Design document | 2026-05-14 | Pending |
| Implementation start | 2026-05-15 | Pending |
| Phase 1-2 complete (worklist + permissions) | 2026-05-17 | Pending |
| Phase 3-4 complete (metadata + models) | 2026-05-19 | Pending |
| Testing & documentation | 2026-05-20 | Pending |
| Design-implementation match rate ≥95% | 2026-05-20 | Pending |

---

## Effort Breakdown

| Task | Hours | Notes |
|------|:-----:|-------|
| Infrastructure (connection pool, decorators) | 2 | Reusable for future features |
| Worklist caching | 2 | Highest impact |
| Permissions caching | 1 | Simplest, guaranteed hit rate |
| Orthanc metadata caching | 2 | Most complex invalidation |
| AI models caching | 1 | Straightforward |
| Testing & integration | 2 | E2E + load test |
| Documentation & code review | 1 | Design update + architecture diagram |
| **Total** | **11** | Buffer for edge cases |

---

## Design Document Locations

- Current Design: `docs/02-design/features/backend.design.md` (updated with caching section)
- Related Analysis: `docs/03-analysis/backend.analysis.md` (Gap #2: Redis Caching)
- Related Report: `docs/04-report/backend.report.md` (Recommendation: Phase 3 caching)

---

## Next Steps

1. **Get Plan approval** (user review & feedback)
2. **Create Design document** (`/pdca design backend-caching`)
   - Detailed API cache layer architecture
   - Cache key collision prevention strategy
   - Invalidation trigger mappings
3. **Implementation** (`/pdca do backend-caching`)
4. **Gap analysis & testing** (`/pdca analyze backend-caching`)
5. **Completion report** (`/pdca report backend-caching`)

---

## Approval

**Plan Status**: ⏳ Pending User Review  
**Estimated Review Time**: 30 minutes  
**Ready for**: Design phase upon approval
