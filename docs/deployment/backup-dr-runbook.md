# OpenPACS 백업/재해복구 Runbook

**상태**: 스크립트·감시 구현 완료, **정기 백업 미가동** (cron 미등록 — 아래 1줄로 활성화)
**구성요소**: `scripts/server/backup-openpacs.sh`, `restore-openpacs.sh`,
`app/services/backup_monitor.py`(Celery beat 30분), system_health `services.backup`

---

## 1. 활성화 (운영 결정 시)

```bash
# 서버에서 (root crontab 권장 — DICOM 볼륨 읽기에 root 필요)
sudo crontab -l 2>/dev/null | { cat; echo '30 3 * * * /home/deploy/openpacs/scripts/backup-openpacs.sh >> /home/deploy/backups/openpacs/backup.log 2>&1'; } | sudo crontab -
```
- 03:30 — HospitalRun 백업(03:00)과 시차. 첫 실행 후 admin 알림센터에서 이상 없음 확인.
- 활성화 즉시 신선도 감시가 살아있는 상태가 됨(상태 키 생성 후부터 26h 룰 적용).
  비활성 상태에서는 `not_configured`로 조용함.

## 2. 백업 내용물

| 산출물 | 경로 | 암호화 | 보존 |
|--------|------|:------:|------|
| DB 덤프 (PACS 메타+Orthanc 인덱스+판독/감사) | `backups/openpacs/db/openpacs_*.sql.gz.gpg` | GPG AES256 | 30일 |
| DICOM 파일 스냅샷 (하드링크 증분) | `backups/openpacs/dicom/YYYYMMDD/` + `latest` | 평문(root 700) | 7일 스냅샷 |
| 설정 (compose/.env/scripts/nginx) | `backups/openpacs/config/config_*.tar.gz.gpg` | GPG AES256 | 30일 |

- **passphrase**: `/home/deploy/.backup-passphrase` (HospitalRun과 공유).
  **이 파일을 잃으면 암호화 백업 전체가 무용** — 별도 안전한 위치(오프라인)에 사본 보관 필수.
- 오프사이트: `OFFSITE_RSYNC_TARGET=user@host:/path` env로 활성화 (기본 비활성).

## 3. 복구 리허설 (월 1회 권장)

```bash
sudo BACKUP_ROOT=/home/deploy/backups/openpacs bash -c '
  /home/deploy/openpacs/scripts/restore-openpacs.sh --db $(ls -t $BACKUP_ROOT/db/*.gpg | head -1)
  /home/deploy/openpacs/scripts/restore-openpacs.sh --dicom $BACKUP_ROOT/dicom/latest'
```
- DB: 임시 DB `openpacs_restore_test`로 복원 → 핵심 테이블 행수 운영 대조 → 자동 드롭
- DICOM: 파일 수/바이트 대조만 (운영 무접촉)

## 4. 실제 재해 복구 절차 (전체 유실 시나리오)

> 전제: 새 서버에 Docker + compose 스택 구성 완료 (CLAUDE.md 배포 구조)

1. **설정 복원**: `gpg -d config_*.tar.gz.gpg | tar xz` → compose/.env/nginx 배치
2. **DB 복원**:
   ```bash
   gpg -d openpacs_*.sql.gz.gpg | gunzip | docker exec -i docker-postgres-1 psql -U openpacs -d openpacs
   ```
   (사전: `CREATE DATABASE openpacs OWNER openpacs` + uuid-ossp/pgcrypto 확장)
3. **DICOM 복원**: 스냅샷을 볼륨으로 복사
   ```bash
   sudo rsync -a backups/openpacs/dicom/latest/ /var/lib/docker/volumes/openpacs_orthanc-db/_data/
   ```
4. **기동·정합 확인**: `docker compose up -d` → Orthanc `/statistics`의 study/instance 수가
   DB 복원 시점과 일치하는지 확인 (인덱스가 DB에 있으므로 파일·인덱스가 함께 복원되어야 함 —
   **DB와 DICOM 스냅샷은 같은 날짜 세트로 복원할 것**)
5. nginx 사이트 활성화 + certbot 재발급 → 헬스체크 4종(CLAUDE.md 동작 확인 절)

## 5. 감시 동작

- `backup_monitor.check_backup_freshness` (beat 30분): 상태 키 없음=무시(미구성),
  실패 또는 26h 초과=admin 알림(`backup_alert`, high) — 24h 중복 억제
- 확인 위치: admin 알림센터 / `GET /api/v1/system/health-detail` → `services.backup`

## 6. 알려진 제약

- RPO = 최대 24h (일일 백업). PITR(WAL) 필요 시 후속 기획.
- DICOM 스냅샷과 DB 덤프는 같은 03:30 실행 세트가 정합 쌍 — 교차 복원 금지.
- `celery` 큐 라우팅 누락 시 beat 태스크가 영원히 대기함 — 신규 beat 태스크는 반드시
  `task_routes`에 명시 (2026-06-11 auto_validate 1,652건 적체 사고 — v11.5에서 수정).
