# 성능 검토 — 2026-06-15 (측정 주도)

## 방법론
코드 리뷰가 아닌 **실측 우선** — 운영 시스템의 PG 통계·엔드포인트 지연·리소스로 실제
병목을 찾고, 개선 후 재측정으로 효과 확인.

## 측정 결과 (개선 전)
- **엔드포인트 지연**: reading-queue **0.52s**(나머지의 3배·최대 병목), statistics 0.19s, BI 0.17s, governance 0.17s, notifications 0.18s.
- **PG seq scan**(우리 테이블): reports 195k·**study_provenance 94k(idx_scan 0)**·notifications 8k — 작아서 현재는 싸나 빈번 + 5년 보존 성장 시 병목.
- **리소스**: backend 0.39% CPU·3.5% MEM, orthanc 0.32%, docker-postgres 0.24% — **리소스 병목 없음**.

## 발견 & 개선

### P1. [핵심] reading-queue Orthanc N+1 → 1콜 (0.52s→0.20s, ~60%↓)
- 원인: `GET /studies`(ID 목록) + **N×`GET /studies/{id}`**(33건, 병렬화해도 ~0.5s) + modality 빈 경우 **시리즈 폴백 N+1**.
- 개선: **Orthanc `/tools/find` `Expand:true` + `RequestedTags:["ModalitiesInStudy"]`** — 33 study 전체 메타를 **1콜·11ms**. study detail N+1 + 시리즈 폴백 N+1 **둘 다 제거**.
- 효과: 0.52s→0.20s. 빈번 폴링 엔드포인트라 reports/provenance seq_scan 압력도 동반 감소.

### P2. check_sla(beat) 동일 N+1 → 1콜 (~183ms)
- 5분 beat가 `/tools/find` + **200×`GET /studies/{id}`** + 시리즈 폴백 → 작업 길어짐(다음 beat와 겹칠 위험·H1 락 점유 연장).
- 동일 Expand 패턴 적용. 183ms로 단축.

### P3. notifications 성장 인덱스
- 빈번 폴링(벨 배지)·`ORDER BY created_at DESC` — `ix_notifications_created_at(DESC)`·`ix_notifications_target_role` 추가(prod). 성장 시 정렬/스코프 필터 가속.

### 양호 확인 (개선 불요)
- reports·study_provenance·inference_jobs: study_instance_uid·status·patient_id 등 **이미 잘 인덱싱**.
- study_provenance idx_scan 0은 **BI 전체 집계(GROUP BY date_trunc)** 특성 — 인덱스로 가속 불가(전수 집계). 테이블 작아 무해.
- my-patients: DB 쿼리 기반(N+1 없음). gzip/HTTP2: v11.0 적용됨. 리소스: 여유.

## 개선 후 측정
- reading-queue **0.20s**, today 0.21s, statistics 0.18s — **전 엔드포인트 ~0.2s로 균등화**(reading-queue outlier 해소).
- check_sla beat **183ms**.

## 잔여(동일 패턴·낮은 우선순위)
- `reading_assignment.auto_assign`(200 study GET N+1) — admin 수동 트리거(비핫). 동일 Expand 적용 권장.
- BI 트렌드의 study_provenance 전수 집계 — 성장 시 received_at 범위 제한 or 사전집계(materialized) 고려.
- pg_stat_statements 확장 미설치 — 쿼리 누적시간 정밀 분석엔 설치 권장.
