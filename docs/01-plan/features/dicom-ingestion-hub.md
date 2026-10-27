# DICOM 영상 수집 허브 기획서

> **버전**: v9.2  
> **작성일**: 2026-05-26  
> **우선순위**: P0 (파일럿 필수)  
> **예상 API**: 25개 신규 + 5개 수정  
> **예상 페이지**: 5개 신규  
> **핵심 목표**: 모든 경로(외부 PACS, 환자, 키오스크, 관리자)로부터의 DICOM 수집을 하나의 플랫폼에서 관리

---

## 1. 개요

### 1.1 영상 수집 경로 — 전체 그림

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DICOM 영상 수집 허브                          │
├─────────┬──────────┬──────────┬──────────┬─────────────────────────┤
│  경로 1  │  경로 2   │  경로 3   │  경로 4   │        경로 5           │
│ 외부 PACS│ 환자 포털  │ 키오스크  │ 관리자    │   장비 직접 전송         │
│ 연동     │ (셀프)    │ (CD/USB) │ 업로드    │   (C-STORE)            │
├─────────┼──────────┼──────────┼──────────┼─────────────────────────┤
│Q/R, 피어 │웹 업로드  │터치 UI   │드래그&드롭│ Orthanc 수신           │
│C-MOVE   │모바일 촬영│DICOMDIR  │ZIP/배치  │ (기존, 이미 동작)       │
│DICOM Send│가이드    │바코드스캔│검증+정규화│                        │
└────┬────┴────┬─────┴────┬────┴────┬────┴────────┬────────────────┘
     │         │          │         │              │
     ▼         ▼          ▼         ▼              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    OpenPACS Orthanc Server                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ 자동 검증 │→ │ 자동 수정 │→ │ DB 저장  │→ │ 판독 큐 등록     │   │
│  │(Validator)│  │(Normalizer│  │(Orthanc) │  │(Reading Queue)   │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 현재 상태 vs 목표

| 경로 | 현재 | 목표 |
|------|------|------|
| **외부 PACS 연동** | 없음 (ad-hoc C-STORE만) | Query/Retrieve UI + 피어 관리 + 자동 라우팅 |
| **환자 셀프 업로드** | 없음 | 토큰 기반 웹 포털 (CD/파일 업로드 + 모바일 촬영) |
| **키오스크 (병원 내)** | CD import API만 (UI 없음) | 터치 최적화 전용 페이지 + 바코드 환자 매칭 |
| **관리자/연구자 업로드** | STOW-RS + 배치 API | 드래그&드롭 UI + 폴더 업로드 + 진행률 |
| **장비 C-STORE** | 동작 중 | 유지 (자동 검증 연동은 v9.0에서 완료) |

---

## 2. 경로 1: 외부 PACS 연동

### 2.1 기능 개요

다른 병원/기관의 PACS에서 영상을 가져오거나, 우리 영상을 보내는 기능.

### 2.2 DICOM 피어/모달리티 관리

Orthanc의 피어(peer)와 모달리티(modality)를 관리 UI에서 설정.

**피어(Peer)**: 다른 Orthanc 서버 (HTTP REST 기반)
```json
{
  "name": "서울대병원PACS",
  "url": "https://pacs.snuh.org/orthanc",
  "username": "openpacs",
  "password": "****",
  "type": "peer"
}
```

**모달리티(Modality)**: 전통적 DICOM 장비 (DIMSE 프로토콜)
```json
{
  "name": "2층CT",
  "ae_title": "CT_2F",
  "host": "192.168.1.50",
  "port": 4242,
  "type": "modality"
}
```

### 2.3 Query/Retrieve (C-FIND + C-MOVE)

외부 PACS에서 환자/검사를 검색하고 가져오기:

```
관리자 → 피어/모달리티 선택
  → 검색 조건 입력 (환자명, ID, 날짜, 모달리티)
  → C-FIND 실행 → 결과 목록 표시
  → 선택 → C-MOVE/C-GET 실행 → 수신 진행률 표시
  → 수신 완료 → 자동 검증 → 판독 큐 등록
```

### 2.4 영상 전송 (C-STORE / Peer Send)

우리 영상을 외부로 보내기:

```
판독 큐에서 Study 선택 → "전송" 버튼
  → 대상 피어/모달리티 선택
  → C-STORE 또는 Peer Send 실행
  → 전송 이력 기록
```

### 2.5 자동 라우팅 규칙

조건 기반 자동 전송:

```
규칙 예시:
  IF modality == "MR" AND study_description CONTAINS "brain"
  THEN auto-forward TO "신경외과PACS"
  
  IF referring_physician == "김내과"
  THEN auto-forward TO "내과HIS"
```

### 2.6 API 설계

| # | Method | Endpoint | 설명 |
|---|--------|----------|------|
| 1 | GET | `/api/v1/remotes` | 피어/모달리티 목록 |
| 2 | POST | `/api/v1/remotes` | 피어/모달리티 등록 |
| 3 | PUT | `/api/v1/remotes/{id}` | 수정 |
| 4 | DELETE | `/api/v1/remotes/{id}` | 삭제 |
| 5 | POST | `/api/v1/remotes/{id}/echo` | C-ECHO 연결 테스트 |
| 6 | POST | `/api/v1/remotes/{id}/query` | C-FIND 검색 |
| 7 | POST | `/api/v1/remotes/{id}/retrieve` | C-MOVE/C-GET 가져오기 |
| 8 | POST | `/api/v1/remotes/{id}/send` | C-STORE/Peer Send 보내기 |
| 9 | GET | `/api/v1/remotes/transfer-history` | 전송/수신 이력 |
| 10 | GET/POST | `/api/v1/remotes/routing-rules` | 자동 라우팅 규칙 CRUD |

### 2.7 Admin 페이지

**`/pacs-admin/remotes`** — 외부 연동 관리
- 피어/모달리티 목록 (카드형)
- 등록/수정 모달 (연결 테스트 포함)
- Query/Retrieve 탭 (검색 + 결과 + 가져오기)
- 전송 이력 탭
- 라우팅 규칙 탭

---

## 3. 경로 2: 환자 셀프 업로드 포털

### 3.1 기능 개요

환자가 직접 자신의 의료 영상을 업로드하는 웹 포털. 타 병원에서 받은 CD, 개인 보관 영상 등.

### 3.2 접근 방식

토큰 기반 1회성 접근 (기존 consult-portal 패턴 활용):

```
접수 데스크 → 환자에게 업로드 링크 발급 (QR코드/SMS)
  → 환자 스마트폰 또는 PC에서 접속
  → 본인 확인 (이름 + 생년월일 + 환자번호)
  → 파일 업로드 (CD ZIP / 개별 DICOM / 모바일 촬영)
  → 업로드 완료 → 기사/관리자 승인 → Orthanc 저장
```

### 3.3 화면 구성

**환자 업로드 포털** (`/patient-upload?token=xxx`)

```
┌─────────────────────────────────────────────────┐
│  🏥 WeRU.B PACS 영상 업로드                       │
│                                                   │
│  안녕하세요, 홍길동님                               │
│  아래 방법 중 하나로 영상을 업로드하세요.              │
│                                                   │
│  ┌──────────────┐  ┌──────────────┐               │
│  │  📁 파일 선택  │  │  📷 사진 촬영  │              │
│  │  CD/USB에서   │  │  필름/문서를   │              │
│  │  DICOM 파일   │  │  카메라로 촬영  │              │
│  └──────────────┘  └──────────────┘               │
│                                                   │
│  또는 ZIP 파일을 여기에 드래그하세요                   │
│  ┌─────────────────────────────────┐              │
│  │         드롭 영역               │              │
│  │    최대 500MB, DICOM/ZIP        │              │
│  └─────────────────────────────────┘              │
│                                                   │
│  업로드된 파일 (3건)                                │
│  ├─ chest_ct_001.dcm ✅ 유효                     │
│  ├─ chest_ct_002.dcm ✅ 유효                     │
│  └─ report.pdf       ⚠ DICOM 아님 (건너뜀)       │
│                                                   │
│  [업로드 제출]                                     │
│                                                   │
│  ⚠ 업로드된 영상은 담당 의료진이 확인 후              │
│    시스템에 등록됩니다.                              │
└─────────────────────────────────────────────────┘
```

### 3.4 보안 및 법적 고려

| 항목 | 대응 |
|------|------|
| 본인 확인 | 토큰 + 이름/생년월일/환자번호 3중 확인 |
| 동의 | 개인정보 수집·이용 동의 (업로드 전 필수 체크) |
| 토큰 만료 | 24시간 (설정 가능) |
| 파일 크기 | 최대 500MB (CD 1장 기준) |
| 격리 | 환자 업로드는 바로 Orthanc 저장하지 않음 → 승인 큐 |
| HTTPS | 필수 (TLS 1.3) |
| 감사 로그 | 업로드 시각, IP, 토큰, 파일 목록 기록 |

### 3.5 모바일 촬영 기능

환자가 필름 X-ray나 출력된 리포트를 스마트폰 카메라로 촬영:

```
카메라 촬영 → JPEG 이미지
  → DICOM SC (Secondary Capture) 자동 변환
    - PatientID: 토큰에서 추출
    - Modality: OT (Other)
    - SOPClassUID: 1.2.840.10008.5.1.4.1.1.7 (SC)
  → 승인 큐로 전송
```

### 3.6 API 설계

| # | Method | Endpoint | 인증 | 설명 |
|---|--------|----------|------|------|
| 1 | POST | `/api/v1/patient-upload/token` | ADMIN/TECH | 환자 업로드 토큰 발급 |
| 2 | GET | `/api/v1/patient-upload/verify` | 토큰 | 토큰 검증 + 환자 정보 반환 |
| 3 | POST | `/api/v1/patient-upload/consent` | 토큰 | 개인정보 동의 제출 |
| 4 | POST | `/api/v1/patient-upload/files` | 토큰 | 파일 업로드 (DICOM/ZIP/JPEG) |
| 5 | GET | `/api/v1/patient-upload/status` | 토큰 | 업로드 상태 확인 |
| 6 | GET | `/api/v1/upload-queue` | ADMIN/TECH | 승인 대기 큐 |
| 7 | POST | `/api/v1/upload-queue/{id}/approve` | ADMIN/TECH | 승인 → Orthanc 저장 |
| 8 | POST | `/api/v1/upload-queue/{id}/reject` | ADMIN/TECH | 거부 + 사유 |

---

## 4. 경로 3: 키오스크 (병원 내 CD/USB 업로드)

### 4.1 기능 개요

병원 로비/접수 데스크에 설치된 키오스크 단말에서 환자가 CD/USB를 직접 업로드.

### 4.2 화면 구성 (터치 최적화)

**`/kiosk`** — 전체 화면, 큰 버튼, 터치 최적화

```
┌─────────────────────────────────────────────────────────┐
│  🏥 WeRU.B PACS                                         │
│                                                         │
│  ┌───────────────────────────────────────────────┐      │
│  │                                               │      │
│  │        CD/DVD를 넣어주세요                      │      │
│  │                                               │      │
│  │     💿 ← CD/DVD 드라이브                       │      │
│  │                                               │      │
│  │   또는 USB 메모리를 꽂아주세요                    │      │
│  │                                               │      │
│  └───────────────────────────────────────────────┘      │
│                                                         │
│  ┌─────────────────────┐  ┌─────────────────────┐      │
│  │                     │  │                     │      │
│  │   📱 바코드 스캔     │  │   ⌨️ 환자번호 입력   │      │
│  │   (접수증/팔찌)      │  │   (터치 키패드)      │      │
│  │                     │  │                     │      │
│  └─────────────────────┘  └─────────────────────┘      │
│                                                         │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 진행 상태 ━━━━━━  │
│                                                         │
│  1. CD 인식  ✅                                         │
│  2. 환자 확인 (홍길동, M, 1985-03-15)  ✅                │
│  3. 영상 스캔 중... 45/120 파일                          │
│  4. 업로드                                              │
│  5. 완료                                                │
│                                                         │
│  ┌─────────────────────────────────────────────┐        │
│  │         🟢 업로드 중 — 38%                   │        │
│  │  ████████████░░░░░░░░░░░░░░░░░░░░           │        │
│  └─────────────────────────────────────────────┘        │
│                                                         │
│  [취소]                                    [처음으로]    │
└─────────────────────────────────────────────────────────┘
```

### 4.3 워크플로우

```
1. CD/USB 삽입 감지 (또는 파일 선택)
2. 환자 매칭
   a. 바코드 스캔 → HIS 조회 → 환자 확인
   b. 환자번호 수동 입력 → HIS 조회 → 환자 확인
   c. DICOMDIR에서 환자 정보 추출 → 기존 환자 매칭 시도
3. 중복 검사 (이미 있는 Study 감지)
4. 업로드 (진행률 표시)
5. 완료 안내 (CD 배출)
```

### 4.4 키오스크 특수 요구사항

| 항목 | 요구사항 |
|------|---------|
| 인증 | 키오스크 전용 API 키 (환자 로그인 불필요) |
| 터치 UI | 최소 48px 터치 영역, 큰 폰트, 단순 흐름 |
| 타임아웃 | 3분 무조작 시 초기 화면 복귀 |
| 에러 처리 | "직원을 호출하세요" 안내 (기술 메시지 숨김) |
| 바코드 | USB 바코드 스캐너 (HID 키보드 에뮬레이션) |
| CD 드라이브 | 웹 앱은 CD 직접 접근 불가 → "파일 선택" 또는 로컬 에이전트 |
| 전체 화면 | Kiosk 모드 (F11, Chrome `--kiosk`) |
| 자동 검증 | 업로드 시 자동 DicomValidator 실행 |

### 4.5 CD 드라이브 접근 방식

웹 브라우저에서 CD 드라이브 직접 접근 불가 → 2가지 방안:

**방안 A: 파일 선택 대화상자** (권장, 추가 설치 없음)
```
"파일 선택" 버튼 → 시스템 파일 탐색기 → CD 드라이브 선택 → 폴더 전체 선택
→ File System Access API (Chrome) 또는 webkitdirectory로 폴더 업로드
```

**방안 B: 로컬 에이전트** (자동 감지 필요 시)
```
키오스크 PC에 경량 에이전트 설치 (Electron/Python)
→ CD 삽입 감지 → 자동 파일 읽기 → localhost API로 웹앱에 전달
```

### 4.6 API 설계

| # | Method | Endpoint | 인증 | 설명 |
|---|--------|----------|------|------|
| 1 | POST | `/api/v1/kiosk/session` | API키 | 키오스크 세션 시작 |
| 2 | POST | `/api/v1/kiosk/match-patient` | API키 | 바코드/환자번호로 환자 매칭 |
| 3 | POST | `/api/v1/kiosk/upload` | API키 | DICOM 파일 업로드 (청크) |
| 4 | GET | `/api/v1/kiosk/upload/{session_id}/status` | API키 | 업로드 진행 상태 |
| 5 | POST | `/api/v1/kiosk/upload/{session_id}/complete` | API키 | 업로드 완료 + 검증 실행 |

---

## 5. 경로 4: 관리자/연구자 DICOM 업로드

### 5.1 기능 개요

기존 STOW-RS, 배치 업로드, CD 임포트 API를 **통합 UI**로 제공.

### 5.2 화면 구성

**`/pacs-admin/upload`** — 관리자 업로드 센터

```
┌─────────────────────────────────────────────────────────────────┐
│  DICOM 업로드 센터                                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  [단일 파일] [폴더 업로드] [ZIP/CD 업로드] [외부 가져오기]          │
│                                                                 │
│  ── 드래그 & 드롭 영역 ──────────────────────────────────────   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                                                         │   │
│  │    📂 DICOM 파일, 폴더, 또는 ZIP을 여기에 드롭하세요       │   │
│  │                                                         │   │
│  │    지원 형식: .dcm, .zip, 폴더(DICOMDIR 포함)             │   │
│  │    최대: 2GB (개별 파일 500MB)                            │   │
│  │                                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ── 옵션 ────────────────────────────────────────────────────   │
│  ☑ 자동 검증 (DicomValidator)                                   │
│  ☑ 자동 정규화 (DicomNormalizer)                                │
│  ☐ 익명화 후 업로드                                              │
│  ☐ 연구용 (별도 프로젝트에 저장)                                  │
│                                                                 │
│  ── 업로드 진행 ─────────────────────────────────────────────   │
│  ┌──────┬──────────┬──────┬──────┬──────┬───────┐            │
│  │파일명 │환자       │모달  │상태   │검증   │진행률  │            │
│  ├──────┼──────────┼──────┼──────┼──────┼───────┤            │
│  │001.dcm│홍길동    │CT    │✅완료 │정상   │100%   │            │
│  │002.dcm│홍길동    │CT    │✅완료 │⚠경고 │100%   │            │
│  │003.dcm│홍길동    │CT    │🔄업로드│-     │45%    │            │
│  │004.dcm│홍길동    │CT    │⏳대기 │-     │-      │            │
│  └──────┴──────────┴──────┴──────┴──────┴───────┘            │
│                                                                 │
│  총 120파일 | 완료 45 | 진행 중 1 | 대기 74 | 실패 0              │
│  ████████████████░░░░░░░░░░░░░░ 38%                            │
│                                                                 │
│  [일시정지]  [중지]                                              │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 연구자 전용 기능

| 기능 | 설명 |
|------|------|
| 프로젝트 태깅 | 업로드 시 연구 프로젝트 지정 → 메타데이터로 저장 |
| 자동 익명화 | PatientName/ID 해시 + 날짜 시프트 |
| 코호트 연결 | 업로드된 스터디를 기존 코호트에 자동 추가 |
| 배치 리포트 | 업로드 결과 CSV 다운로드 |

### 5.4 API 설계 (기존 API 활용 + 신규)

| # | Method | Endpoint | 설명 | 비고 |
|---|--------|----------|------|------|
| 1 | POST | `/api/v1/upload/files` | 단일/다중 파일 업로드 | 기존 STOW-RS 래핑 |
| 2 | POST | `/api/v1/upload/folder` | 폴더 업로드 (webkitdirectory) | 신규 |
| 3 | POST | `/api/v1/upload/zip` | ZIP/CD 업로드 | 기존 cd_import 래핑 |
| 4 | GET | `/api/v1/upload/{job_id}/progress` | 업로드 진행 상태 | WebSocket 겸용 |
| 5 | POST | `/api/v1/upload/{job_id}/pause` | 일시정지 |
| 6 | POST | `/api/v1/upload/{job_id}/resume` | 재개 |
| 7 | DELETE | `/api/v1/upload/{job_id}` | 업로드 작업 취소 |

---

## 6. 공통 인프라

### 6.1 승인 큐 (Upload Approval Queue)

환자/키오스크 경로는 직접 Orthanc에 저장하지 않고 승인 큐를 거침:

```sql
CREATE TABLE upload_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 출처
    source VARCHAR(32) NOT NULL,          -- 'patient_portal', 'kiosk', 'admin', 'remote'
    source_detail TEXT,                    -- 토큰ID, 키오스크ID, 사용자명 등
    
    -- 환자 매칭
    patient_id VARCHAR(64),
    patient_name VARCHAR(256),
    matched_patient_id UUID,              -- 기존 환자와 매칭된 경우
    
    -- 파일 정보
    file_count INT DEFAULT 0,
    total_size_bytes BIGINT DEFAULT 0,
    storage_path TEXT,                     -- 임시 저장 경로
    dicomdir_parsed BOOLEAN DEFAULT FALSE,
    study_uids TEXT[],                     -- 포함된 Study UID 목록
    modalities TEXT[],                     -- 포함된 모달리티 목록
    
    -- 검증 결과
    validation_status VARCHAR(16),         -- pending, passed, warning, failed
    validation_summary JSONB,
    
    -- 승인
    status VARCHAR(16) DEFAULT 'pending',  -- pending, approved, rejected, expired
    approved_by UUID,
    approved_at TIMESTAMPTZ,
    reject_reason TEXT,
    
    -- 메타
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,                -- 미승인 시 자동 삭제
    
    INDEX ix_upload_queue_status (status),
    INDEX ix_upload_queue_source (source)
);

-- 환자 업로드 토큰
CREATE TABLE patient_upload_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token VARCHAR(128) UNIQUE NOT NULL,
    patient_id VARCHAR(64) NOT NULL,
    patient_name VARCHAR(256),
    patient_birth_date VARCHAR(8),
    
    -- 동의
    consent_agreed BOOLEAN DEFAULT FALSE,
    consent_agreed_at TIMESTAMPTZ,
    
    -- 상태
    used BOOLEAN DEFAULT FALSE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    INDEX ix_patient_token (token)
);

-- 외부 PACS 피어/모달리티
CREATE TABLE dicom_remotes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL,
    remote_type VARCHAR(16) NOT NULL,      -- 'peer' or 'modality'
    
    -- Peer (Orthanc HTTP)
    url TEXT,
    username VARCHAR(64),
    password_encrypted TEXT,
    
    -- Modality (DIMSE)
    ae_title VARCHAR(16),
    host VARCHAR(256),
    port INT,
    
    -- 상태
    enabled BOOLEAN DEFAULT TRUE,
    last_echo_at TIMESTAMPTZ,
    last_echo_status VARCHAR(16),
    
    -- 메타
    description TEXT,
    tags JSONB DEFAULT '{}',               -- {"department": "radiology", "institution": "서울대"}
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(name)
);

-- 전송/수신 이력
CREATE TABLE dicom_transfer_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    remote_id UUID REFERENCES dicom_remotes(id),
    direction VARCHAR(8) NOT NULL,          -- 'send' or 'receive'
    study_instance_uid VARCHAR(128),
    patient_id VARCHAR(64),
    patient_name VARCHAR(256),
    modality VARCHAR(16),
    series_count INT,
    instance_count INT,
    status VARCHAR(16) DEFAULT 'pending',   -- pending, in_progress, completed, failed
    error_message TEXT,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
```

### 6.2 임시 저장소

환자/키오스크 업로드 파일은 Orthanc 저장 전 임시 디렉토리에 보관:

```
/data/openpacs/upload-staging/
├── patient-portal/
│   └── {token_id}/
│       ├── file1.dcm
│       └── file2.dcm
├── kiosk/
│   └── {session_id}/
│       └── ...
└── admin/
    └── {job_id}/
        └── ...
```

- 승인 후 → Orthanc 업로드 → 임시 파일 삭제
- 72시간 미승인 → 자동 삭제 (Celery beat)

### 6.3 JPEG → DICOM SC 변환

환자 모바일 촬영(JPEG)을 DICOM Secondary Capture로 변환:

```python
def jpeg_to_dicom_sc(jpeg_bytes, patient_id, patient_name, study_desc="Mobile Capture"):
    """Convert JPEG image to DICOM Secondary Capture."""
    ds = Dataset()
    ds.PatientID = patient_id
    ds.PatientName = patient_name
    ds.Modality = "OT"
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.7"  # SC Image Storage
    ds.StudyDescription = study_desc
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 3
    ds.PhotometricInterpretation = "YBR_FULL_422"
    ds.TransferSyntaxUID = "1.2.840.10008.1.2.4.50"  # JPEG Baseline
    # ... set pixel data from JPEG
    return ds
```

---

## 7. 페이지 구성 요약

| # | 경로 | 페이지 | 대상 | 인증 |
|---|------|--------|------|------|
| 1 | `/pacs-admin/remotes` | 외부 PACS 연동 관리 | 관리자 | JWT |
| 2 | `/patient-upload` | 환자 셀프 업로드 포털 | 환자 | 토큰 |
| 3 | `/kiosk` | 키오스크 CD/USB 업로드 | 환자/직원 | API키 |
| 4 | `/pacs-admin/upload` | 관리자 업로드 센터 | 관리자/연구자 | JWT |
| 5 | `/pacs-admin/upload-queue` | 승인 대기 큐 | 관리자/기사 | JWT |

---

## 8. 구현 우선순위

### Phase A: 관리자 업로드 센터 + 승인 큐 (즉시 활용)

| # | 작업 |
|---|------|
| 1 | 업로드 센터 UI (드래그&드롭 + 진행률 + 검증 결과 인라인) |
| 2 | 기존 STOW-RS/CD Import/Batch API 통합 래핑 |
| 3 | 승인 큐 DB + API + Admin 페이지 |

### Phase B: 외부 PACS 연동 (파일럿 필수)

| # | 작업 |
|---|------|
| 4 | dicom_remotes 테이블 + CRUD API |
| 5 | Orthanc 피어/모달리티 동기화 (Orthanc REST API 호출) |
| 6 | C-ECHO / C-FIND / C-MOVE API |
| 7 | 외부 연동 관리 Admin 페이지 |
| 8 | 전송 이력 |

### Phase C: 환자 포털 (규제 대응 후)

| # | 작업 |
|---|------|
| 9 | 토큰 발급 + 검증 + 동의 API |
| 10 | 환자 업로드 포털 페이지 (반응형) |
| 11 | JPEG → DICOM SC 변환 |
| 12 | 승인 워크플로우 연동 |

### Phase D: 키오스크 (병원 도입 시)

| # | 작업 |
|---|------|
| 13 | 키오스크 전용 페이지 (터치 UI) |
| 14 | 바코드 스캐너 연동 (HID) |
| 15 | 환자 자동 매칭 (HIS 조회) |
| 16 | 자동 라우팅 규칙 엔진 |

---

## 9. 비기능 요구사항

| 항목 | 요구사항 |
|------|---------|
| 파일 크기 | 단일 500MB, ZIP 2GB, 키오스크 CD 700MB |
| 동시 업로드 | 관리자 5건, 환자 포털 3건 병렬 |
| 청크 업로드 | 대용량 파일은 5MB 청크로 분할 (재시도 지원) |
| 진행률 | WebSocket 또는 SSE로 실시간 진행률 전송 |
| 중복 감지 | StudyInstanceUID + SOPInstanceUID 기반 중복 방지 |
| 임시 파일 | 72시간 후 자동 삭제 (Celery beat) |
| CORS | 환자 포털은 별도 오리진 허용 필요 |
| 접근성 | 키오스크는 WCAG 2.1 AA 수준 |

---

## 10. 위험 요소 및 대응

| 위험 | 영향 | 대응 |
|------|------|------|
| 환자가 타인 영상 업로드 | 환자 혼동 | 3중 본인확인 + 승인 큐 필수 |
| CD에 악성 파일 포함 | 보안 위협 | DICOM magic byte 검증 + 실행파일 차단 |
| 대용량 업로드로 서버 부하 | 서비스 장애 | 청크 업로드 + rate limit + 임시 저장소 분리 |
| 외부 PACS 연결 끊김 | 수신 실패 | 재시도 로직 + 알림 + 전송 이력 |
| 키오스크 PC 장애 | 환자 불편 | "직원 호출" 안내 + 원격 모니터링 |
| DICOMDIR 없는 CD | 파싱 실패 | 폴더 재귀 스캔으로 폴백 (.dcm 확장자 + magic byte) |
| 개인정보 동의 누락 | 법적 리스크 | 업로드 전 동의 단계 필수 (건너뛰기 불가) |
| UID 충돌 (외부 PACS → 우리 PACS) | 기존 영상 덮어쓰기 | UID 재매핑 옵션 + 충돌 감지 알림 |

---

## 11. 기대 효과

| 효과 | 설명 |
|------|------|
| **영상 수집 시간 단축** | CD 수작업 30분 → 키오스크 5분 |
| **환자 편의성** | 내원 전 미리 영상 업로드 → 대기 시간 단축 |
| **타 기관 연동** | Q/R로 실시간 영상 조회 → 전원/의뢰 시 즉시 영상 확보 |
| **연구 효율** | 드래그&드롭 배치 업로드 → 연구 데이터 수집 간소화 |
| **보안/감사** | 모든 경로의 업로드 이력 통합 관리 → 규제 대응 |
| **파일럿 대비** | 실제 병원에서 C-STORE 외 영상 수집 경로 확보 |
