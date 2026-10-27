# Performance Load Test Report

**Version**: v8.4
**Date**: 2026-05-21
**Target**: https://his.example.org (Linode VPS, 8 CPU cores)

## Executive Summary

OpenPACS v8.4 성능 부하 테스트를 완료했다. **동시 50명 및 100명 모두 PASS**.
초기 100명 테스트에서 503 에러 발생 → gunicorn 4워커 + Nginx rate limit 튜닝 후 **에러율 0% 달성**.

| 테스트 | 사용자 | 결과 | 에러율 | p95 | RPS |
|--------|--------|------|--------|-----|-----|
| Smoke | 5명 | PASS | 0% | 140ms | 2.7 |
| **Full** | **50명** | **PASS** | **0%** | **120ms** | **26** |
| Peak (before tuning) | 100명 | FAIL | 5.82% | 190ms | 49.3 |
| **Peak (after tuning)** | **100명** | **PASS** | **0%** | **180ms** | **49** |

## Test 1: API Load (Locust, 50 users, 5 min)

### Result: PASS

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Total Requests | 7,380 | - | - |
| Error Rate | 0.00% | < 1% | PASS |
| p50 | 51ms | - | - |
| p95 | 120ms | < 2,000ms | PASS |
| p99 | 190ms | - | - |
| RPS | 26.0 | > 10 | PASS |

### Endpoint Performance (p95)

| Endpoint | p95 | Status |
|----------|-----|--------|
| /health | 49ms | Excellent |
| /worklist/[id] | 49ms | Excellent |
| /sla/config | 53ms | Excellent |
| /statistics | 55ms | Excellent |
| /system/info | 57ms | Excellent |
| /notifications | 58ms | Excellent |
| /reports | 59ms | Excellent |
| /dashboard/today | 60ms | Excellent |
| /templates | 64ms | Good |
| /worklist | 99ms | Good |
| /emergency/board | 100ms | Good |
| /dicom-web/studies | 130ms | Good |
| /worklist [POST] | 130ms | Good |
| /dicom-web/studies/[uid]/metadata | 190ms | Acceptable |
| /dicom-web/studies/[uid]/series/[uid]/instances | 210ms | Acceptable |
| /auth/login | 280ms | Acceptable (bcrypt) |

## Test 2: Study Upload Throughput (50 studies)

### Result: PASS

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Total Studies | 50 | - | - |
| Success Rate | 100% | > 95% | PASS |
| Total Time | 4.5s | - | - |
| Throughput | 39,783/hr | > 42/hr | PASS (947x) |
| Upload Avg | 0.44s | - | - |
| Upload p95 | 0.82s | - | - |
| Search Before | 122ms | - | - |
| Search After | 99ms | - | - |
| Search Degradation | -19% | < 100% | PASS (improved) |

## Test 3: WebSocket Concurrent Connections (50)

### Result: PASS

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Connections | 50/50 | > 95% | PASS |
| Disconnections | 0 | < 10% | PASS |
| Connect Time Avg | 314ms | - | - |
| Connect Time p95 | 420ms | - | - |
| Messages Received | 12 | - | - |

## Test 4: Peak Load (100 users, 5 min)

### Result: FAIL (capacity limit identified)

| Metric | Value | Target |
|--------|-------|--------|
| Total Requests | 14,659 | - |
| Error Rate | 5.82% | < 1% |
| p50 | 53ms | - |
| p95 | 190ms | - |
| p99 | 370ms | - |
| RPS | 49.3 | - |

### Error Breakdown
- **503 Service Unavailable**: 827건 (97%) — uvicorn 워커 포화
- **401 Unauthorized**: 26건 (3%) — 로그인 실패 후 토큰 없이 요청

## Bottleneck Analysis

### 50명 이하: 병목 없음
- 모든 엔드포인트 p95 < 300ms
- DB 커넥션 풀 여유
- Redis 응답 < 5ms

### 100명에서 발생하는 병목
1. **uvicorn 워커 수**: 기본 1 워커 → 동시 처리 한계
2. **Nginx upstream 커넥션**: 동시 100개 초과 시 503 반환
3. **DB 커넥션 풀**: SQLAlchemy 기본 pool_size=5

## Tuning Applied (100명 PASS 달성)

| 조치 | Before | After | 효과 |
|------|--------|-------|------|
| WSGI 서버 | uvicorn --reload (1 worker) | gunicorn -w 4 -k UvicornWorker | 동시 처리 4x |
| Nginx rate limit | 30r/s burst=50 | 100r/s burst=200 | 503 제거 |
| DB pool | pool_size=20, max_overflow=10 | (이미 충분) | — |

### 100명 튜닝 후 결과

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Total Requests | 14,725 | - | - |
| Error Rate | 0.00% | < 1% | PASS |
| p50 | 56ms | - | - |
| p95 | 180ms | < 2,000ms | PASS |
| p99 | 220ms | - | - |
| RPS | 49.0 | > 10 | PASS |

## Bug Found & Fixed

**reading_stats 라우터 순서 버그**: `/api/v1/reports/statistics` 경로가 `/api/v1/reports/{report_id}`에 가려져 422 반환.
- **원인**: `main.py`에서 `report_router`(302행)가 `reading_stats_router`(340행)보다 먼저 등록
- **수정**: `reading_stats_router`를 `report_router` 앞으로 이동

## Test Artifacts

```
tests/load/
├── locustfile.py           # API 부하 (19 엔드포인트)
├── websocket_test.py       # WebSocket 동시 연결
├── study_upload_test.py    # DICOM 업로드 처리량
├── requirements.txt        # locust, websockets, httpx, pydicom
├── run_all.sh              # 통합 실행 (smoke/full)
└── results/                # CSV + HTML 리포트
```

## Conclusion

OpenPACS v8.4는 **동시 100명, 일 1,000 Study** 처리 기준을 **에러율 0%로 달성**한다.
- 50명: p95=120ms, RPS 26
- 100명: p95=180ms, RPS 49 (gunicorn 4워커 + Nginx 튜닝 후)
- 업로드: 39,783 studies/hr (목표의 947배)

중소 병원/클리닉 파일럿 투입에 성능 문제는 없다.
