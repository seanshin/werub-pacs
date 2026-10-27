# WeRU.B PACS — 설치 전제조건

> 신규 의료기관(클리닉/중소병원) 1대 온프레미스 서버 설치 기준. 자동 점검:
> `bash scripts/install/preflight.sh` (읽기 전용 — 시스템 변경 없음).

## 1. 하드웨어 (최소 / 권장)

| 항목 | 최소 | 권장 | 비고 |
|------|:----:|:----:|------|
| CPU | 4 코어 | 8+ 코어 | AI 추론·뷰어 동시 부하 |
| RAM | 8 GB | 16+ GB | PostgreSQL·Orthanc·AI 워커 |
| 디스크(OS) | 50 GB SSD | 100 GB SSD | 컨테이너·로그·DB |
| 디스크(영상) | 100 GB | **전용 파티션**, 검사량×5년 산정 | DICOM 보존(의료법 5년) |
| GPU | 불필요 | 선택(AI 가속) | 없으면 CPU 폴백/외부 AI |

> 영상 용량 예시: 흉부 CR ~수 MB, CT/MR 1검사 ~수십~수백 MB. 일 검사량 × 평균 용량 × 365 × 5년 + 여유 30%.

## 2. 소프트웨어

| 항목 | 요구 |
|------|------|
| OS | Linux x86_64 (Ubuntu 22.04+/RHEL 8+ 등). ARM64는 이미지 멀티아치 확인 |
| Docker Engine | 24.x+ |
| Docker Compose | **v2 (plugin)** — `docker compose version` |
| 시간 동기 | NTP/chrony (TAT·SLA·감사 시각 정확도) |
| 로케일 | `ko_KR.UTF-8` (한글·리포트) |
| 타임존 | `Asia/Seoul` (설치 `.env` TIMEZONE과 일치) |

## 3. 네트워크 / 포트

설치 compose는 대부분 포트를 **127.0.0.1(내부)**로 바인딩하고, 외부는 nginx(443)만 공개한다.

| 포트 | 서비스 | 노출 | 설명 |
|:----:|--------|:----:|------|
| 443 | nginx (HTTPS) | **공개** | 모든 웹 접근(관리자·뷰어·API) |
| 80 | nginx (HTTP) | 공개 | 443 리다이렉트 |
| 4242 | Orthanc DICOM | **장비망** | C-STORE/C-FIND/C-MOVE (모달리티 수신) |
| 4243 | MWL SCP | 장비망 | Modality Worklist 조회 |
| 2575 | HL7 MLLP | HIS망 | HL7 v2 오더/결과(연동 시) |
| 5432 / 6379 | PostgreSQL / Redis | 내부 | 외부 노출 금지 |
| 8042 | Orthanc HTTP | 내부 | DICOMweb(nginx 경유) |
| 8000/8001 | Backend(FastAPI) | 내부 | nginx 경유 |
| 3001 / 3004 | OHIF·Admin / WeRU.B 뷰어 | 내부 | nginx 경유 |
| 3000 / 9090 | Grafana / Prometheus | 내부 | 모니터링(선택) |
| 8080 | Keycloak | 내부 | IdP(선택) |

- **방화벽**: 443은 인가된 망에, DICOM(4242/4243)은 **장비망에서만**. PostgreSQL/Redis는 절대 외부 노출 금지.
- **DICOM 수신**(C-STORE)을 장비에서 받으려면 `docs/cstore-pilot-readiness.md` 참고 후 4242 LAN 노출.

## 4. TLS / 도메인

- 공개 도메인 1개 + **유효한 TLS 인증서**(Let's Encrypt 등). `.env`의 `BASE_URL`과 일치.
- 인증서 경로를 nginx에 마운트. 자동 갱신(certbot) 권장.

## 5. 보안 / 운영 전제

- 시크릿은 설치 시 생성(`openssl rand`), `.env`에만 저장(레포·로그 금지).
- 정기 백업 가동(`scripts/server/backup-openpacs.sh`) + 오프사이트(운영 별도 준비).
- 비-root 컨테이너·보안 헤더는 기본 적용됨.

## 6. 외부 연동 (선택 — 미연동 시 standalone)

| 연동 | 필요 정보 |
|------|----------|
| HIS/RIS SSO | `HOSPITALRUN_AUTH_SECRET` 또는 공통 SSO `HIS_JWKS_URL`/`HIS_JWT_AUDIENCE` |
| 오더 동기화 | `HOSPITALRUN_DB_URL`(읽기 전용) 또는 HL7 |
| AI 서버 | `AI_SERVER_URL`/`AI_API_KEY` (없으면 AI 비활성) |
| 전자서명 | `SIGN_SERVICE_*` (없으면 비활성) |
| 장비 AE | 각 모달리티 AE Title/IP — 설치 후 `외부연동`/장비 등록 |

---

## 설치 진행 체크 (preflight 통과 후)

```
[ ] preflight.sh: FAIL 0
[ ] .env 작성(전제조건 값 + 시크릿 생성)
[ ] TLS 인증서 배치
[ ] (P2) install.sh 실행 → compose up
```

> 점검 임계치(`MIN_CPU`/`MIN_RAM_GB`/`MIN_DISK_GB`)와 영상 저장 경로(`DICOM_PATH`)는
> `scripts/install/preflight.sh` 상단 또는 환경변수로 조정 가능:
> `MIN_RAM_GB=16 DICOM_PATH=/data/dicom bash scripts/install/preflight.sh`
