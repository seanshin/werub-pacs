# TD-003 소프트웨어 아키텍처 설계서 (Software Architecture Document)

| 항목 | 내용 |
|------|------|
| 문서 ID | TD-003 |
| 버전 | 1.0 |
| 작성일 | 2026-05-18 |
| 상태 | 승인 |
| 적용 표준 | IEC 62304:2006+A1:2015 §5.3 |
| 제품명 | WeRU.B PACS |
| 검토일 | 2026-05-27 |
| 승인일 | 2026-05-27 |

## 1. 목적

WeRU.B PACS 시스템의 전체 아키텍처를 기술하고, Docker 컨테이너 구성, 데이터 흐름, 네트워크 구성, DICOMweb 통합 방식을 정의한다.

## 2. 배포 아키텍처 (Docker Compose)

### 2.1 컨테이너 구성

| 서비스 | 이미지 | 포트 (Host) | 역할 |
|--------|--------|-------------|------|
| postgres | postgres:16-alpine | 127.0.0.1:5432 | 관계형 DB (openpacs DB) |
| redis | redis:7-alpine | 127.0.0.1:6379 | 캐시, 세션, 메시지 브로커 |
| orthanc | orthancteam/orthanc:latest-full | 127.0.0.1:8042 (HTTP), 127.0.0.1:4242 (DIMSE) | DICOM 서버 |
| ohif | ohif/app:latest | 127.0.0.1:3001 | 웹 뷰어 (WeRU.B Viewer) |
| backend | custom (Python 3.12) | 127.0.0.1:8001 | FastAPI 애플리케이션 서버 |
| celery-worker | custom (Python 3.12) | - | AI 추론 워커 |
| celery-beat | custom (Python 3.12) | - | 주기적 작업 스케줄러 |
| celery-flower | mher/flower | 127.0.0.1:5555 | Celery 모니터링 |
| nginx | Host (not container) | 443, 80 | Reverse proxy |
| adminer | adminer:latest | 127.0.0.1:8080 | DB 관리 UI |
| backup | custom build | - | 일일 자동 백업 |
| ai-worker | custom build | - | AI 추론 전용 워커 |
| ai-server | WeRU.B AI v2.50 | - | AI 모델 29개 (의료 13종, 범용 16종) |

### 2.2 네트워크 토폴로지

```
[인터넷]
    │
[Nginx :443 (TLS 1.3)]
    │
    ├── /viewer/     → ohif:3001 (WeRU.B Viewer)
    ├── /pacs-api/   → backend:8001 (FastAPI)
    ├── /dicom-web/  → orthanc:8042 (DICOMweb + Basic Auth, ★토큰 게이트 auth_request)
    ├── /wado        → orthanc:8042 (WADO-URI, ★토큰 게이트)
    └── /pacs/       → orthanc:8042 (Orthanc Explorer)

[내부 네트워크 (Docker Bridge)]
    backend ←→ orthanc (HTTP :8042)
    backend ←→ postgres (TCP :5432)
    backend ←→ redis (TCP :6379)
    orthanc ←→ postgres (Orthanc Index Plugin)
    hl7-listener :2575 (MWL HL7 ORM 수신 — ufw 도커서브넷만, 외부 DROP)  ← LIS 연계
```

### 2.3 볼륨 구성

| 볼륨 | 마운트 위치 | 용도 |
|------|-------------|------|
| orthanc-data | /var/lib/orthanc/db | DICOM 파일 저장소 |
| postgres-data | /var/lib/postgresql/data | 데이터베이스 파일 |
| redis-data | /data | Redis 영속성 (AOF) |

## 3. 데이터 흐름

### 3.1 DICOM 영상 수신 (C-STORE)

```
[모달리티/PACS] → DIMSE C-STORE (:4242) → [Orthanc]
    → Orthanc PostgreSQL Plugin (인덱싱)
    → Orthanc Lua/Python Plugin (자동 라우팅)
    → [Backend] Webhook 수신
        → DICOM Validation 수행
        → Normalization 필요 시 배치 등록
        → Worklist 자동 생성
```

### 3.2 웹 뷰어 영상 조회 (DICOMweb) — 토큰 게이트 (v13.19)

```
[WeRU.B Viewer (브라우저)]
    UserAuthenticationService → 요청에 Authorization: Bearer <pacs_token> 주입
    → QIDO-RS (Study 검색) → Nginx /dicom-web
    → WADO-RS (영상 프레임)  → Nginx /dicom-web
         └ Nginx: satisfy any (내부 IP 바이패스)
              └ auth_request → Backend GET /dicomweb/_authcheck (경량 JWT 검증, auth 캐시 60s)
                   ├ 200 → Orthanc (Basic 주입) → 프레임
                   └ 401 → 차단 (무인증/refresh/RESEARCHER)
    → 뷰어 렌더링 (Cornerstone3D / 병리 SM은 microscopy 모드)
```

- 무인증 `/dicom-web` edge PHI 노출을 토큰 게이트로 차단. IP allowlist 불가(임상 egress 부재)라
  토큰 방식 채택 — 컷오버 시 클리닉 네트워크 무관하게 동작.
- 인증 표준 QIDO-RS는 `/api/v1/dicomweb/rs/*`(외부 연동용 태그키 응답). `StudyReadRoles`로
  RESEARCHER의 PHI 열거 차단.

### 3.2b LIS(병리) 연계 흐름 (v13.19~13.20)

```
[LIS 병리 오더]  → HL7 ORM^O01 NW (MLLP) → hl7-listener:2575 → worklist_items(SCHEDULED) → Orthanc MWL C-FIND
[LIS 오더 취소]  → HL7 ORM ORC-1=CA       → hl7-listener       → worklist_items(CANCELLED, 감사보존)  (v13.20)
[LIS 판독화면]   → QIDO-RS (svc-lis JWT, AccessionNumber) → /api/v1/dicomweb/rs/studies → Study UID
               → 뷰어 런처 /api/v1/viewer/launch?AccessionNumber= → 302 → 뷰어(SM은 microscopy)
```

### 3.2c 병리 WSI 주석 흐름 (DICOM Sup 222, v13.20)

```
[producer]
  ├ 계산병리 AI      → coordinate_type=2D (total pixel matrix 픽셀좌표)
  └ 병리의 수기 마킹  → microscopy 뷰어 드로잉 → "DICOM 주석 저장(ANN)" → coordinate_type=3D (슬라이드 mm, v13.22)
    → POST /api/v1/pathology/{study_uid}/annotations {coordinate_type, groups:[geometry]}   [병리 write RBAC]
    → highdicom: Microscopy Bulk Simple Annotations (SOPClass …91.1, Modality ANN
        · 3D는 FrameOfReferenceUID + coplanar 최적화 CommonZCoordinateValue · POLYGON 닫힘점 제거)
    → Orthanc 저장 (WSI SM study에 ANN 시리즈 추가)
[뷰어] microscopy 모드 → DicomMicroscopyANN 핸들러 → WSI 열 때 ANN 오버레이 자동 로드(v13.21)
       create·SCOORD3D·디스플레이셋 인식·loadAnnotation 종단 실행 완료 / 최종 화면 렌더·드로잉은 실 WSI 게이트
```

### 3.3 AI 추론 흐름

```
[사용자] → POST /api/v1/ai/inference → [Backend]
    → Celery Task 생성 → [Redis Broker]
    → [Celery Worker] 추론 수행
        → Orthanc에서 DICOM 다운로드
        → ONNX Runtime 또는 외부 API 호출
        → 결과 DICOM (SR/SC/SEG) 생성
        → Orthanc에 결과 저장
    → WebSocket 알림 → [사용자]
```

### 3.4 인증/감사 흐름

```
[사용자] → POST /auth/login → [Backend]
    → bcrypt 비밀번호 검증
    → JWT 발급 (Access + Refresh)
    → Redis 세션 등록
    → Audit Log 기록

[모든 API 호출]
    → AuthMiddleware: JWT 검증
    → RBAC 권한 확인
    → AuditMiddleware: 감사 로그 비동기 기록
```

## 4. Orthanc 설정 아키텍처

### 4.1 플러그인 구성
| 플러그인 | 용도 |
|----------|------|
| PostgreSQL Index | 대용량 인덱싱 성능 확보 |
| DICOMweb | WADO-RS, STOW-RS, QIDO-RS 지원 |
| GDCM | JPEG2000 등 압축 형식 디코딩 |
| Python | 자동 라우팅, Webhook 트리거 |

### 4.2 DICOM AE 설정
- AE Title: OPENPACS
- DICOM Port: 4242
- 허용 원격 모달리티: 설정 파일 기반 관리

## 5. 확장성 고려사항

| 항목 | 현재 | 확장 계획 |
|------|------|-----------|
| 저장소 | 단일 디스크 | 객체 스토리지 (S3 호환) |
| DB | 단일 PostgreSQL | Read Replica |
| Worker | 단일 Celery | 멀티 Worker (GPU/CPU 분리) |
| 뷰어 | 단일 인스턴스 | CDN 배포 |

## 6. 장애 대응

| 장애 시나리오 | 대응 |
|---------------|------|
| Orthanc 다운 | Docker restart policy: unless-stopped |
| DB 연결 실패 | SQLAlchemy 재연결 풀, 헬스체크 |
| Redis 다운 | 캐시 미스 시 DB 직접 조회 |
| 디스크 부족 | 모니터링 알림 (90% threshold) |

## 7. 참조 문서

- TD-001 요구사항 명세서
- TD-002 설계 명세서
- CS-001 사이버보안 계획서
- RM-001 위험관리 계획서
