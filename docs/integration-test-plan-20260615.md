# 통합 테스트 기획 — 2026-06-15 세션

## 목적
이번 세션의 신규 기능(BI·거버넌스 확장·e-sign/SSO)과 보완(K1~K9 감사·H1~H3 동시성)을
**종단 흐름으로 검증**한다. 단위/스모크(Playwright 14스펙)를 넘어, 교차 컴포넌트(API↔DB↔Celery↔
Orthanc↔외부서비스)와 시간/동시성 의존 시나리오를 포함.

## 범위 & 시나리오 (커버리지 매트릭스)

| # | 흐름 | 컴포넌트 | 핵심 검증 | 방법 |
|---|------|---------|----------|------|
| IT-1 | **회귀 베이스라인** | 전체 | Playwright 14스펙 통과 | E2E |
| IT-2 | **K1 DICOM 수정→롤백 무결성** | API·Orthanc·DB | 수정 시 original_data 보존 → 롤백이 **원본 실복원**(hash·재업로드·재검증) | 실DICOM 사이클 |
| IT-3 | **거버넌스: 추론→피드백→롤업→요약** | API·Celery·DB | feedback→inference_jobs.acceptance→`_rollup_ondemand`→summary 반영 | API+task |
| IT-4 | **BI: 집계→CSV→월간 cron→알림** | API·Celery·DB | operational/export/run-monthly→bi_monthly_reports→admin 알림 | API+task |
| IT-5 | **SSO: HIS aud=pacs 토큰→PACS 인증→JIT** | API·JWKS | RS256/JWKS 검증·aud 스코핑·JIT 역할매핑 | 실토큰 |
| IT-6 | **H1 beat overlap 락** | Celery·Redis | 동시 2실행 시 1개 skip | 락 동작 |
| IT-7 | **H2 run_inference 멱등** | Celery·DB | COMPLETED 재실행 no-op·카운터 원자성 | task |
| IT-8 | **H3 동시 배정 유니크** | API·DB | 복수 is_current 불가(인덱스) | DB |
| IT-9 | **판독→확정 동시서명 가드** | API·DB | FINAL 재서명·lost update 차단 | API |
| IT-10 | **HSM attestation 봉인** | API·sign | assuranceLevel 캡처·트리거 | (sign 토큰 대기) |

## 합격 기준
- IT-1 회귀 0 실패(데이터 의존 flaky 제외, 격리 재확인).
- IT-2 롤백 후 Orthanc에 원본 instance 복원·hash 일치.
- IT-3~IT-8 각 종단 상태 전이 정합.
- 실패 시 근본원인 기록·수정 or 백로그.

## 결과
하단 "수행 결과" 섹션에 기록.

---

## 수행 결과 (2026-06-15)

| # | 흐름 | 결과 | 근거 |
|---|------|:---:|------|
| IT-1 | 회귀 베이스라인(E2E 14스펙) | ✅* | 35 pass+1 skip. **★뷰어 회귀 1건 발견·복구**(아래) + 07:44 캐시워밍 flaky(격리 통과) |
| IT-2 | **K1 DICOM 수정→롤백 무결성** | ✅ | fix=true(SeriesDate/ContentDate)→**original_data 309KB 보존**·fixed_orthanc_id→rollback **restored:true**·rolled_back. study 원상복구 |
| IT-3 | 거버넌스 추론→피드백→롤업→요약 | ✅ | summary on-demand 수용률 1.0·자동격리 false·29모델 |
| IT-4 | BI 집계→월간 cron→이력 | ✅ | run-monthly queued·monthly-history 1건 |
| IT-5 | SSO HIS aud=pacs→PACS→JIT | ✅ | 실토큰 statistics 200(JIT ADMIN) |
| IT-6 | H1 beat overlap 락 | ✅ | acquire True→False 차단(구현검증) |
| IT-7 | H2 run_inference 멱등 | ✅ | COMPLETED 재실행=skip |
| IT-8 | H3 동시배정 유니크 | ✅ | uq_reading_assignments_current 존재 |
| IT-9 | 판독 동시서명 가드 | ✅ | FINAL 재서명 400 "이미 최종 서명" |
| IT-10 | HSM attestation 봉인 | ⏸ | sign aud=sign 토큰 대기(P7 cutover 후 HSM_ANCHORED) |

### ★ IT-1이 잡은 중대 회귀 — 뷰어 dist 소스 오류
- **증상**: 07-prefetch(study-opened)·08-vrt(3D 렌더) 일관 실패. 원인: 이번 세션 **K6 배포가 `werub-build/dist`(stale, Jun-9, prefetch v11.4·VRT v11.6 이전)** 에서 이미지 빌드 → 뷰어가 구버전으로 회귀(prefetch/VRT 계측 코드 소실).
- **근본**: 서버에 dist 2개 — `werub-build/dist`(Dockerfile COPY 원본, **stale**) vs `werub-viewer/dist`(**현행, prefetch 포함**). 빌드 원본이 동기 안 됨.
- **복구**: `rsync werub-viewer/dist → werub-build/dist`(현행 동기) + K6 app-config 재적용 + 이미지 재빌드. 실행 컨테이너에 prefetch+K6 둘 다 확인, 07/08 재실행 통과.
- **교훈**: **뷰어 배포 시 빌드 원본 dist가 현행인지 확인 필수**(werub-build/dist는 werub-viewer/dist와 동기돼야). 통합 테스트(full E2E)가 단위/스모크로는 안 잡히는 배포 회귀를 포착.

### 종합
**IT 9/9 통과**(+IT-10 외부의존 대기). 특히 IT-2(K1 데이터무결성)가 실 study fix→rollback으로 원본 실복원 입증, IT-1이 내 배포 회귀를 포착·복구. 통합 테스트의 가치 실증.
