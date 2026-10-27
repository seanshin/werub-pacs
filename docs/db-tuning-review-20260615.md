# DB 튜닝·보완 검토 (2026-06-15)

연결 누수 이슈를 계기로 OpenPACS DB 전반 점검. 공유 postgres(`docker-postgres-1`,
PG 16.13, max_connections=200, HospitalRun·erp·sign·twin 공존) — **글로벌 설정은 신중**,
OpenPACS 한정 보완 위주.

## 현황 (양호)
- **인덱스 커버리지 양호**: reports(study/status/patient/tenant), audit_logs(action/study/tenant),
  ai_screening_results(actionable/status), sla_escalation_log(study/time), viewer_open_events(opened).
  핫 쿼리 대부분 커버 — 추가 인덱스 시급성 없음.
- **DB 19MB 소형**(테스트 데이터). effective_cache_size=8GB로 충분 → 현재 성능 병목 없음.
- **연결 60/200**(누수 수정 후 안정, idle 59=풀 보유분). 헤드룸 119.
- openpacs DB 연결은 전부 **openpacs role**(backend·celery·Orthanc 공유, app_name 빈값).

## 적용 (안전 — OpenPACS 한정, HospitalRun 무영향)
1. **연결 누수 근절**(앞선 커밋 d19e178): beat 작업 `_get_sync_db` per-call `create_engine` → 전역 캐싱.
2. **idle 회수 백스톱**(role 레벨):
   - `ALTER ROLE openpacs SET idle_session_timeout = '2h'` — 고아 idle 연결 자동 회수(누수가 14h
     방치되던 원인=회수 미설정). 정상 풀은 pool_recycle(30~60분)로 먼저 순환 → 2h는 진짜 고아만 타격.
   - `ALTER ROLE openpacs SET idle_in_transaction_session_timeout = '15min'` — 스턱 트랜잭션 회수.
   - **per-role이라 HospitalRun/erp/sign 무영향**. 신규 연결부터 적용(기존 풀은 순환 후).

## 권고 (보류·조건부 — 공유 인프라 or 저우선)
| 항목 | 현재 | 권고 | 판단 |
|---|---|---|---|
| shared_buffers | 128MB | ~1GB(RAM 25%) | **보류** — DB 19MB라 불필요, 글로벌·HospitalRun 영향·재시작 필요. 데이터 대량 증가 시 재검토 |
| work_mem | 4MB | 16MB | 보류 — 동일(글로벌). 복잡 쿼리 느려지면 |
| 백엔드 pool max_overflow | 10 (worker당 최대 15) | 5 (최대 10) | 선택 — 4워커×15=60 가능, 헤드룸 충분이라 현행 유지. 공유 DB 압박 시 축소 |
| consent_signatures(patient_id) 인덱스 | pkey만 | 추가 | 선택 — 테이블 소형, 풀스캔 무방 |
| pg_stat_statements | 미설치 | 설치 | 보류 — shared_preload_libraries+재시작(글로벌). 쿼리 프로파일 필요 시 |

## 연결 예산 (참고)
- backend(gunicorn 4워커 × pool_size5+overflow10) 최대 60 + celery(2 × pool2~5) ~10 + celery-beat + Orthanc 풀.
- 정상 ~60, 버스트 시 ~100. 공유 200에서 헤드룸 OK. **앱-사이드 캐싱 + role idle 회수로 누수 차단**이 핵심.

## 결론
**인덱스·용량은 양호**, 실질 리스크였던 **연결 누수는 앱 캐싱(근본) + role idle 회수(백스톱) 이중 차단**.
글로벌 PG 메모리 튜닝은 현 규모(19MB)에서 불필요·고위험(공유)이라 데이터 증가 시점으로 보류.
