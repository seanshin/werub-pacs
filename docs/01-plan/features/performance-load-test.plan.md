# Performance Load Test Plan

## 개요
OpenPACS v8.3 시스템의 성능 한계를 측정하고 병목을 식별한다.
목표: **동시 50명 사용자**, **일 1,000 Study** 처리 능력 검증.

## 배경
- 파일럿 병원 투입 전 성능 기준선(baseline) 확보 필요
- 현재 13개 Docker 컨테이너, 225+ API 엔드포인트
- PostgreSQL 16 + Redis 7 + Orthanc + FastAPI (uvicorn)

## 테스트 도구
- **Locust** (Python 기반) — FastAPI와 동일 언어, 시나리오 작성 용이
- 로컬 실행 → 서버(198.51.100.73) 대상 원격 부하

## 테스트 시나리오

### Scenario 1: API 응답 성능 (핵심 엔드포인트)
| 엔드포인트 | 메서드 | 목표 p95 | 비중 |
|-----------|--------|---------|------|
| `/pacs-api/health` | GET | < 100ms | 5% |
| `/pacs-api/api/v1/statistics` | GET | < 500ms | 10% |
| `/dicom-web/studies` | GET | < 1s | 20% |
| `/dicom-web/studies/{id}/series` | GET | < 1s | 15% |
| `/pacs-api/api/v1/worklist` | GET | < 500ms | 15% |
| `/pacs-api/api/v1/reports` | GET/POST | < 1s | 15% |
| `/pacs-api/api/v1/reading-stats/*` | GET | < 2s | 10% |
| `/pacs-api/api/v1/dashboard` | GET | < 2s | 10% |

### Scenario 2: 동시 사용자 부하 (Concurrent Users)
- **Ramp-up**: 0 → 50 users over 2분
- **Sustained**: 50 users × 5분
- **Peak**: 50 → 100 users × 2분 (한계 탐색)
- 측정: RPS, p50/p95/p99 응답시간, 에러율

### Scenario 3: Study 대량 처리 시뮬레이션
- Orthanc REST API로 DICOM 파일 업로드 (C-STORE 시뮬레이션)
- 목표: 시간당 ~42 Study (= 일 1,000)
- 측정: 업로드 처리시간, DB 인덱싱 지연, DICOMweb 검색 성능 변화

### Scenario 4: WebSocket 동시 연결
- 50개 동시 WebSocket 연결 (`/pacs-api/ws/notifications`)
- 알림 브로드캐스트 지연시간 측정

## 성능 기준 (Pass/Fail)

| 지표 | 기준 | 심각도 |
|------|------|--------|
| API p95 응답시간 | 각 엔드포인트 목표 이내 | Critical |
| 에러율 (5xx) | < 1% | Critical |
| 동시 50명 시 RPS | > 100 req/s | High |
| WebSocket 연결 유지 | 50개 × 10분 무중단 | High |
| Study 업로드 처리율 | > 42/hr (1,000/day) | High |
| DB 커넥션 풀 소진 | 없음 | Critical |
| Redis 메모리 | < 256MB | Medium |
| CPU 사용률 | < 80% (sustained) | Medium |

## 산출물
1. `tests/load/locustfile.py` — Locust 테스트 시나리오
2. `tests/load/README.md` — 실행 방법
3. `docs/04-report/features/performance-load-test.report.md` — 결과 리포트
4. 병목 식별 및 개선 권고 사항

## 구현 순서
1. Locust 설치 및 테스트 프레임워크 셋업
2. JWT 인증 포함 API 시나리오 작성
3. DICOMweb/Orthanc 시나리오 작성
4. WebSocket 시나리오 작성
5. 로컬에서 스모크 테스트 (5명)
6. 서버 대상 풀 부하 테스트 실행
7. 결과 분석 및 리포트 작성
8. 병목 발견 시 최적화 수행

## 리스크
- 운영 서버 대상 부하 → HospitalRun에 영향 가능 → **비업무 시간 실행**
- 테스트 데이터 부족 시 성능 편차 → 사전 더미 데이터 생성 필요
- Nginx rate limiting이 있다면 테스트 결과 왜곡 → 사전 확인 필요

## 제외 항목
- DICOM C-STORE 프로토콜 직접 테스트 (파일럿 트랙에서 별도 수행)
- AI 추론 성능 (GPU 의존, 별도 벤치마크)
- OHIF Viewer 프론트엔드 렌더링 성능 (브라우저 의존)
