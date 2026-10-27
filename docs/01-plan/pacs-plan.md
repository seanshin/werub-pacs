# PACS 서버 및 웹 뷰어 기획서

> **프로젝트명**: OpenPACS  
> **작성일**: 2026-05-09  
> **프로젝트 레벨**: Dynamic (병원/클리닉 실무용)  
> **기술 스택**: 웹 기반 (Next.js 15 + Python 백엔드 + Cornerstone3D)  
> **총 개발 기간**: 30주 (Phase 1~8)

---

## 1. 프로젝트 개요

### 1.1 배경

PACS(Picture Archiving and Communication System)는 의료 영상(CT, MRI, X-ray 등)의 저장, 전송, 조회를 위한 핵심 의료 정보 시스템이다. 기존 상용 PACS는 높은 라이선스 비용과 폐쇄적 아키텍처로 인해 중소 병원/클리닉에서 도입이 어려운 실정이다.

본 프로젝트는 **오픈소스 기반의 웹 PACS 시스템**을 구축하여, 브라우저만으로 의료 영상을 조회하고 관리할 수 있는 솔루션을 개발한다.

### 1.2 목표

| 목표 | 설명 |
|------|------|
| **DICOM 서버** | DICOM 표준 준수 영상 수신/저장/검색/전송 서버 구축 |
| **웹 뷰어** | 브라우저 기반 Zero-footprint 의료 영상 뷰어 개발 |
| **DICOMweb API** | REST 기반 DICOMweb(QIDO/WADO/STOW-RS) 지원 |
| **의료 AI 연동** | AI 모델 실행/결과 시각화/판독 워크플로우 통합 |
| **비표준 DICOM 대응** | 비표준 영상 자동 감지/정규화, JPEG 밀도 조작 검출 |
| **실무 적용** | 병원/클리닉에서 실제 사용 가능한 수준의 안정성과 보안 |

### 1.3 범위 (Scope)

**In Scope**
- 단일 기관(병원/클리닉) 운영 환경 (v1.0 기준)
- 웹 브라우저 기반 뷰어 (데스크톱 + 모바일 반응형)
- 2D 뷰잉, MPR, MIP, **3D VRT(Volume Rendering)** — Cornerstone3D 기본 제공, Layout 버튼 접근 (검토: `docs/03-analysis/3d-pacs-capability-review.md`)
- 자체 DICOM 서버 + DICOMweb
- AI 모델 연동 프레임워크

**Out of Scope (v1.0)**
- 다중 기관(그룹 병원) 멀티테넌시 — v2.0에서 고려
- 3D VRT **임상 튜닝** — 엔진 능력은 보유(가용), 한국형 VR 프리셋·전용 Hanging Protocol·임상 검증은 v2.0 (※ 2026-06-06 정정: 기존 "VRT 미지원"은 부정확 — 엔진엔 존재)
- IHE SWF 전체 트랜잭션 구현 — 핵심 트랜잭션만 우선 구현
- 음성 인식(Dictation) 연동 — 외부 API 연동 인터페이스만 제공
- 네이티브 모바일 앱 — 반응형 웹으로 대체

### 1.4 대상 사용자

- **영상의학과 전문의**: 영상 판독, Window/Level 조정, 측정, 주석, 리포트 작성
- **임상의**: 외래/병동에서 영상 조회, AI 분석 결과 확인
- **영상의학과 기사**: 영상 업로드, 워크리스트 관리, QC(영상 품질 검수, Study 병합/분리)
- **IT 관리자**: 시스템 설정, 사용자 관리, 모니터링, AI 모델 관리
- **연구자**: 익명화된 영상 데이터 내보내기, AI 모델 학습 데이터 준비

### 1.5 적용 법규 및 규정

| 법규/규정 | 적용 범위 |
|-----------|----------|
| **개인정보보호법** (한국) | 환자 개인정보 처리, 동의, 파기, 안전성 확보 조치 |
| **의료법** (한국) | 의료 영상 보존 기간(5년), 전자의무기록 관리 기준 |
| **HIPAA** (미국, 참조) | PHI 보호 기준 — 국제 수준의 보안 설계 참조 |
| **IHE 프로파일** | Radiology 도메인 통합 프로파일 준수 (SWF, PIR, AIW/AIR) |
| **SaMD 규제** | 본 PACS 자체는 일반 의료 소프트웨어, AI 모듈은 SaMD 해당 가능 — 인허가 범위 분리 설계 |

---

## 2. DICOM 표준 개요

### 2.1 데이터 모델 (4단계 계층)

```
Patient (환자)
  └── Study (검사) — Study Instance UID
        └── Series (시리즈) — Series Instance UID
              └── Instance (인스턴스/이미지) — SOP Instance UID
```

### 2.2 핵심 DIMSE 서비스

| 서비스 | 역할 | 본 시스템 지원 |
|--------|------|---------------|
| C-ECHO | 연결 테스트 | O |
| C-STORE | 영상 저장 (모달리티 → PACS) | O |
| C-FIND | 영상 검색 (Patient/Study/Series/Instance) | O |
| C-MOVE | 영상 전송 (PACS → 워크스테이션) | O |
| C-GET | 영상 가져오기 | O |
| N-CREATE / N-SET | MPPS (검사 수행 절차 단계) | O |

### 2.3 DICOMweb REST 서비스

| 서비스 | HTTP 메서드 | 역할 |
|--------|-----------|------|
| QIDO-RS | GET | 검색 — 메타데이터 기반 Study/Series/Instance 검색 |
| WADO-RS | GET | 조회 — 영상 데이터 및 메타데이터 스트리밍 |
| WADO-URI | GET | 단일 객체 조회 (레거시 호환, JPEG/PNG 렌더링 응답 지원) |
| STOW-RS | POST | 저장 — HTTP POST로 DICOM 인스턴스 업로드 |

### 2.4 지원 Transfer Syntax

| Transfer Syntax | 우선순위 | 비고 |
|----------------|---------|------|
| Explicit VR Little Endian | 필수 | 기본 전송 구문 |
| Implicit VR Little Endian | 필수 | DICOM 기본값 |
| JPEG Lossless | 높음 | 무손실 압축 |
| JPEG 2000 (Lossless/Lossy) | 높음 | 고압축 |
| HTJ2K | 높음 | 웹 최적화, 프로그레시브 로딩 지원 |
| JPEG Baseline | 보통 | 8bit 손실 압축 |
| JPEG-LS | 보통 | 효율적 무손실 |

---

## 3. 시스템 아키텍처

### 3.1 전체 아키텍처

```
┌──────────────────────────────────────────────────────────────────────┐
│                          클라이언트 계층                               │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  ┌───────────┐  │
│  │  OHIF Viewer  │  │ Admin Portal │  │ 리포트 편집기│  │ 모바일 웹  │  │
│  │(Cornerstone3D)│  │  (Next.js)   │  │  (Next.js) │  │  (반응형)  │  │
│  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘  └─────┬─────┘  │
└─────────┼─────────────────┼────────────────┼────────────────┼────────┘
          │                 │                │                │
          ▼                 ▼                ▼                ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     API Gateway / Reverse Proxy                      │
│                          (Nginx)                                     │
│      TLS 종단 · OAuth2 인증 · CORS · 로드밸런싱 · Rate Limit          │
│      WebSocket 프록시 지원 (영상 수신 알림, AI 진행 상태)               │
└───────┬──────────────┬──────────────┬──────────────┬─────────────────┘
        │              │              │              │
        ▼              ▼              ▼              ▼
┌──────────────┐ ┌───────────┐ ┌───────────┐ ┌────────────────────────┐
│ DICOM 서버    │ │  웹 API   │ │  인증서버  │ │    AI Worker 계층       │
│  (Orthanc)   │ │ (FastAPI) │ │(Keycloak) │ │                        │
│              │ │           │ │           │ │ ┌──────────────────┐   │
│ ┌──────────┐ │ │· 판독리포트│ │· OAuth2   │ │ │  AI Orchestrator │   │
│ │  DIMSE   │ │ │· 워크리스트│ │· RBAC     │ │ │  (FastAPI)       │   │
│ │ C-STORE  │ │ │· 감사로그  │ │· OIDC     │ │ └────────┬─────────┘   │
│ │ C-FIND   │ │ │· 익명화   │ │· SSO      │ │          │             │
│ │ C-MOVE   │ │ │· 내보내기  │ └───────────┘ │ ┌────────▼─────────┐   │
│ │ C-ECHO   │ │ │· AI관리   │               │ │  Celery Workers  │   │
│ │ MPPS     │ │ │· QC관리   │               │ │  (전처리/추론/   │   │
│ └──────────┘ │ │· 보존정책  │               │ │   후처리)        │   │
│ ┌──────────┐ │ │· 마이그레  │               │ └────────┬─────────┘   │
│ │ DICOMweb │ │ │  이션     │               │          │             │
│ │ QIDO-RS  │ │ └─────┬─────┘               │ ┌────────▼─────────┐   │
│ │ WADO-RS  │ │       │                     │ │ 추론 엔진         │   │
│ │ WADO-URI │ │       │                     │ │ · ONNX Runtime   │   │
│ │ STOW-RS  │ │       │                     │ │ · Triton Server  │   │
│ └──────────┘ │       │                     │ │ · 외부 API 호출   │   │
│ ┌──────────┐ │       │                     │ └──────────────────┘   │
│ │ Plugins  │ │       │                     └────────────────────────┘
│ │·PostgreSQL│ │       │
│ │·Auth     │ │       │
│ │·Python   │ │       │
│ │·DICOM검증│ │       │
│ └──────────┘ │       │
└──────┬───────┘       │
       │               │
       ▼               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        데이터 계층                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────┐  │
│  │  PostgreSQL   │  │ DICOM Storage│  │    Redis     │  │  MinIO  │  │
│  │  (Primary +   │  │              │  │  (Sentinel)  │  │  (S3)   │  │
│  │   Replica)   │  │· 로컬 파일    │  │              │  │         │  │
│  │· DICOM 인덱스 │  │  시스템      │  │· AI 작업 큐   │  │· 백업   │  │
│  │· 사용자 DB    │  │· S3 확장     │  │· 세션 캐시    │  │· 아카이브│  │
│  │· 리포트       │  │· 무결성 체크섬│  │· AI 결과 캐시 │  │· Cold   │  │
│  │· 감사 로그    │  │              │  │              │  │  Storage│  │
│  │· AI 메타데이터│  │              │  │              │  │         │  │
│  │· 검증 이력    │  │              │  │              │  │         │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └─────────┘  │
└──────────────────────────────────────────────────────────────────────┘
       ▲                                                    ▲
       │                                                    │
┌──────┴──────────────────┐  ┌──────────────────────────────┴──────────┐
│ 외부 연동 계층            │  │ 운영 모니터링 계층                        │
│                         │  │                                         │
│ · HL7 v2 어댑터          │  │ · Prometheus (메트릭 수집)               │
│   (Mirth Connect 등)    │  │ · Grafana (대시보드/알림)                │
│ · FHIR 어댑터 (향후)     │  │ · Loki (로그 수집) 또는 PostgreSQL 직접  │
│   (점선 — v2.0)         │  │ · AlertManager (장애 알림)               │
│ · SMTP (이메일 알림)     │  │   → 이메일, SMS, 메신저 연동             │
│ · SMS Gateway           │  │                                         │
│ · 메신저 Webhook         │  │                                         │
└─────────────────────────┘  └─────────────────────────────────────────┘
       ▲
       │
┌──────────────────────────────────────────────────────────────────────┐
│                    모달리티 장비 (CT, MRI, CR, US 등)                   │
│                    DICOM C-STORE SCU → Orthanc SCP                   │
│                    MPPS N-CREATE → Orthanc SCP                       │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 기술 스택

| 계층 | 기술 | 선택 이유 |
|------|------|----------|
| **DICOM 서버** | Orthanc | 경량, REST API 내장, 플러그인 확장, GPLv3 |
| **DICOMweb** | Orthanc DICOMweb 플러그인 | QIDO/WADO/STOW-RS 표준 준수 |
| **웹 뷰어** | OHIF Viewer v3 (버전 고정) | Cornerstone3D 기반, 즉시 사용 가능, Extension 시스템 |
| **렌더링 엔진** | Cornerstone3D | WebGL GPU 가속, 멀티스레드 디코딩, 프로그레시브 로딩 |
| **웹 프론트엔드** | Next.js 15 (App Router) | Admin Portal, 리포트 편집기, SSR/SSG 지원 |
| **백엔드 API** | FastAPI (Python) | 비동기 처리, DICOM 라이브러리 풍부, 타입 안전 |
| **DICOM 라이브러리** | pydicom + pynetdicom | 파일 처리 + 네트워킹 |
| **데이터베이스** | PostgreSQL 16 (Primary + Replica) | Orthanc 인덱싱 + 애플리케이션 데이터, Streaming Replication |
| **인증** | Keycloak | OAuth2/OIDC, RBAC, SSO |
| **컨테이너** | Docker Compose | 개발/배포 일관성 |
| **리버스 프록시** | Nginx | TLS 종단, 로드밸런싱, WebSocket 프록시 |
| **AI 추론 서빙** | ONNX Runtime / Triton | 범용 모델 서빙, GPU/CPU 가속 |
| **AI 전처리** | pydicom + NumPy + nibabel | DICOM→텐서 변환, 정규화 |
| **작업 큐** | Celery + Redis | AI 추론 비동기 큐, 우선순위 관리 |
| **AI 결과 저장** | highdicom | DICOM SEG/SR/SC/ANN 생성 |
| **캐시/브로커** | Redis (Sentinel 구성) | 세션, AI 결과 캐시, Celery 브로커 |
| **오브젝트 스토리지** | MinIO (S3 호환) | 백업, 아카이브, Cold Storage |
| **모니터링** | Prometheus + Grafana | 메트릭 수집, 대시보드, 장애 알림 |
| **로그 수집** | Loki + Grafana | 감사 로그/시스템 로그 수집 및 검색 |
| **HL7 연동** | Mirth Connect (향후) | HL7 v2 메시지 수신/변환/전달 |

### 3.3 고가용성(HA) 구성

| 구성 요소 | HA 방안 | 비고 |
|-----------|--------|------|
| PostgreSQL | Streaming Replication (Primary + Replica) | 자동 페일오버 (Patroni 또는 repmgr) |
| Redis | Redis Sentinel (최소 3노드) | 자동 마스터 선출 |
| Orthanc | 다중 인스턴스 + PostgreSQL 공유 인덱스 | Nginx 라운드 로빈 로드밸런싱 |
| Nginx | Active-Passive (keepalived) | VIP 기반 페일오버 |
| DICOM Storage | 로컬 파일시스템 + MinIO 동기화 | rsync 또는 S3 sync 기반 복제 |

### 3.4 백업/복구 아키텍처

| 대상 | 백업 방법 | 주기 | 복구 절차 |
|------|----------|------|----------|
| PostgreSQL | pg_dump + WAL 아카이빙 | 일 1회 풀 백업 + 실시간 WAL | pg_restore + WAL replay |
| DICOM Storage | rsync → MinIO (S3) | 일 1회 증분 동기화 | MinIO에서 복원 |
| Keycloak DB | pg_dump (별도) | 일 1회 | pg_restore |
| Redis | RDB 스냅샷 | 6시간마다 | RDB 파일 복원 |
| 설정 파일 | Git 버전 관리 | 변경 시 | Git checkout |

### 3.5 데이터 암호화 레이어

| 계층 | 방식 | 적용 |
|------|------|------|
| 전송 중 (In Transit) | TLS 1.3 | 모든 HTTP/DICOM 통신 |
| 저장 중 (At Rest) — DB | PostgreSQL pgcrypto (컬럼 레벨) | PHI 포함 컬럼 (환자명, ID 등) |
| 저장 중 (At Rest) — 파일 | 볼륨 암호화 (LUKS/dm-crypt) | DICOM Storage 파티션 |
| 저장 중 (At Rest) — 백업 | AES-256 암호화 | MinIO 서버 사이드 암호화 (SSE-S3) |

---

## 4. 핵심 기능 명세

### 4.1 PACS 서버 기능

#### 4.1.1 영상 수신 (C-STORE SCP)
- 모달리티(CT, MRI, CR, US 등)로부터 DICOM 영상 수신
- 수신 시 자동 인덱싱 및 메타데이터 추출
- AE Title 기반 접근 제어
- 수신 알림 (WebSocket 실시간 통보)
- 한글 환자명(PN VR) 정상 처리 — Specific Character Set `ISO 2022 IR 149` (EUC-KR) 및 `ISO_IR 192` (UTF-8) 지원
- 영상 무결성 체크섬(SHA-256) 생성 및 저장

#### 4.1.2 영상 검색 (C-FIND SCP / QIDO-RS)
- Patient / Study / Series / Instance 레벨 검색
- 복합 조건 검색 (환자명, ID, 검사일, 모달리티 등)
- 와일드카드 검색 지원
- 한글 환자명 검색 (초성 검색 포함)
- 페이지네이션 (DICOMweb limit/offset)

#### 4.1.3 영상 전송 (C-MOVE SCP / WADO-RS / WADO-URI)
- 외부 DICOM 노드로 영상 전송 (C-MOVE)
- DICOMweb을 통한 웹 클라이언트 영상 조회 (WADO-RS)
- 멀티파트 응답을 통한 대용량 스트리밍
- WADO-URI 레거시 호환 (JPEG/PNG 렌더링 응답 포함)

#### 4.1.4 영상 업로드 (STOW-RS)
- 웹 인터페이스를 통한 DICOM 파일 업로드
- CD/DVD에서 가져오기 (DICOMDIR 파싱, 진행률 표시, 중복 검사 감지)
- 드래그 앤 드롭 대량 업로드
- 파일 유효성 검증 (4.1.6 검증 엔진 연계)

#### 4.1.5 영상 라우팅
- 수신 영상 자동 라우팅 규칙 (모달리티, AE Title, Body Part 기반)
- 원격 PACS로 자동 전달
- AI 모델 자동 트리거 (4.3 AI 워크플로우 연계)

#### 4.1.6 비표준 DICOM 검증 및 정규화 (DICOM Conformance Validation)

실무에서는 DICOM 표준을 완벽히 준수하지 않는 영상 데이터가 빈번하게 유입된다. 벤더별 구현 차이, 레거시 장비, 수동 변환 파일 등에서 발생하는 비표준 데이터를 수신 시점에 자동 감지하고 대응해야 한다.

> **구현 주의**: Orthanc Python 플러그인의 GIL 제약으로 대량 수신 시 병목이 발생할 수 있으므로, 검증 엔진은 외부 FastAPI 서비스로 분리하여 비동기 호출 방식으로 구현한다. Orthanc의 `OnStoredInstance` 콜백에서 경량 검증만 수행하고, 상세 검증은 외부 서비스에 위임한다.

**A. 메타데이터 검증**
- **필수 태그 누락 감지**: Patient ID, Study/Series/SOP Instance UID, Modality 등 Type 1/1C 태그 누락 검출
- **태그 값 형식 오류**: VR(Value Representation) 불일치 검출 — 예: DA(Date)에 잘못된 날짜 형식, IS(Integer String)에 비정수 값
- **UID 형식 검증**: UID가 64자 초과, 비허용 문자 포함, 루트 UID 없음 등
- **문자셋 오류**: Specific Character Set(0008,0005) 미지정 시 한글/일본어 등 비ASCII 문자 깨짐 감지
- **중복 태그 감지**: 동일 태그가 복수 존재하는 비표준 상황 검출
- **Private 태그 분석**: 벤더별 Private 태그 식별 및 로깅 (삭제하지 않고 보존)

**B. 픽셀 데이터 및 Transfer Syntax 검증**
- **Transfer Syntax 불일치**: 헤더에 선언된 Transfer Syntax와 실제 픽셀 데이터 인코딩 불일치 검출
- **Bits Allocated/Stored 불일치**: 선언된 비트 심도와 실제 픽셀 범위 불일치 감지
- **Photometric Interpretation 오류**: MONOCHROME1/2, RGB, YBR_FULL 등 잘못된 선언 검출
- **Pixel Padding 누락/오류**: Pixel Padding Value 태그와 실제 패딩 불일치
- **Encapsulated 픽셀 데이터 오류**: Fragment 구조 손상, BOT(Basic Offset Table) 누락/불일치

**C. JPEG 관련 비표준 처리 (빈번 발생)**
- **JPEG 밀도(DPI/DPM) 조작 감지**: 일부 장비/소프트웨어에서 JPEG 압축 시 밀도(density) 값을 임의 변경하는 경우 감지
  - JFIF 헤더의 Xdensity/Ydensity 값과 DICOM Pixel Spacing 태그 간 불일치 검출
  - density_unit (0=무단위, 1=DPI, 2=DPM) 잘못된 설정 감지
  - 비정상적 밀도 값으로 인한 실측정 오류 사전 경고
- **JPEG 마커 구조 이상**: SOI/EOI 누락, 잘못된 마커 순서, 불완전한 허프만 테이블
- **색공간 불일치**: JPEG 색공간(YCbCr/RGB)과 DICOM Photometric Interpretation 불일치
- **JPEG Lossy 재압축 감지**: 이미 손실 압축된 데이터가 재압축된 경우(세대 손실) 경고
- **ICC 프로필 충돌**: JPEG 내장 ICC 프로필과 DICOM 색 관리 설정 간 불일치

**D. 검증 결과 처리 정책**

| 심각도 | 정의 | 처리 |
|--------|------|------|
| **Critical** | 영상 표시 불가 또는 환자 식별 불가 | 수신 거부 + 즉시 알림 |
| **Error** | 표준 위반이나 영상 표시는 가능 | 수신 허용 + 경고 플래그 + 관리자 알림 |
| **Warning** | 경미한 표준 위반 | 수신 허용 + 검증 로그 기록 |
| **Info** | 참고 사항 (Private 태그 등) | 로그 기록만 |

**E. 자동 정규화 (선택적 적용)**
- 누락된 필수 태그 기본값 자동 삽입 (관리자 설정에 따라)
- Transfer Syntax 불일치 시 자동 트랜스코딩
- 문자셋 자동 감지 및 Specific Character Set 태그 보정
- JPEG 밀도 값 정규화 — DICOM Pixel Spacing 기준으로 재설정
- 정규화 전 원본 보존 (원본/정규화 이중 저장 옵션)

**F. 검증 대시보드**
- 비표준 DICOM 발생 현황 통계 (장비별, 모달리티별, 유형별)
- 반복 발생하는 비표준 패턴 자동 탐지 및 알림
- 특정 장비/AE Title에서 빈번히 발생하는 문제 패턴 리포트
- 검증 이력 검색 및 필터링

#### 4.1.7 데이터 보존 및 생명주기 관리

- **보존 정책**: 의료법 기준 최소 5년 보존 (영상 종류별 차등 설정 가능)
- **자동 아카이빙**: 보존 기간 경과 시 Cold Storage(MinIO)로 자동 이관
- **삭제 정책**: 보존 기간 만료 후 관리자 승인 하에 삭제 (자동 삭제 금지)
- **삭제 감사**: 삭제된 영상의 메타데이터(환자ID, Study UID, 삭제일, 삭제자) 영구 보존
- **저장 용량 관리**: Prometheus 기반 스토리지 사용률 모니터링, Grafana 알림 (80%, 90% 임계치)
- **영상 무결성 정기 검증**: 저장된 DICOM 파일의 SHA-256 체크섬을 정기적으로 검증하여 bit rot 감지 (주 1회 배치)

#### 4.1.8 데이터 익명화/비식별화

- **연구용 내보내기**: 환자 식별 정보(이름, ID, 생년월일 등) 제거/대체 후 내보내기
- **DICOM Supplement 142 준수**: 기본 프로파일(Basic Application Level Confidentiality Profile) 적용
- **태그별 처리 규칙**: 제거(Remove), 대체(Replace), 해싱(Hash), 유지(Keep) 설정 가능
- **일관된 익명화**: 동일 환자의 다중 Study를 동일 가명 ID로 연결 유지
- **Burned-in Annotation 경고**: 영상 픽셀에 환자 정보가 포함된 경우 경고 (US, SC 등)
- **AI 학습 데이터 파이프라인**: 익명화 + 포맷 변환(NIfTI/PNG) + 메타데이터 CSV 일괄 내보내기

#### 4.1.9 영상 내보내기

- **DICOM 내보내기**: 선택한 Study/Series를 DICOM 파일로 다운로드 (ZIP)
- **CD/USB 패키징**: DICOMDIR 포함 미디어 구조 생성, 내장 뷰어 포함 옵션
- **비DICOM 포맷 변환**: JPEG, PNG, TIFF 내보내기 (W/L 적용 상태)
- **DICOM Print**: 필름 프린터 연동 (DICOM Print SCU) — 선택적 구현 (Backlog)
- **외부 PACS 전송**: C-STORE SCU로 지정 노드에 전송

#### 4.1.10 MPPS (Modality Performed Procedure Step)
- 모달리티에서 검사 시작(N-CREATE) 및 완료/중단(N-SET) 통보 수신
- 워크리스트 검사 상태 자동 갱신 (예약 → 진행중 → 완료)
- MPPS 기반 영상 수신 완료 확인

#### 4.1.11 Prefetch (사전 로딩)
- 외래 예약 환자의 이전 영상을 원격 PACS에서 사전에 가져오기 (C-MOVE SCU)
- 예약 목록 기반 자동 Prefetch 스케줄링
- Prefetch 상태 모니터링 (성공/실패/진행률)

### 4.2 웹 뷰어 기능

#### 4.2.1 기본 영상 조회
- 2D 영상 표시 (CT, MRI, CR, DX, US 등)
- Window/Level(밝기/대비) 조정 — 프리셋 및 수동
- 줌, 팬, 회전, 좌우반전
- 시리즈 스크롤 (마우스 휠)
- 레이아웃 설정 (1x1, 1x2, 2x2, 3x3 등)
- 한글 환자 정보 정상 표시
- 다중 모니터 레이아웃 지원 (브라우저 창 분리 후 동기화)

#### 4.2.2 측정 및 주석
- 길이 측정 (mm)
- 각도 측정
- 면적/타원 측정
- ROI (Region of Interest) 통계 (평균, 표준편차)
- 텍스트 주석
- 화살표 마커
- 측정값 DICOM SR(Structured Report)로 저장

#### 4.2.3 고급 기능
- MPR (Multi-Planar Reconstruction) — 축상/관상/시상면
- MIP (Maximum Intensity Projection)
- 이전 검사와 비교 (Prior Study Comparison)
  - 매칭 로직: 동일 환자 ID + 동일 모달리티 + 동일/유사 Body Part + 날짜순 정렬
  - 비교 동기화: 좌우 패널 슬라이스 위치 동기화, W/L 동기화 (개별 해제 가능)
- 행잉 프로토콜 (Hanging Protocol)
  - 모달리티/Body Part별 자동 레이아웃 규칙 적용
  - JSON 설정 파일 기반 규칙 정의, Admin Portal에서 관리
- CINE 모드 (동영상 재생 — 심장 초음파, MR Cine 등)
- 키 이미지 (Key Image Note) 마킹
- 응급 플래그: 기사/임상의가 수동으로 긴급 표시 설정

#### 4.2.4 비표준 DICOM 대응 (뷰어)
- **비표준 플래그 표시**: 서버에서 검증된 비표준 항목을 뷰어 UI에 경고 아이콘/배너로 표시
- **JPEG 밀도 보정 뷰**: 밀도 값이 조작된 영상의 원본/보정 비교 표시
- **Pixel Spacing 신뢰도 표시**: 측정 도구 사용 시 Pixel Spacing 출처(DICOM 태그 vs JPEG 헤더) 및 신뢰도 표시
- **Window/Level 폴백**: Rescale Slope/Intercept, Window Center/Width 누락 시 자동 계산 폴백
- **비표준 Photometric 자동 보정**: MONOCHROME1/2 잘못 선언된 경우 반전 표시 보정
- **Transfer Syntax 폴백 디코딩**: 선언된 TS 디코딩 실패 시 자동 감지하여 대체 디코더 시도

#### 4.2.5 모바일 웹 뷰어
- 반응형 레이아웃 (태블릿/모바일 대응)
- 터치 제스처: 핀치 줌, 스와이프 스크롤, 2손가락 팬, 길게 누르기 W/L
- 모바일 제한 기능: MPR, MIP, CINE는 데스크톱 전용 (모바일에서 비활성)
- 기본 뷰잉(2D, W/L, 줌, 스크롤) 및 리포트 조회는 모바일 완전 지원

#### 4.2.6 성능 최적화
- 프로그레시브 로딩 (HTJ2K 기반 저해상도 → 고해상도)
- 프리페칭 (다음 시리즈 미리 로드)
- 웹 워커 기반 멀티스레드 디코딩
- GPU 가속 렌더링 (WebGL)
- 대용량 CT (500MB+) 스트리밍 로딩

### 4.3 의료 AI 연동 기능

병원/클리닉에서 도입이 확대되고 있는 의료 영상 AI(CAD, AI 진단 보조)를 PACS와 유기적으로 연동하기 위한 기능이다. DICOM 표준의 AI 결과 저장 방식과 IHE AI Workflow(AIW/AIR) 프로파일을 기반으로 설계한다.

#### 4.3.1 AI 워크플로우 엔진

**A. AI 모델 실행 파이프라인**
- **자동 트리거**: 영상 수신(C-STORE) 시 모달리티/검사 부위/SOP Class 기반으로 해당 AI 모델 자동 실행
  - 예: Chest X-ray 수신 → 폐결절 탐지 AI 자동 실행
  - 예: 유방촬영 수신 → 유방암 스크리닝 AI 자동 실행
  - 예: 뇌 CT 수신 → 뇌출혈 감지 AI 자동 실행 (긴급 알림 포함)
- **수동 실행**: 뷰어에서 특정 Study/Series 선택 후 원하는 AI 모델 수동 실행
- **트리거 규칙 관리**: 관리자가 모달리티, Body Part, AE Title 조건별 AI 실행 규칙 설정

**B. AI 모델 관리**
- AI 모델 등록/수정/삭제/버전 관리 (Admin Portal UI 포함)
- 모델별 입력 요구사항 정의 (모달리티, Transfer Syntax, 최소 슬라이스 수 등)
- 모델 활성화/비활성화 토글
- 모델별 실행 통계 (처리 시간, 성공률, 오류율)
- GPU/CPU 리소스 할당 설정
- **임상용/연구용 구분**: 의료기기 인증 모델(임상)과 미인증 모델(연구) 분리 표시

**C. AI 실행 큐 및 상태 관리**
- 비동기 작업 큐 (Celery + Redis)
- 작업 상태 추적: 대기 → 전처리 → 추론 → 후처리 → 완료/실패
- 우선순위 큐: 긴급(Emergency) 검사 우선 처리
- 재시도 정책: 실패 시 자동 재시도 (최대 3회)
- 타임아웃 설정: 모델별 최대 실행 시간 제한

#### 4.3.2 AI 모델 통합 인터페이스

**A. 표준 추론 API**
```
POST /api/v1/ai/inference
{
  "model_id": "lung-nodule-detector-v2",
  "study_uid": "1.2.840...",
  "series_uid": "1.2.840...",
  "parameters": {
    "sensitivity": "high",
    "min_nodule_size_mm": 3
  }
}
```

**B. 지원 모델 인터페이스 유형**

| 유형 | 설명 | 예시 |
|------|------|------|
| **로컬 컨테이너** | Docker 컨테이너로 패키징된 AI 모델 | 자체 개발 모델, 오픈소스 모델 |
| **MONAI Deploy** | NVIDIA MONAI Deploy App SDK 기반 모델 | MONAI 생태계 모델 |
| **외부 API** | 클라우드 AI 서비스 REST API 호출 | Lunit INSIGHT, Vuno Med 등 |
| **ONNX Runtime** | ONNX 포맷 모델 직접 실행 (GPU/CPU) | 범용 모델 서빙 |
| **Triton Inference Server** | NVIDIA Triton 기반 고성능 모델 서빙 | 대규모 GPU 추론 |

**C. GPU/CPU 실행 전략**

| 환경 | 전략 | 적용 대상 |
|------|------|----------|
| **GPU 서버** | CUDA 기반 고속 추론, 배치 처리 | 대규모 병원, 실시간 요구 |
| **CPU 전용** | ONNX Runtime CPU, OpenVINO 최적화 | 중소 클리닉, GPU 미보유 |
| **클라우드 API** | 외부 AI 서비스 호출 (GPU 불필요) | 인증된 상용 AI 서비스 사용 시 |
| **하이브리드** | 긴급은 로컬 CPU, 비긴급은 클라우드 배치 | 비용 최적화 |

**D. 영상 전처리 파이프라인**
- DICOM → NumPy/NIfTI 변환 (pydicom + nibabel)
- 리사이징, 정규화, 윈도잉 (모델 요구사항에 맞게)
- 비표준 DICOM 자동 보정 후 AI 입력 (4.1.6 검증 엔진 연계)
- Transfer Syntax 트랜스코딩 (압축 해제)
- 3D 볼륨 재구성 (Slice Spacing/Thickness 기반)

#### 4.3.3 AI 결과 저장 (DICOM 표준)

AI 분석 결과를 DICOM 표준 형식으로 저장하여 벤더 종속성 없이 호환성을 보장한다.

| DICOM IOD | 용도 | 예시 |
|-----------|------|------|
| **DICOM SEG** (Segmentation) | 병변/장기 영역 세그멘테이션 마스크 | 폐결절 영역, 종양 경계, 장기 세그멘테이션 |
| **DICOM SR** (Structured Report) | 정량적 분석 결과, 수치 데이터 | 결절 크기/밀도, 골밀도 수치, 심장 기능 지표 |
| **DICOM PR** (Presentation State) | 오버레이, 마킹, 화살표 | 병변 위치 화살표, 관심 영역 마킹 |
| **DICOM SC** (Secondary Capture) | AI 생성 이미지 (히트맵 등) | CAM 히트맵, 확률 맵, 비교 이미지 |
| **DICOM ANN** (Annotation) | 포인트/폴리라인/바운딩박스 | DICOM Supplement 222 기반 좌표 주석 |

- AI 결과를 원본 Study에 새 Series로 저장 → 뷰어에서 원본과 함께 조회
- 결과 DICOM에 AI 모델 정보 기록 (모델명, 버전, 제조사, 알고리즘 식별자)
- 이전 AI 결과 버전 관리 (모델 업데이트 시 재분석 이력)

#### 4.3.4 AI 결과 시각화 (뷰어)

**A. 세그멘테이션 오버레이**
- AI SEG 결과를 원본 영상 위에 반투명 컬러 오버레이로 표시
- 다중 레이블(폐, 간, 종양 등) 각각 다른 색상으로 구분
- 오버레이 투명도 조절 (0~100%)
- 오버레이 ON/OFF 토글
- 3D MPR에서 세그멘테이션 표시 (고해상도 SEG의 WebGL 메모리 한계 고려, 다운샘플링 옵션)

**B. 바운딩 박스 및 마커**
- AI가 검출한 병변 위치에 바운딩 박스 표시
- 병변별 신뢰도(Confidence Score) 표시
- 클릭 시 해당 병변으로 자동 이동/줌
- 병변 목록 패널 (신뢰도 순 정렬)

**C. AI 리포트 패널**
- AI 분석 결과 요약 패널 (뷰어 사이드바)
- 정량적 수치 표시 (크기, 부피, 밀도, HU 값 등)
- 이전 검사 대비 변화량 추적 (Follow-up comparison)
- AI 모델 정보 (모델명, 버전, 인증 상태)
- AI 결과 승인/거부/수정 워크플로우

**D. 히트맵/확률 맵**
- CAM(Class Activation Map) 등 AI 주목 영역 시각화
- 컬러맵 변경 (Jet, Hot, Cool 등)
- 임계값(Threshold) 슬라이더로 표시 범위 조절

**E. 판독 워크플로우 통합**
- AI 결과 기반 자동 행잉 프로토콜 (AI가 이상 소견 발견한 시리즈 우선 표시)
- AI 신뢰도에 따른 검사 우선순위 재배치 (Triage)
- AI 결과를 판독 리포트 초안에 자동 삽입
- 판독의가 AI 결과에 대한 동의/비동의 기록

#### 4.3.5 긴급 알림 (Critical Finding Alert)
- AI가 긴급 소견(뇌출혈, 기흉, 폐색전 등)을 감지하면 즉시 알림
- 알림 채널: 웹 푸시, 이메일(SMTP), SMS(Gateway), 메신저(Webhook)
- 워크리스트 최상단 긴급 표시
- 알림 확인(Acknowledge) 추적 — 미확인 시 에스컬레이션

#### 4.3.6 AI 성능 모니터링 및 품질 관리

**A. 성능 대시보드**
- 모델별 처리량 (일/주/월)
- 평균 추론 시간, P95/P99 지연 시간
- 오류율 및 실패 원인 분류
- GPU/CPU 사용률 모니터링 (Prometheus 메트릭)

**B. 임상 품질 지표**
- AI 결과 vs 판독의 최종 판독 일치율 추적
- False Positive / False Negative 통계
- 모달리티별/검사 부위별 정확도 분석
- 모델 버전별 성능 비교 (A/B 테스트)

**C. 감사 및 규제 준수**
- AI 모델별 의료기기 인증 상태 표시 (FDA 510(k), CE Mark, MFDS 등)
- 모든 AI 추론 요청/결과에 대한 감사 로그
- 모델 입력/출력 데이터 추적 가능성(Traceability)
- AI 판단 근거 기록 (Explainability 지원)
- **임상용 AI 면책 표시**: 뷰어 및 리포트에 "AI 결과는 진단 보조 목적이며, 최종 판단은 의료진의 책임" 고지문 상시 표시

### 4.4 판독 리포트

#### 4.4.1 리포트 작성
- 구조화 리포트 템플릿 (모달리티별/검사 부위별)
- 자유 텍스트 + 구조화 필드 혼합 작성
- AI 분석 결과 자동 삽입 (4.3.4E 연계)
- 키 이미지 첨부 (스냅샷 캡처)
- 이전 리포트 참조/복사
- 음성 인식 연동 인터페이스 (외부 Dictation API 호출 포인트 제공)

**리포트 템플릿 예시 (Chest X-ray)**

| 필드 | 타입 | 필수 | 설명 |
|------|------|:----:|------|
| 임상 정보 | 자유 텍스트 | O | 의뢰 사유, 증상 |
| 비교 검사 | 날짜 선택 | - | 이전 검사 참조 |
| 소견 (Findings) | 구조화 + 자유 텍스트 | O | 부위별 소견 (폐야, 심장, 종격동, 흉막, 뼈) |
| 결론 (Impression) | 자유 텍스트 | O | 진단 결론 |
| 권고 사항 | 자유 텍스트 | - | 추가 검사, 추적 관찰 |
| 긴급도 | 선택 | O | 정상 / 비긴급 이상 / 긴급 |

#### 4.4.2 리포트 워크플로우
- 작성 → 예비 판독(Preliminary) → 최종 판독(Final) → 수정(Addendum)
- 전자 서명 (판독의 인증)
- 리포트 상태 추적 및 알림
- 지정 임상의에게 완료 알림 전송
- **동시 편집 방지**: Study별 편집 잠금 (비관적 잠금) — 이미 다른 판독의가 편집 중이면 읽기 전용으로 표시, 잠금 해제 요청 가능

#### 4.4.3 리포트 저장 및 배포
- DICOM SR(Structured Report)로 저장 — PACS 내 원본 Study에 연결
- PDF 내보내기
- HL7 ORU 메시지로 HIS/EMR 전송 (향후, 외부 연동 계층 경유)
- FHIR DiagnosticReport 리소스 변환 (향후)

### 4.5 QC (Quality Control) 관리

#### 4.5.1 Study 병합/분리
- **Study 병합**: 동일 검사가 잘못 분리된 경우 → 하나의 Study로 합침
- **Study 분리**: 다른 환자/검사가 잘못 합쳐진 경우 → 별도 Study로 분리
- 병합/분리 시 UID 재생성 및 관련 참조 자동 업데이트
- 변경 이력 감사 로그 기록 (변경 전/후 상태)

#### 4.5.2 환자 정보 수정 (Patient Reconciliation)
- 잘못된 환자 ID/이름으로 수신된 영상의 환자 정보 수정
- 수정 시 관련 모든 DICOM 태그 일괄 업데이트 (Patient ID, Patient Name, Birth Date 등)
- 수정 사유 필수 입력
- 수정 이력 감사 로그 (변경 전/후 값, 수정자, 사유)
- 수정 후 관련 AI 결과/리포트에 대한 연결 유지

#### 4.5.3 영상 품질 검수
- 기사가 수신된 영상의 품질을 확인하고 승인/반려
- 반려 시 재촬영 요청 사유 기록
- QC 상태 관리: 미검수 → 승인 → 반려

### 4.6 관리 기능

#### 4.6.1 사용자 관리
- 사용자 등록/수정/삭제
- 역할 기반 접근 제어 (RBAC)
  - **Admin**: 시스템 전체 관리
  - **Radiologist**: 판독, 리포트 작성, AI 결과 승인
  - **Physician**: 영상 조회, 리포트 조회
  - **Technologist**: 영상 업로드, 워크리스트 관리, QC
  - **Researcher**: 익명화 영상 내보내기, AI 연구용 모델 실행
- 로그인/로그아웃, 세션 관리
- SSO(Single Sign-On) 지원 — 병원 통합 인증 연동

#### 4.6.2 워크리스트 관리 (MWL)
- 검사 예약 목록 관리
- 모달리티 워크리스트 (MWL SCP) 제공
- 검사 상태 추적 (예약 → 진행중 → 판독대기 → 판독완료)
- MPPS 기반 자동 상태 갱신 (4.1.10 연계)
- 수동 워크리스트 등록/수정/삭제
- 향후 HL7 ORM 연동을 통한 자동 워크리스트 생성

**MWL 주요 필드**

| 필드 | DICOM 태그 | 설명 |
|------|-----------|------|
| Patient ID | (0010,0020) | 환자 번호 |
| Patient Name | (0010,0010) | 환자명 (한글 지원) |
| Scheduled Station AE Title | (0040,0001) | 대상 모달리티 |
| Scheduled Procedure Step Start Date/Time | (0040,0002/0003) | 예약 일시 |
| Modality | (0008,0060) | 검사 모달리티 |
| Scheduled Procedure Step Description | (0040,0007) | 검사 설명 |
| Requested Procedure ID | (0040,1001) | 검사 요청 ID |
| Accession Number | (0008,0050) | 접수 번호 |

#### 4.6.3 시스템 관리
- DICOM 노드(AE Title) 등록/관리/연결 테스트 (C-ECHO)
- 라우팅 규칙 설정
- AI 트리거 규칙 설정
- 행잉 프로토콜 규칙 설정
- 데이터 보존 정책 설정
- 시스템 로그 조회

#### 4.6.4 감사 로그
- 모든 영상 조회/내보내기/삭제 기록
- 사용자별 접근 이력
- AI 추론 요청/결과 이력
- 리포트 작성/수정 이력
- QC 변경 이력 (Study 병합/분리, 환자 정보 수정)
- 개인정보보호법 및 HIPAA 감사 요구사항 충족
- 감사 로그 최소 3년 보관 (개인정보보호법)

#### 4.6.5 운영 모니터링
- **서비스 상태**: Orthanc, FastAPI, Keycloak, Redis, PostgreSQL 헬스체크
- **리소스 모니터링**: CPU, 메모리, 디스크, GPU 사용률 (Prometheus)
- **DICOM 수신 모니터링**: 수신 건수, 실패 건수, 평균 처리 시간
- **장애 알림**: AlertManager 기반 자동 알림 (이메일, SMS, 메신저)
  - 서비스 다운, 디스크 부족(80%/90%), DICOM 수신 실패 연속 발생, AI Worker 전체 다운
- **대시보드**: Grafana 기반 통합 운영 대시보드

### 4.7 데이터 마이그레이션

#### 4.7.1 기존 PACS 데이터 이관
- **C-MOVE 기반 이관**: 기존 PACS에서 C-MOVE로 영상 일괄 수신
- **DICOM 파일 직접 Import**: 파일시스템에서 직접 Orthanc으로 벌크 임포트
- **증분 이관**: 날짜 범위 기반으로 단계적 이관 (최근 → 과거 순)
- **이관 검증**: 원본 vs 이관 데이터 건수/체크섬 비교 검증
- **이관 진행률 대시보드**: 전체/완료/실패 건수, 예상 소요 시간

#### 4.7.2 이관 계획
- 운영 중단 없이 이관 (병행 운영 기간 설정)
- 이관 중 신규 영상은 신규 PACS에 직접 수신
- 이관 완료 후 데이터 정합성 최종 검증

---

## 5. 보안 요구사항

### 5.1 데이터 전송 보안

| 항목 | 요구사항 |
|------|---------|
| TLS | 1.2 이상 필수, TLS 1.3 권장 |
| DICOM TLS | DIMSE 통신 시 TLS 적용 |
| HTTPS | 모든 웹 API 통신 HTTPS 필수 |
| PFS | Perfect Forward Secrecy 구현 |
| WebSocket | WSS(WebSocket Secure) 필수 |

### 5.2 데이터 저장 보안

| 항목 | 요구사항 |
|------|---------|
| DB 암호화 | PostgreSQL pgcrypto — PHI 포함 컬럼 레벨 암호화 |
| 파일 암호화 | LUKS/dm-crypt — DICOM Storage 볼륨 암호화 |
| 백업 암호화 | MinIO SSE-S3 — AES-256 서버 사이드 암호화 |
| 키 관리 | 환경변수/시크릿 매니저를 통한 안전한 키 관리 |

### 5.3 접근 제어

| 항목 | 요구사항 |
|------|---------|
| 인증 | OAuth2 / OIDC (Keycloak) |
| 인가 | RBAC — 역할별 기능 접근 제한 |
| 세션 | JWT 기반, Access Token(1h) + Refresh Token(7d) |
| 환자 데이터 | 담당 의사/부서만 해당 환자 영상 접근 가능 |
| 비활동 잠금 | 10분 비활동 시 자동 화면 잠금, 30분 비활동 시 자동 로그아웃 |
| 비밀번호 정책 | 최소 8자, 대/소문자+숫자+특수문자, 90일 만료, 이전 5회 재사용 금지 |
| Break-the-Glass | 비상 시 관리자 승인 없이 전체 접근 가능, 사후 감사 필수 |

### 5.4 한국 개인정보보호법 준수

- 개인정보 처리 목적/항목/보유기간 명시
- 개인정보 처리 동의 관리
- 개인정보 접근 로그 기록 (최소 3년 보관)
- 개인정보 영향평가 — 민감정보(의료 정보) 처리 시 필수
- 개인정보 파기 — 보존 기간 만료 시 지체 없이 파기 (복구 불가능한 방법)
- 안전성 확보 조치 — 접근 권한 관리, 접근 통제, 암호화, 물리적 안전조치

### 5.5 HIPAA 준수 항목 (국제 참조)

- PHI(Protected Health Information) 접근 로그 기록
- 자동 로그아웃 (비활동 시간 초과)
- 데이터 무결성 검증
- 비상 접근 절차 (Break-the-Glass)

### 5.6 SaMD(Software as a Medical Device) 규제 대응

| 구성 요소 | SaMD 해당 여부 | 대응 |
|-----------|--------------|------|
| PACS 서버/뷰어 | 일반 의료 소프트웨어 | 의료기기 해당 여부 확인 필요 (식약처 기준) |
| AI 진단 보조 모듈 | SaMD 해당 가능 | 인증 모델만 임상 적용, 미인증은 연구용 분리 |
| 측정 도구 | SaMD 해당 가능 | Pixel Spacing 정확도 검증, 교정 기록 유지 |

- AI 모듈과 PACS 코어를 분리 설계하여 인허가 범위 최소화
- AI 결과에는 항상 "보조 진단" 면책 고지 표시

---

## 6. 비기능 요구사항

### 6.1 성능

| 항목 | 목표 |
|------|------|
| 영상 목록 로딩 | < 2초 (100건 기준) |
| 단일 영상 표시 | < 1초 (CR/DX 기준) |
| CT 시리즈 로딩 | < 5초 (300장 기준, 프로그레시브) |
| 동시 사용자 | 50명 이상 |
| 일일 검사 수용 | 500건 이상 |
| AI 추론 (GPU) | < 30초 (CT 1 Study 기준) |
| AI 추론 (CPU) | < 120초 (CT 1 Study 기준) |
| AI 추론 (CXR, CPU) | < 10초 (단일 X-ray) |
| 비표준 DICOM 검증 | < 2초 (단일 인스턴스) |
| 검색 응답 (QIDO-RS) | < 1초 (1000건 인덱스 기준) |

### 6.2 가용성

| 항목 | 목표 |
|------|------|
| 가동률 | 99.5% 이상 (연간 44시간 미만 다운타임) |
| 백업 | 일 1회 자동 백업 (3.4 백업 아키텍처 참조) |
| 복구 목표 시간 (RTO) | < 4시간 |
| 복구 목표 시점 (RPO) | < 24시간 |
| HA 구성 | PostgreSQL Replica, Redis Sentinel, Nginx Active-Passive (3.3 참조) |

### 6.3 확장성

- 수평 확장: 다중 Orthanc 인스턴스 + PostgreSQL 공유 인덱스, Nginx 로드밸런싱
- 스토리지 확장: S3 호환 오브젝트 스토리지 연동
- 인덱싱 확장: PostgreSQL Streaming Replication
- AI Worker 확장: Celery Worker 수평 증설
- 검증 엔진 확장: 외부 FastAPI 서비스 독립 스케일링

### 6.4 호환성

| 항목 | 지원 범위 |
|------|----------|
| 브라우저 | Chrome 90+, Firefox 90+, Safari 15+, Edge 90+ |
| 모달리티 | DICOM 3.0 준수 모든 장비 |
| PACS 연동 | DICOM C-STORE/C-FIND/C-MOVE, DICOMweb |
| HIS/RIS | HL7 v2 (향후 FHIR 지원) |
| 문자셋 | UTF-8 기본, EUC-KR(ISO 2022 IR 149) 호환 |
| OHIF 버전 | 특정 버전 고정 + 마이너 업데이트만 적용 (메이저 업데이트는 호환성 테스트 후) |

### 6.5 다국어/로컬라이제이션

| 항목 | 지원 |
|------|------|
| UI 언어 | 한국어 (기본), 영어 |
| OHIF 한국어화 | OHIF i18n 시스템을 통한 한국어 번역 파일 제공 |
| 환자명 | 한글 PN(Person Name) 정상 표시 및 검색 |
| 날짜/시간 | KST(한국 표준시) 기본, 타임존 설정 가능 |
| 리포트 | 한국어 템플릿 기본 제공 |

---

## 7. 개발 계획 (총 30주)

### 7.1 Phase 1: 기반 구축 (4주)

| 작업 | 설명 |
|------|------|
| 개발 환경 구성 | Docker Compose 기반 Orthanc + PostgreSQL + Redis + Nginx + Prometheus + Grafana 세팅 |
| Orthanc 설정 | DICOM 서버 설정, DICOMweb 플러그인 활성화, PostgreSQL 플러그인 |
| FastAPI 프로젝트 초기화 | 프로젝트 구조, DB 모델, 인증 모듈 |
| DICOM 연동 검증 | 테스트 모달리티로 C-STORE/C-FIND/C-MOVE 검증 |
| 한글 처리 검증 | Specific Character Set 설정, 한글 환자명 수신/검색 확인 |
| 모니터링 기반 구축 | Prometheus 메트릭 수집, Grafana 기본 대시보드, AlertManager 알림 설정 |

### 7.2 Phase 2: PACS 서버 핵심 기능 (4주)

| 작업 | 설명 |
|------|------|
| DICOMweb API 검증 | QIDO-RS, WADO-RS, WADO-URI, STOW-RS 동작 확인 및 커스텀 래핑 |
| 사용자 인증/인가 | Keycloak 통합, RBAC 구현, SSO 설정, 비밀번호 정책 |
| 워크리스트 관리 | MWL SCP 구현, MPPS SCP, 검사 상태 추적 |
| 영상 라우팅 | 자동 라우팅 규칙 엔진 |
| 비표준 DICOM 검증 엔진 | 외부 FastAPI 서비스, 메타데이터/픽셀/JPEG 검증, 심각도 분류, 정규화 |
| WebSocket 알림 | 영상 수신 실시간 알림 구현, Nginx WebSocket 프록시 설정 |

### 7.3 Phase 3: 웹 뷰어 개발 (6주)

| 작업 | 설명 |
|------|------|
| OHIF Viewer 통합 | OHIF v3 버전 고정, 빌드 및 Orthanc DICOMweb 연결, 한국어 i18n |
| 기본 뷰어 기능 | W/L, 줌, 팬, 스크롤, 레이아웃, 다중 모니터 |
| 측정/주석 도구 | 길이, 각도, 면적, 텍스트, 화살표 |
| 고급 렌더링 | MPR, MIP, CINE 모드, Prior Study 비교 (동기화 포함) |
| 행잉 프로토콜 | JSON 규칙 엔진, 모달리티/Body Part별 자동 레이아웃 |
| 비표준 대응 UI | 경고 표시, Pixel Spacing 신뢰도, 폴백 처리 |
| 모바일 반응형 | 터치 제스처, 모바일 레이아웃, 기능 제한 처리 |
| 성능 최적화 | HTJ2K, 프리페칭, 프로그레시브 로딩 |

### 7.4 Phase 4: 관리, 리포트, QC, 보안 (5주)

| 작업 | 설명 |
|------|------|
| Admin Portal | Next.js 15 기반 관리 UI, 검증 대시보드, 운영 모니터링 대시보드 |
| 판독 리포트 | 한국어 템플릿, 작성/서명 워크플로우, 동시편집 잠금, DICOM SR 저장 |
| QC 관리 | Study 병합/분리, Patient Reconciliation, 영상 품질 검수 |
| 감사 로그 | 접근 이력 기록 및 조회 (개인정보보호법 3년 보관) |
| 보안 강화 | TLS 설정, 볼륨 암호화, pgcrypto, 비활동 잠금, Break-the-Glass |
| DICOM 노드 관리 | AE Title 등록/테스트 UI |
| 익명화/내보내기 | 비식별화 엔진, 내보내기(DICOM/JPEG/CD 패키징), 보존 정책 엔진 |
| 데이터 보존 관리 | Cold Storage 자동 이관, 삭제 감사, 용량 모니터링 알림, 무결성 검증 배치 |
| Prefetch | 예약 기반 사전 로딩 스케줄러 |

### 7.5 Phase 5: 의료 AI 연동 (7주)

| 작업 | 설명 |
|------|------|
| AI 워크플로우 엔진 | 자동/수동 트리거, Celery+Redis 비동기 큐, 상태 관리 |
| AI 모델 통합 인터페이스 | 표준 추론 API, Docker 컨테이너/ONNX/외부 API 어댑터 |
| GPU/CPU 실행 전략 | ONNX Runtime CPU 폴백, OpenVINO 최적화, 클라우드 API 연동 |
| 영상 전처리 파이프라인 | DICOM→텐서 변환, 정규화, 3D 볼륨 재구성 |
| AI 결과 DICOM 저장 | highdicom 기반 SEG/SR/PR/SC/ANN 생성 |
| AI 결과 뷰어 시각화 | 세그멘테이션 오버레이(다운샘플링), 바운딩 박스, 히트맵, 리포트 패널 |
| AI 판독 워크플로우 | Triage, 자동 행잉 프로토콜, 리포트 삽입, 동의/비동의 |
| 긴급 알림 시스템 | Critical Finding Alert, SMTP/SMS/Webhook 연동, 에스컬레이션 |
| AI 모델 관리 UI | Admin Portal에 모델 등록/관리/통계 화면 |
| AI 성능 대시보드 | 처리량, 추론 시간, 오류율, 임상 품질 지표, Prometheus/Grafana 연동 |

### 7.6 Phase 6: 통합 테스트 (2주)

| 작업 | 설명 |
|------|------|
| DICOM 호환성 테스트 | 다양한 벤더 장비, 비표준 DICOM 샘플 테스트 |
| AI 파이프라인 E2E | 영상 수신 → AI 추론 → 결과 저장 → 뷰어 표시 전체 흐름 |
| 성능 테스트 | 50명 동시 접속 부하, 대용량 영상, AI 추론 응답시간 |
| 보안 테스트 | OWASP Top 10 점검, 취약점 스캐닝, Break-the-Glass 검증 |
| 한글 처리 검증 | 다양한 문자셋 DICOM 파일 호환 테스트 |
| HA 검증 | 페일오버 테스트 (PostgreSQL, Redis, Nginx) |

### 7.7 Phase 7: 데이터 마이그레이션 (2주)

| 작업 | 설명 |
|------|------|
| 마이그레이션 도구 | C-MOVE 기반 일괄 수신, 파일 벌크 임포트 도구 |
| 이관 테스트 | 소량 테스트 이관, 데이터 정합성 검증 |
| 이관 계획 수립 | 기관별 이관 순서, 병행 운영 계획 |

### 7.8 Phase 8: 문서화 및 배포 (2주)

| 작업 | 설명 |
|------|------|
| 문서화 | 설치 가이드, 사용자 매뉴얼, API 문서, DICOM Conformance Statement |
| 배포 | Docker Compose 기반 프로덕션 배포 |
| 운영 가이드 | 백업/복구 절차, 모니터링 설정, 장애 대응 매뉴얼 |

### Backlog (선택적 구현)

| 작업 | 설명 |
|------|------|
| DICOM Print | 필름 프린터 연동 (DICOM Print SCU) |
| HL7 연동 | Mirth Connect 기반 HL7 v2 ORM/ORU 수신/전송 |
| FHIR 어댑터 | FHIR ImagingStudy / DiagnosticReport 변환 |
| Teaching File | 교육/연구용 증례 수집 태깅 기능 |
| 3D VRT | Volume Rendering Technique |
| 다중 기관 | 멀티테넌시 지원 (v2.0) |

---

## 8. 기술 스택 비교 및 선택 근거

### 8.1 DICOM 서버: Orthanc vs DCM4CHEE

| 항목 | Orthanc (선택) | DCM4CHEE |
|------|---------------|----------|
| 설치 | 독립형 바이너리, 매우 간편 | JDK + WildFly + LDAP, 복잡 |
| 학습 곡선 | 낮음 | 높음 |
| REST API | 내장, 직관적 | 있으나 복잡 |
| 플러그인 | DICOMweb, PostgreSQL, Python 등 | 제한적 |
| 확장성 | 중소규모에 적합 | 대규모 엔터프라이즈 |
| **결론** | 중소 병원/클리닉 대상이므로 Orthanc이 적합 | |

### 8.2 웹 뷰어: OHIF vs 커스텀

| 항목 | OHIF Viewer (선택) | 커스텀 (Cornerstone3D) |
|------|-------------------|---------------------|
| 개발 시간 | 단축 (기본 기능 내장) | 긴 개발 기간 |
| 기능 완성도 | 높음 (2D/3D, 측정, 주석) | 직접 구현 필요 |
| 커스터마이징 | Extension/Mode 시스템 | 완전 자유 |
| AI 시각화 | SEG/SR 렌더링 내장 | 직접 구현 필요 |
| 버전 리스크 | 메이저 업데이트 시 Extension 호환성 깨짐 가능 | 없음 |
| **결론** | OHIF를 기반으로 버전 고정 + Extension 추가. 메이저 업데이트는 호환성 테스트 후 적용 | |

### 8.3 백엔드: FastAPI (Python) vs Node.js

| 항목 | FastAPI (선택) | Node.js (Express) |
|------|--------------|-------------------|
| DICOM 라이브러리 | pydicom, pynetdicom (성숙) | dcmjs, dcmjs-dimse (발전 중) |
| 비동기 처리 | async/await 네이티브 | 네이티브 |
| 타입 안전 | Pydantic 모델 | TypeScript 필요 |
| 의료 AI 통합 | NumPy, SciPy, TensorFlow, ONNX 연동 용이 | 제한적 |
| 익명화/검증 | pydicom 기반 태그 조작 용이 | 제한적 |
| **결론** | DICOM 생태계와 AI 확장성 고려하여 Python 선택 | |

### 8.4 인증: Keycloak vs 자체 구현

| 항목 | Keycloak (선택) | 자체 구현 |
|------|---------------|----------|
| 기능 완성도 | OAuth2/OIDC/RBAC/SSO 내장 | 직접 구현 필요 |
| 운영 부담 | JVM 기반, 설정 복잡 | 경량화 가능 |
| 병원 SSO | LDAP/AD 연동 내장 | 직접 구현 필요 |
| **결론** | 병원 SSO 연동과 보안 표준 준수를 위해 Keycloak 선택. 운영 부담은 Docker 기반 배포와 설정 자동화로 완화 | |

---

## 9. 리스크 및 대응

| 리스크 | 확률 | 영향 | 대응 방안 |
|--------|:----:|:----:|----------|
| 대용량 영상 처리 성능 | 보통 | 높음 | HTJ2K 압축, 프로그레시브 로딩, 프리페칭 |
| DICOM 호환성 이슈 | 높음 | 높음 | 다양한 벤더 장비로 사전 호환성 테스트, Conformance Statement 작성 |
| 보안 취약점 | 보통 | 높음 | 정기 보안 감사, OWASP Top 10 점검, 취약점 스캐닝 |
| Orthanc 성능 한계 | 보통 | 보통 | 다중 인스턴스 구성, 필요시 DCM4CHEE 전환 |
| Orthanc Python 플러그인 GIL 병목 | 높음 | 높음 | 검증 엔진을 외부 FastAPI 서비스로 분리, 비동기 호출 |
| 비표준 DICOM 유입 | 높음 | 높음 | 수신 시 자동 검증 파이프라인, 정규화 엔진, 장비별 패턴 DB 구축 |
| JPEG 밀도 조작으로 인한 측정 오류 | 보통 | 높음 | Pixel Spacing vs JPEG density 교차 검증, 측정 시 신뢰도 표시 |
| AI 모델 GPU 리소스 부족 | 보통 | 높음 | CPU 폴백(ONNX Runtime/OpenVINO), 클라우드 API 하이브리드, 우선순위 스케줄링 |
| AI 결과 신뢰성/법적 책임 | 보통 | 높음 | AI 결과는 보조 수단으로 명시, 판독의 최종 확인 필수, 면책 고지 상시 표시 |
| AI 모델 의료기기 인허가 | 보통 | 보통 | 임상용/연구용 분리, FDA/CE/MFDS 인증 모델만 임상 사용 |
| 대용량 DICOM SEG WebGL 메모리 초과 | 보통 | 보통 | 고해상도 SEG 다운샘플링 옵션, 렌더링 품질 설정 |
| OHIF 메이저 업데이트 호환성 | 보통 | 보통 | 버전 고정 전략, 마이너만 적용, 메이저는 호환성 테스트 후 |
| Keycloak 운영 복잡도 | 보통 | 보통 | Docker 기반 배포, 설정 자동화, 간소화 매뉴얼 제공 |
| 한국 법규 미준수 | 낮음 | 높음 | 개인정보보호법/의료법 요구사항 설계 단계에서 반영, 법률 자문 |
| SaMD 규제 대상 판정 | 낮음 | 보통 | PACS 코어와 AI 모듈 분리 설계, 식약처 사전 상담 |
| 네트워크 단절 시 영상 조회 불가 | 낮음 | 높음 | 최근 조회 영상 브라우저 로컬 캐시(Service Worker), 긴급 시 Orthanc 직접 접속 폴백 |
| 기존 PACS 데이터 마이그레이션 실패 | 보통 | 높음 | 증분 이관, 이관 검증 도구, 병행 운영 기간 확보 |
| 오픈소스 라이선스 | 낮음 | 보통 | GPLv3(Orthanc) 준수 확인, 라이선스 검토 |

---

## 10. 용어 정의

### DICOM 관련

| 용어 | 설명 |
|------|------|
| **DICOM** | Digital Imaging and Communications in Medicine — 의료 영상 표준 |
| **PACS** | Picture Archiving and Communication System — 영상 저장/전송 시스템 |
| **SOP** | Service-Object Pair — DICOM 서비스와 정보 객체의 조합 |
| **AE Title** | Application Entity Title — DICOM 네트워크 노드 식별자 |
| **Transfer Syntax** | 전송 구문 — 데이터 인코딩 방식 (압축 포함) |
| **VR** | Value Representation — DICOM 태그의 데이터 타입 (DA, IS, PN 등) |
| **HTJ2K** | High-Throughput JPEG 2000 — 고속 JPEG2000 변형, 프로그레시브 로딩 지원 |
| **Pixel Spacing** | 픽셀 간 물리적 거리 (mm 단위), 실측정의 기준 |
| **JPEG Density** | JFIF 헤더의 Xdensity/Ydensity — 픽셀 밀도(DPI/DPM) 정보 |
| **JFIF** | JPEG File Interchange Format — JPEG 파일의 메타데이터 헤더 포맷 |
| **ICC 프로필** | International Color Consortium Profile — 장치 간 색 관리를 위한 표준 |
| **Conformance** | DICOM 표준 준수 여부. Conformance Statement는 장비의 표준 준수 명세서 |
| **Transcoding** | Transfer Syntax 변환. 예: JPEG2000 → Explicit VR Little Endian |
| **BOT** | Basic Offset Table — Encapsulated 픽셀 데이터의 프래그먼트 위치 테이블 |
| **SR** | Structured Report — DICOM 구조화 보고서 |
| **DICOM SEG** | Segmentation — AI 세그멘테이션 마스크를 저장하는 DICOM IOD |
| **DICOM ANN** | Annotation — 좌표 기반 주석(포인트, 폴리라인, 바운딩 박스) 저장 IOD (Supplement 222) |
| **DICOMDIR** | DICOM 미디어(CD/DVD)의 디렉토리 파일 |
| **Burned-in Annotation** | 영상 픽셀에 직접 포함된 텍스트/주석 (제거 불가) |
| **MPPS** | Modality Performed Procedure Step — 모달리티 검사 수행 절차 단계 통보 |
| **MWL** | Modality Worklist — 모달리티 작업 목록 |

### 의료 시스템 관련

| 용어 | 설명 |
|------|------|
| **RIS** | Radiology Information System — 영상의학과 정보 시스템 |
| **HIS** | Hospital Information System — 병원 정보 시스템 |
| **EMR** | Electronic Medical Record — 전자의무기록 |
| **IHE** | Integrating the Healthcare Enterprise — 의료 시스템 통합 표준 프레임워크 |
| **AIW/AIR** | AI Workflow / AI Results — IHE의 AI 연동 프로파일 |
| **SaMD** | Software as a Medical Device — 의료기기 소프트웨어 |
| **PHI** | Protected Health Information — 보호 대상 건강 정보 |
| **Triage** | 긴급도에 따른 검사 우선순위 분류 |
| **NIfTI** | Neuroimaging Informatics Technology Initiative — 신경영상 파일 포맷. AI 학습에 사용 |

### 뷰어/영상 관련

| 용어 | 설명 |
|------|------|
| **W/L** | Window/Level — 영상 밝기/대비 조정 |
| **MPR** | Multi-Planar Reconstruction — 다평면 재구성 |
| **MIP** | Maximum Intensity Projection — 최대 강도 투영 |
| **Zero-footprint** | 별도 설치 없이 웹 브라우저에서 실행되는 방식 |
| **CAM** | Class Activation Map — AI 모델이 주목하는 영역을 시각화하는 히트맵 |
| **CAD** | Computer-Aided Detection/Diagnosis — 컴퓨터 보조 검출/진단 |

### AI/인프라 관련

| 용어 | 설명 |
|------|------|
| **MONAI** | Medical Open Network for Artificial Intelligence — NVIDIA 의료 AI 프레임워크 |
| **highdicom** | DICOM SEG/SR/SC 등 복합 IOD 생성을 위한 Python 라이브러리 |
| **ONNX** | Open Neural Network Exchange — AI 모델 범용 교환 포맷 |
| **OpenVINO** | Intel의 AI 추론 최적화 툴킷 — CPU 기반 고속 추론 |
| **CUDA** | NVIDIA GPU 병렬 컴퓨팅 플랫폼 |
| **Celery** | Python 비동기 분산 작업 큐 프레임워크 |
| **RBAC** | Role-Based Access Control — 역할 기반 접근 제어 |
| **OIDC** | OpenID Connect — OAuth2 기반 인증 프로토콜. 사용자 신원 확인에 사용 |
| **SSO** | Single Sign-On — 통합 인증 (한 번 로그인으로 여러 시스템 접근) |
| **PFS** | Perfect Forward Secrecy — TLS 세션 키 유출 시에도 과거 통신 보호 |
| **RTO** | Recovery Time Objective — 장애 발생 후 서비스 복구까지의 목표 시간 |
| **RPO** | Recovery Point Objective — 장애 발생 시 허용 가능한 최대 데이터 손실 시점 |
