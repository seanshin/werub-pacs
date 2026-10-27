# PACS 기본 기능 강화 계획 (pacs-fundamentals) — 2026-07-11

> 코어 영상 체인(수신→검증→저장→조회→판독→보존) 전수 실사 + 운영 서버 실측 기반.
> 총평: 응용 기능은 과잉 수준이나 **기본기 갭은 "데이터 안전·운영 연속성" 한 축에 집중**.
> 실측 근거: 조사 시점 호스트 디스크 86%(잔여 44GB, 원인=docker build cache 210GB) +
> 백업 cron 미가동 + 디스크 감시는 Orthanc 논리용량(95MB)만 관측 — 실 리스크 조합.

## 기본기 충족 확인 (강점 — 재투자 불필요)
JPEG 밀도 교차검증(JFIF vs PixelSpacing, 핵심 요구)·검증 24규칙, MPPS·Storage Commitment
실구현, IOCM 아카이브+5년 보존 잠금(의료법 제22조), prior 자동조회+prefetch, 리포트
템플릿/매크로, 파괴작업 BTG 차단·전 과정 감사로그.

## 1축. 데이터 안전 — **v13.15에서 완료** ✅
사용량과 무관하게 가치 있는 유일한 축(사고는 확률).
- ✅ 백업 cron 가동(03:30, HospitalRun 03:00과 시차) + 1회 실행·복구 리허설 PASS
- ✅ 호스트 디스크 워터마크 감시(beat 30분, 85/95%, 레벨 상승 시 즉시 재알림) +
  health-detail `services.host_disk`
- ✅ 보존기간(5년) 만료 활성 study 월간 스캔→admin 알림 + `GET /archive/retention/candidates`
  (자동 삭제 없음 — 기존 수동 아카이브 경로가 담당)
- ✅ `dicom_quarantine` 죽은 모델 제거(validation_results가 이슈추적 담당)
- ✅ 디스크 정리: build cache 207GB 회수(86%→27%)

## 2축. 운영 가시성 완성 — **v13.16에서 완료** ✅
- ✅ ~~exporter 배치~~ — 실사 결과 서버엔 이미 존재(server-ahead 드리프트) → 레포 정본에 흡수
- ✅ alertmanager(9095) + 알림 규칙 7종 → backend webhook → admin 알림센터(종단 검증)
- ✅ 도메인 메트릭 `pacs_*`(수신량/검증실패/큐 길이/디스크) — lifespan 30s 갱신
- ⏳ email 알림 — **SMTP 자격증명 확보 시**(운영 결정): alertmanager email receiver
  (backend-down 커버, 유일한 미커버 시나리오) + alert_service email 활성화

## 3축. DICOM 적합성 심화 (게이트 명시)
| 항목 | 게이트 |
|------|--------|
| DICOM TLS(4242 평문) | **✅ 옵션 구현(v13.23, default-off)** — 설치 제품용. `gen-dicom-tls.sh`+orthanc.json TLS키+compose env+`it-dicom-tls.sh`(격리 TLS C-ECHO 3종 검증). 활성 시 4242 TLS 전용(모달리티 전원 TLS 지원 시). 전체 강제(비TLS 모달리티 배제)는 클리닉 결정 게이트 |
| J2K 저장 압축 | Orthanc 저장량 수십 GB 도달 시(현재 161MB — 실익 0. 전송 압축은 v11.0 완료) |
| C-GET | 요구 장비 발생 시(C-MOVE로 충족 중) |

## 4축. 판독 기본기 — **핵심 2종 v13.17에서 완료** ✅
- ✅ 모달리티별 자동 HP(werubAutoMPR — 재구성 가능 CT/MR→MPR 자동, 단면 1×1 폴백)
- ✅ prior 원클릭 비교(툴바 '이전검사'+단축키 p → hpCompare) — 서버·뷰어 자산 연결
- 잔여(수요 시): 툴바 큐레이션(현재 적정 규모라 미착수), 판독 흐름 워크리스트 이동 단축키.
  사용자 결정으로 실사용 게이트보다 선행(UX 장벽 가설) — 효과는 vrt_metrics·프리셋
  텔레메트리로 사후 측정.

## 하지 않을 것
- HA 이중화(Orthanc/PG/backend 단일): 단일기관 저부하 과투자 — 백업+복구 리허설
  정례화(월 1회, runbook §3)로 갈음. B1 멀티테넌시/SaaS 착수 시 재검토.
- 콜드 스토리지 계층화(S3/Glacier enum만 존재): 용량 문제 실측 시.
- audit log purge: 무기한 보존이 컴플라이언스상 유리 — 용량 문제 발생 전까지 유지.

**관련**: 릴리즈 `docs/releases/v13.15.md`, 백업 runbook `docs/deployment/backup-dr-runbook.md`
