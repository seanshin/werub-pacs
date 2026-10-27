# Design: backup-dr — OpenPACS 백업/재해복구 자동화

**Feature**: backup-dr
**Phase**: Design
**Date**: 2026-06-11
**Plan**: `docs/01-plan/features/backup-dr.plan.md`
**범위 제약(사용자 지시)**: **구현+테스트까지만. 실제 정기 백업은 미가동(cron 미등록).**
가동은 runbook의 1줄 cron 등록으로 활성화.

---

## 1. 구성요소

```
[cron(미등록)] → backup-openpacs.sh ─┬─ pg_dump openpacs | gzip | gpg → backups/openpacs/db/
                                      ├─ rsync --link-dest DICOM 스냅샷 → backups/openpacs/dicom/YYYYMMDD/
                                      ├─ tar 설정(.env/compose/nginx) | gpg → backups/openpacs/config/
                                      └─ docker exec redis-cli SET pacs:backup:status {JSON}
[Celery beat 30분] backup_monitor.check_backup_freshness
   └─ status 없음 → 무시(미구성)  /  26h 초과·failed → notifications(admin, 중복방지 락 24h)
[admin] GET /api/v1/system/health-detail → services.backup 섹션 노출
[복구] restore-openpacs.sh — 임시 DB 복원+행수 대조, DICOM 스냅샷 파일수 대조 (리허설용)
```

## 2. backup-openpacs.sh (서버 `/home/deploy/openpacs/scripts/`)

- env 오버라이드: `BACKUP_ROOT`(기본 /home/deploy/backups/openpacs), `RETENTION_DAYS=30`,
  `DICOM_SNAPSHOT_DAYS=7`, `OFFSITE_RSYNC_TARGET`(기본 빈값=비활성)
- DB: `docker exec docker-postgres-1 pg_dump -U openpacs -d openpacs` → gzip → GPG AES256
  (passphrase 파일 `/home/deploy/.backup-passphrase` — HospitalRun과 공유)
- DICOM: 소스 `/var/lib/docker/volumes/openpacs_orthanc-db/_data/` (sudo 필요 → cron은 root
  또는 sudoers 항목; 테스트는 sudo 직접 실행). `rsync -a --link-dest=../latest` 스냅샷
  + `latest` 심링크 갱신. `DICOM_SNAPSHOT_DAYS` 초과 스냅샷 삭제(하드링크라 실데이터는 잔존 스냅샷이 보존)
- 설정: openpacs compose/.env/스크립트 + /etc/nginx/sites-enabled/hospital-run → tar.gz → GPG
- 상태: 성공/실패와 무관하게 마지막에 `pacs:backup:status` SET —
  `{"ok":bool,"ts":epoch,"db_bytes":n,"dicom_files":n,"dicom_bytes":n,"config_bytes":n,"err":"..."}`
- 실패 시 exit≠0 + status.ok=false (set -euo pipefail + trap)

## 3. restore-openpacs.sh (리허설)

- `--db <dump.gpg>`: gpg 복호 → `openpacs_restore_test` DB 생성·복원 → 검증 쿼리
  (reports/audit_logs/prefetch_history 등 행수 운영 대조) 출력 → `--keep` 없으면 드롭.
  **DB 생성/드롭은 슈퍼유저(hospital)로** — openpacs 계정은 CREATEDB 권한 없음(테스트 실증)
- `--dicom <snapshot-dir>`: 파일 수·총 바이트를 운영 볼륨과 대조 출력 (복사 없음 — 검증만).
  `latest` 심링크는 `readlink -f`로 해소(find/du가 심링크 미추적 — 테스트 실증)
- 운영 볼륨/DB는 **절대 쓰지 않음** (복원은 임시 객체로만)

## 4. backup_monitor.py (Celery beat, queue=default)

- `check_backup_freshness` 30분 주기 (beat_schedule 추가 → celery 재빌드)
- **task_routes 명시 필수** — 구현 중 발견: 미라우팅 태스크는 워커가 소비하지 않는 `celery`
  큐로 가며, `dicom_auto_validate`가 이 패턴으로 **1,652건 적체·~6일간 미실행**되고 있었음
  (잠재버그, 본 릴리즈에서 라우팅 추가 + 적체 큐 드레인으로 수정)
- 로직: Redis `pacs:backup:status` GET →
  - 키 없음 → return "not_configured" (알림 없음 — 백업 미가동 상태 오탐 방지)
  - ok=false 또는 ts가 26h 초과 → 알림 1건 (notifications INSERT, target_role=admin,
    urgency=high) + 중복 방지 락 `pacs:backup:alerted` TTL 24h
- system_health `health-detail`의 services에 `backup` 섹션 추가:
  `{status: ok|stale|failed|not_configured, last_ts, age_hours}`

## 5. runbook (`docs/deployment/backup-dr-runbook.md`)

활성화(1줄 cron), passphrase 보관 수칙, 복구 절차(전체 유실 시나리오 단계별),
리허설 절차(월 1회), 오프사이트 활성화 방법.

## 6. 테스트 계획 (실백업 미가동 제약 내)

| 테스트 | 방법 | 합격 기준 |
|--------|------|----------|
| 백업 1회 실행 | 서버에서 `BACKUP_ROOT=/tmp/backup-test ./backup-openpacs.sh` 수동 실행 | exit 0, 산출물 3종 생성, GPG 복호 가능, status JSON ok=true |
| 복구 리허설 | `restore-openpacs.sh --db <테스트 산출물>` | 임시 DB 행수 = 운영 행수, 자동 드롭 |
| DICOM 검증 | `--dicom /tmp/backup-test/dicom/latest` | 파일 수 = 운영 볼륨 파일 수 |
| 신선도 감시 | Redis에 ts=48h 전 가짜 status SET → beat 태스크 수동 트리거 | admin 알림 1건 생성, 재실행 시 중복 없음 |
| 미구성 무시 | status 키 삭제 후 태스크 실행 | 알림 없음, health-detail=not_configured |
| 정리 | /tmp/backup-test, 가짜 키, 알림 락 삭제 | 운영 흔적 없음 |

## 7. 보안

- 모든 산출물 GPG AES256 (DB 덤프=PHI, 설정=자격증명)
- DICOM 스냅샷은 평문 보관(원본 볼륨과 동일 보호 수준 — 같은 호스트 디스크, root 소유 700)
- 스크립트에 비밀번호 하드코딩 금지 — pg는 docker exec(소켓 신뢰), GPG는 passphrase 파일
