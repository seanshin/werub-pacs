# Plan: backup-dr — OpenPACS 백업/재해복구 자동화

**Feature**: backup-dr
**Phase**: Plan
**Priority**: CRITICAL (운영 리스크 1순위)
**Start Date**: 2026-06-11
**Effort**: 1~2세션

---

## Executive Summary

단일 서버 운영(SPOF)인데 **OpenPACS 데이터는 백업이 전무하다**. 지금 디스크 장애가 나면
환자 영상·판독·감사기록 전부를 복구할 수단이 없다. HospitalRun이 이미 검증된 백업 체계
(매일 pg_dump + GPG AES256, 30일 보존)를 운영 중이므로 같은 패턴을 OpenPACS로 확장하고,
영상 파일 증분 스냅샷·복구 리허설·신선도 감시를 더한다.

## 현재 상태 (2026-06-11 서버 실측)

| 데이터 | 위치 | 크기 | 백업 |
|--------|------|------|:----:|
| hospitalrun DB | docker-postgres-1 | - | ✅ 매일 3시 (pg_dump+GPG, 30일) |
| **openpacs DB** (PACS 메타 + **Orthanc 인덱스** + 판독/감사) | docker-postgres-1 | - | ❌ **없음** |
| **DICOM 영상 파일** | 볼륨 `openpacs_orthanc-db` (`ENABLE_STORAGE: false` → 파일은 디스크) | 97MB (33 studies) | ❌ **없음** |
| 설정 (compose/.env/nginx/오쏘앙크 env) | /home/deploy/openpacs, /etc/nginx | - | ❌ 없음 (수동 .bak 산재) |
| Redis (캐시/큐/알림) | docker-redis-1 (appendonly) | - | 캐시성 — 백업 불필요 판단 |

- 디스크: 315GB 중 170GB 여유 — 로컬 백업 충분
- 기존 자산: `/home/deploy/hospital-run/infra/scripts/backup.sh` 패턴, GPG passphrase 파일,
  `/home/deploy/backups/` 디렉터리, cron 운영 중

## Objectives

1. openpacs DB + DICOM 파일 + 설정의 **자동 일일 백업** (암호화, 보존 정책)
2. **복구 리허설 스크립트** — 백업이 실제 복원 가능함을 정기 증명 (백업은 복원 테스트 전까지는 백업이 아님)
3. **신선도 감시** — 백업 실패/누락 시 PACS 알림 시스템으로 통지 (조용한 실패 방지)
4. 오프사이트 확장 가능 구조 (rsync 대상만 env로 추가하면 되는 형태)

## 설계 방향

### 1. 백업 스크립트 `backup-openpacs.sh` (서버 cron, 매일 03:30 — HospitalRun 3:00과 시차)
- **DB**: `pg_dump openpacs` → gzip → GPG AES256 (기존 passphrase 파일 재사용), 30일 보존
  — Orthanc 인덱스가 openpacs DB에 있으므로 **단일 덤프로 PACS 메타+인덱스 동시 커버**
- **DICOM 파일**: `rsync --link-dest` 일별 하드링크 스냅샷 (`/home/deploy/backups/openpacs/dicom/YYYYMMDD/`)
  — DICOM은 불변(content-addressed)이라 증분 비용 ≈ 신규 영상만. 7일 스냅샷 + 영구 미러 1본
- **설정**: compose/.env/nginx/스크립트 tar → GPG (자격증명 포함이므로 암호화 필수)
- **상태 기록**: 종료 시 Redis `pacs:backup:status`에 JSON SET (성공/실패, 시각, 크기)
  — 호스트에서 redis-cli로 직접(127.0.0.1:6379, requirepass)

### 2. 복구 `restore-openpacs.sh` + 리허설
- DB: 임시 DB(`openpacs_restore_test`)로 복원 → 핵심 테이블 행수 대조(reports, prefetch 등) → 드롭
- DICOM: 스냅샷에서 임시 디렉터리 복원 → Orthanc 파일 수/총량 대조
- 월 1회 리허설 권장 절차를 runbook으로 문서화 (`docs/deployment/backup-dr-runbook.md`)

### 3. 신선도 감시 (백엔드)
- Celery beat 태스크(기존 5분 주기 패턴): Redis `pacs:backup:status` 검사 →
  26시간 초과/실패 상태면 기존 알림 시스템으로 admin 통지 (중복 통지 방지 락)
- `system_health`에 backup 상태 노출 (admin 대시보드에서 확인 가능)

### 4. 오프사이트 (이번 범위는 구조만)
- 스크립트에 `OFFSITE_RSYNC_TARGET` env 훅만 두고 비활성 기본값
- **Open Question**: 오프사이트 대상 — 후보: WeRU.B AI 서버(원격지 GPU 머신, 여유 137GB),
  외부 오브젝트 스토리지. 사용자 결정 필요

## Out of Scope
- PostgreSQL PITR(WAL 아카이빙) — 일일 RPO로 시작, 필요 시 후속
- hospitalrun DB 백업 변경 (기존 체계 유지 — 건드리지 않음)
- Redis 백업 (캐시·큐 성격, appendonly로 충분)

## 성공 기준
1. cron 백업이 운영에서 1회 이상 성공 실행 + 암호화 산출물 생성 확인
2. 복구 리허설: 임시 복원 → 데이터 대조 통과 (DB 행수, DICOM 파일 수)
3. 신선도 감시: 상태 강제 만료 시 알림 발생 확인
4. runbook 문서화 (복구 절차를 제3자가 따라할 수 있는 수준)

## 리스크
| 리스크 | 완화 |
|--------|------|
| 백업 중 Orthanc 쓰기(영상 수신)와 경합 | DICOM은 불변 파일 — rsync 스냅샷 안전. DB는 pg_dump 트랜잭션 일관성 보장 |
| GPG passphrase 파일 분실 = 백업 전체 무용 | runbook에 passphrase 보관 절차 명시 (이미 HospitalRun 동일 리스크 존재 — 공유) |
| 영상 증가 시 디스크 압박 | 하드링크 증분이라 실증가분만 점유 + du 모니터링, 80% 알림은 기존 모니터링 활용 |
| cron 조용한 실패 | 신선도 감시(3번)가 본 기획의 핵심 차별점 |
