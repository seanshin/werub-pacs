# DICOM 이슈 컨트롤 센터 기획서

> **버전**: v9.0  
> **작성일**: 2026-05-26  
> **우선순위**: P0 (운영 필수)  
> **예상 API**: 18개 신규 + 4개 수정  
> **예상 Admin 페이지**: 2개 신규 (`/pacs-admin/dicom-issues`, `/pacs-admin/dicom-issues/settings`)

---

## 1. 배경 및 문제 정의

### 1.1 현재 상황

OpenPACS는 DICOM 파일 검증(validation), 비표준 감지, 정규화(normalization) 엔진을 이미 보유하고 있으나, **이슈 발생 현황을 한눈에 보고 대응할 수 있는 관리 화면**이 없다.

현재 분산된 기능들:
- `DicomValidator` (dicom_validator.py): **19개** 규칙으로 검증 (JPEG 밀도, 필수 태그, UID 형식 등)
- `dicom-renderability.ts`: 비렌더링 모달리티 감지 (SR, PR, KO 등) — **하드코딩**
- `ValidationResult` / `ValidationSummary` (models/validation.py): **DB 모델 정의되어 있으나 실제 데이터가 저장되지 않음** (현재 validate API는 Redis 캐시만 사용)
- `NormalizationReview` (models/batch_job.py): 중위험 변경사항 리뷰 큐 (normalization 페이지에 종속)
- `qc-dashboard` (system_admin.py): 기초 통계만 제공 (심각도/AE Title/카테고리별 집계), **개별 이슈 조회/상태 관리 불가**
- 에러 메시지가 코드에 하드코딩되어 변경 불가
- 정규화 페이지(normalization/page.tsx): 8개 알고리즘 설정이 **프론트엔드 로컬 상태에만 존재** (DB 미저장)

### 1.2 코드 현황 분석 (실사 기반)

#### 검증 파이프라인의 단절

```
현재 흐름:
POST /validation/validate → DicomValidator.validate() → Redis 캐시 (24h TTL)
                                                         └─ ValidationResult 테이블에 저장 안 됨 ❌

원래 의도:
POST /validation/validate → DicomValidator → ValidationResult 테이블 저장 → 조회/관리 UI
                                           → ValidationSummary 테이블 저장
```

- `ValidationResult` 모델에 `sop_instance_uid`, `severity`, `rule_code`, `ae_title` 등 필드와 인덱스가 정의됨
- `system_admin.py`의 `qc-dashboard`가 `ValidationResult` 테이블을 조회하지만, **데이터가 저장되지 않으므로 항상 빈 결과**
- 이 기획의 **Phase A 전제 조건**: validate API가 결과를 DB에 저장하도록 수정 필요

#### DicomValidator 실제 규칙 목록 (19개)

코드에서 확인된 전체 `rule_code`:

| # | rule_code | 심각도 | 카테고리 | 소스 함수 |
|---|-----------|--------|---------|-----------|
| 1 | `PARSE_FAILURE` | CRITICAL | METADATA | validate() |
| 2 | `MISSING_MANDATORY_TAG` | CRITICAL | METADATA | _check_mandatory_tags() |
| 3 | `EMPTY_MANDATORY_TAG` | ERROR | METADATA | _check_mandatory_tags() |
| 4 | `MISSING_RECOMMENDED_TAG` | WARNING | METADATA | _check_recommended_tags() |
| 5 | `UID_TOO_LONG` | ERROR | UID | _check_uid_format() |
| 6 | `UID_INVALID_CHARS` | ERROR | UID | _check_uid_format() |
| 7 | `MISSING_CHARACTER_SET` | ERROR | CHARACTER_SET | _check_character_set() |
| 8 | `UNKNOWN_CHARACTER_SET` | WARNING | CHARACTER_SET | _check_character_set() |
| 9 | `INVALID_DATE_FORMAT` | WARNING | METADATA | _check_vr_conformance() |
| 10 | `INVALID_IS_VALUE` | WARNING | METADATA | _check_vr_conformance() |
| 11 | `MISSING_FILE_META` | ERROR | TRANSFER_SYNTAX | _check_transfer_syntax() |
| 12 | `MISSING_TRANSFER_SYNTAX` | ERROR | TRANSFER_SYNTAX | _check_transfer_syntax() |
| 13 | `BITS_STORED_GT_ALLOCATED` | ERROR | PIXEL_DATA | _check_transfer_syntax() |
| 14 | `UNKNOWN_PHOTOMETRIC` | WARNING | PIXEL_DATA | _check_pixel_data() |
| 15 | `MISSING_IMAGE_DIMENSIONS` | ERROR | PIXEL_DATA | _check_pixel_data() |
| 16 | `JPEG_DENSITY_MISMATCH` | WARNING→ERROR | JPEG | _check_jpeg_density() |
| 17 | `JPEG_DENSITY_NO_PIXEL_SPACING` | WARNING | JPEG | _check_jpeg_density() |
| 18 | `JPEG_DEFAULT_DENSITY` | INFO | JPEG | _check_jpeg_density() |
| 19 | `JPEG_NONSQUARE_ASPECT` | WARNING | JPEG | _check_jpeg_density() |
| 20 | `PRIVATE_TAGS_PRESENT` | INFO | METADATA | _check_private_tags() |

※ `NON_RENDERABLE_ONLY`, `INVALID_STUDY_UID`는 프론트엔드 전용 규칙 (백엔드 Validator에 없음)

#### 기존 정규화 페이지와의 관계

| 항목 | 정규화 페이지 (`/normalization`) | DICOM 이슈 센터 (신규) |
|------|------|------|
| 목적 | 비표준 DICOM 자동 보정 | 이슈 감지·모니터링·규칙 제어 |
| 대상 | 배치 업로드 파일 | 모든 수신 DICOM (실시간 + 배치) |
| 알고리즘 | 8개 정규화 알고리즘 (프론트 하드코딩) | 20개 검증 규칙 (DB 저장) |
| 상태 관리 | 없음 | 이슈별 상태 추적 (미확인→확인→처리) |
| 메시지 제어 | 없음 | 에러 메시지 편집 |
| 통계 | 기본 배치 통계 | 트렌드, 장비별, 규칙별 |
| **관계** | → **Phase C에서 이 센터에 통합** | 정규화 설정도 DB로 이관 |

#### 제조사별 정규화기 (SupplierNormalizer)

`supplier_normalizer.py`에 3개 제조사 정규화기 구현:
- `SiemensNormalizer`: Siemens 전용 비표준 보정
- `GENormalizer`: GE 전용 보정
- `PhilipsNormalizer`: Philips 전용 보정
- `get_normalizer_for_supplier()`: 제조사 자동 감지 팩토리

→ 장비 프로필의 `normalization_preset`과 연동 필요

### 1.3 실무에서 발생하는 문제

| 문제 | 영향 | 근본 원인 |
|------|------|----------|
| CT+SR 복합 스터디가 "영상 표시 불가"로 오분류 | 판독의가 영상을 못 열거나 혼란 | 복합 모달리티 미처리 (v8.8.2에서 수정됨) |
| JPEG 밀도 조작된 영상이 조용히 통과 | **측정값 오류** → 진단 위험 | 검증 결과가 DB에 저장 안 됨 → 추적 불가 |
| 비표준 UID 스터디가 뷰어에서 안 열림 | 판독 지연 | 프론트엔드에서만 감지, 수신 시점에 차단/알림 없음 |
| 제조사별 비표준 패턴이 반복되나 통계 없음 | 대응 전략 수립 불가 | qc-dashboard 데이터 비어있음 |
| 에러 메시지가 하드코딩 → 수정하려면 배포 필요 | 운영 유연성 저하 | dicom-renderability.ts 하드코딩 |
| 정규화 알고리즘 설정이 DB에 없음 | 새로고침하면 초기화 | normalization 페이지 로컬 상태만 사용 |
| 검증·정규화가 수동 업로드 시에만 실행 | C-STORE 수신 영상은 미검증 | 자동 검증 트리거 없음 |

### 1.4 해결 목표

**관리자가 DICOM 이슈를 실시간 모니터링하고, 규칙·메시지·대응 방식을 코드 수정 없이 제어**할 수 있는 통합 관리 화면을 구축한다.

추가 목표:
- 검증 결과를 DB에 영속 저장하여 이력 추적 가능
- 기존 `qc-dashboard`를 대체하는 풍부한 이슈 조회 UI 제공
- C-STORE 수신 시 자동 검증 → 실시간 이슈 감지
- 정규화 설정을 DB 기반으로 전환 (프론트 하드코딩 제거)

---

## 2. 기능 범위

### 2.1 DICOM 이슈 대시보드 (`/pacs-admin/dicom-issues`)

실시간으로 DICOM 파일의 검증 결과와 이슈 현황을 조회·관리하는 메인 화면.

#### 2.1.1 이슈 현황 요약 카드

| 카드 | 표시 내용 | 색상 |
|------|----------|------|
| CRITICAL | 즉시 조치 필요 건수 (JPEG 밀도 불일치, 필수 태그 누락) | 빨강 |
| ERROR | 오류 건수 (빈 필수 태그, UID 형식 오류, 문자셋 누락) | 주황 |
| WARNING | 경고 건수 (권장 태그 누락, 경미한 밀도 차이) | 노랑 |
| INFO | 정보 건수 (사설 태그 감지, 기본 밀도) | 파랑 |
| 총 스터디 | 전체 스터디 수 / 이슈 있는 스터디 수 | 회색 |
| 자동 수정 | 자동 정규화로 해결된 건수 / 비율 | 초록 |

#### 2.1.2 이슈 목록 테이블

| 컬럼 | 설명 |
|------|------|
| 심각도 | CRITICAL / ERROR / WARNING / INFO (배지) |
| 규칙 코드 | `JPEG_DENSITY_MISMATCH`, `MISSING_MANDATORY_TAG` 등 |
| 환자 | 환자명 + ID |
| 스터디 | Study Description + Date |
| 모달리티 | CT, MR 등 (ModalityBadge) |
| AE Title | 영상 전송 장비명 |
| 카테고리 | METADATA / PIXEL_DATA / JPEG / UID / CHARACTER_SET |
| 메시지 | 이슈 설명 (관리자가 커스텀 가능) |
| 상태 | 미확인 / 확인됨 / 무시 / 자동수정 / 수동수정 |
| 발생일 | 최초 감지 시점 |
| 액션 | 상세보기 / 뷰어열기 / 상태변경 / 재검증 |

**필터**:
- 심각도 (멀티 셀렉트)
- 카테고리
- 규칙 코드
- 상태 (미확인 / 확인됨 / 무시 / 수정됨)
- 기간 (오늘 / 7일 / 30일 / 전체)
- AE Title (장비별 필터링)
- 모달리티

**정렬**: 심각도 > 발생일 기본, 클릭 정렬 지원

#### 2.1.3 이슈 상세 모달

특정 이슈 클릭 시 표시:
- DICOM 태그 전체 목록 (문제 태그 하이라이트)
- JPEG 밀도 이슈의 경우: Pixel Spacing vs JFIF Density 비교 표
- 관련 시리즈/인스턴스 목록
- 정규화 적용 이력 (적용 전/후 값)
- 관리자 메모 입력 필드
- 상태 변경 드롭다운

#### 2.1.4 통계 차트

- **이슈 트렌드**: 일별/주별 이슈 발생 추이 (라인 차트)
- **규칙별 분포**: 어떤 규칙 위반이 가장 많은지 (바 차트)
- **장비(AE Title)별 분포**: 문제가 많은 장비 식별 (바 차트)
- **자동 수정율**: 정규화 자동 해결 비율 (도넛 차트)

---

### 2.2 이슈 규칙 설정 (`/pacs-admin/dicom-issues/settings`)

검증 규칙의 활성화/비활성화, 심각도 조정, 에러 메시지 편집을 관리하는 설정 화면.

#### 2.2.1 검증 규칙 관리

| 설정 항목 | 설명 |
|----------|------|
| 규칙 코드 | `MISSING_MANDATORY_TAG`, `JPEG_DENSITY_MISMATCH` 등 (읽기 전용) |
| 규칙 이름 | 관리자가 편집 가능한 표시명 |
| 카테고리 | METADATA / PIXEL_DATA / JPEG / UID / CHARACTER_SET / TRANSFER_SYNTAX |
| 활성화 토글 | 규칙을 끄면 해당 검증을 건너뜀 |
| 심각도 | CRITICAL / ERROR / WARNING / INFO (드롭다운으로 변경 가능) |
| 기본 메시지 | 코드에 정의된 원본 메시지 (읽기 전용, 참조용) |
| 커스텀 메시지 | 관리자가 입력한 메시지 (비어있으면 기본 메시지 사용) |
| 자동 조치 | `none` / `normalize` / `quarantine` / `reject` |
| 임계값 | 규칙별 파라미터 (예: JPEG 밀도 차이 5%/20% 임계값 조정) |

**기본 제공 규칙 — 백엔드 DicomValidator (20개)**:

| # | 코드 | 기본 심각도 | 카테고리 | 설명 | 수정 가능 |
|---|------|-----------|---------|------|----------|
| 1 | `PARSE_FAILURE` | CRITICAL | METADATA | DICOM 파싱 실패 | 심각도 잠금 |
| 2 | `MISSING_MANDATORY_TAG` | CRITICAL | METADATA | 필수(Type 1) 태그 누락 | 심각도 잠금 |
| 3 | `EMPTY_MANDATORY_TAG` | ERROR | METADATA | 필수 태그 값 비어있음 | O |
| 4 | `MISSING_RECOMMENDED_TAG` | WARNING | METADATA | 권장(Type 2) 태그 누락 | O |
| 5 | `UID_TOO_LONG` | ERROR | UID | UID 64자 초과 | O |
| 6 | `UID_INVALID_CHARS` | ERROR | UID | UID에 비표준 문자 포함 | O |
| 7 | `MISSING_CHARACTER_SET` | ERROR | CHARACTER_SET | 비ASCII 데이터에 문자셋 태그 없음 | O |
| 8 | `UNKNOWN_CHARACTER_SET` | WARNING | CHARACTER_SET | 지원되지 않는 문자셋 | O |
| 9 | `INVALID_DATE_FORMAT` | WARNING | METADATA | DA(날짜) 형식 비표준 (YYYYMMDD 아님) | O |
| 10 | `INVALID_IS_VALUE` | WARNING | METADATA | IS(정수 문자열) VR에 정수 아닌 값 | O |
| 11 | `MISSING_FILE_META` | ERROR | TRANSFER_SYNTAX | File Meta Information 누락 | O |
| 12 | `MISSING_TRANSFER_SYNTAX` | ERROR | TRANSFER_SYNTAX | Transfer Syntax UID 누락 | O |
| 13 | `BITS_STORED_GT_ALLOCATED` | ERROR | PIXEL_DATA | BitsStored > BitsAllocated 불일치 | O |
| 14 | `UNKNOWN_PHOTOMETRIC` | WARNING | PIXEL_DATA | 알 수 없는 Photometric Interpretation | O |
| 15 | `MISSING_IMAGE_DIMENSIONS` | ERROR | PIXEL_DATA | 픽셀 데이터 있으나 Rows/Columns 누락 | O |
| 16 | `JPEG_DENSITY_MISMATCH` | WARNING→ERROR | JPEG | JFIF 밀도 vs Pixel Spacing 차이 | O (임계값: 5%/20%) |
| 17 | `JPEG_DENSITY_NO_PIXEL_SPACING` | WARNING | JPEG | JPEG에 밀도 있으나 Pixel Spacing 태그 없음 | O |
| 18 | `JPEG_DEFAULT_DENSITY` | INFO | JPEG | 기본 1×1 DPI 밀도 (플레이스홀더) | O |
| 19 | `JPEG_NONSQUARE_ASPECT` | WARNING | JPEG | 비정방 JPEG 종횡비 | O |
| 20 | `PRIVATE_TAGS_PRESENT` | INFO | METADATA | 제조사 사설 태그 감지 | O |

**프론트엔드 전용 규칙 (2개, DB 시딩만):**

| # | 코드 | 심각도 | 설명 | 용도 |
|---|------|--------|------|------|
| 21 | `NON_RENDERABLE_ONLY` | WARNING | 스터디에 렌더링 가능 시리즈 없음 | 판독 큐 경고 배지 |
| 22 | `INVALID_STUDY_UID` | ERROR | Study UID 형식 오류 (뷰어 표시 불가) | ViewerButton 경고 |

#### 2.2.2 모달리티 렌더링 설정

비렌더링 모달리티 목록과 에러 메시지를 관리자가 편집 가능:

| 설정 | 설명 |
|------|------|
| 비렌더링 모달리티 목록 | 현재: RTSTRUCT, RTPLAN, RTDOSE, SR, PR, KO, ANN (추가/제거 가능) |
| 부분 렌더링 모달리티 | 현재: SEG (추가/제거 가능) |
| 모달리티별 표시명 | 한국어 라벨 편집 (예: "구조화 리포트") |
| 모달리티별 안내 메시지 | 경고 모달에 표시되는 설명문 편집 |
| 모달리티별 조치 안내 | "판독 리포트에서 내용을 확인하세요" 등 편집 |
| 복합 모달리티 정책 | `any_renderable` (기본, 하나라도 영상이면 표시) / `strict` (모두 렌더링 가능해야) |

#### 2.2.3 에러 메시지 템플릿

뷰어/판독 화면에서 사용자에게 보여주는 에러 메시지를 통합 관리:

| 메시지 키 | 용도 | 기본값 |
|----------|------|--------|
| `viewer.non_renderable.title` | 경고 모달 제목 | "영상 표시 불가" |
| `viewer.non_renderable.description` | 경고 모달 설명 | "{modality_label}(으)로, 영상 데이터가..." |
| `viewer.non_renderable.action_open` | 그래도 열기 버튼 | "그래도 열기" |
| `viewer.invalid_uid.title` | UID 오류 제목 | "비표준 Study UID" |
| `viewer.invalid_uid.description` | UID 오류 설명 | "DICOM 표준 UID 형식이 아니어서..." |
| `validation.critical.title` | 검증 실패 알림 | "DICOM 검증 실패" |
| `validation.jpeg_density` | JPEG 밀도 경고 | "JPEG 밀도와 Pixel Spacing이 {diff}% 차이..." |
| `queue.non_renderable_badge` | 판독 큐 배지 툴팁 | "영상 표시 불가 모달리티" |

- **변수 지원**: `{modality}`, `{modality_label}`, `{diff}`, `{tag_name}`, `{ae_title}` 등
- **미리보기**: 편집 시 실제 메시지가 어떻게 표시되는지 즉시 프리뷰
- **초기화 버튼**: 기본값으로 되돌리기

---

### 2.3 자동 대응 정책

검증 규칙별로 자동 조치를 설정:

| 조치 | 동작 |
|------|------|
| `none` | 이슈만 기록, 별도 조치 없음 |
| `normalize` | 자동 정규화 시도 (DicomNormalizer 호출) |
| `quarantine` | 격리 큐로 이동 (관리자 확인 대기) |
| `reject` | 저장 거부 + 전송 측에 에러 응답 |
| `alert` | 알림 발송 (WebSocket + Email) + 이슈 기록 |

---

### 2.4 장비(AE Title) 프로필

반복적으로 비표준 영상을 보내는 장비를 프로필로 관리:

| 항목 | 설명 |
|------|------|
| AE Title | DICOM 전송 장비의 Application Entity Title |
| 장비명 | 관리자 입력 별칭 (예: "2층 CT", "응급실 X-ray") |
| 제조사 | 자동 감지 또는 수동 입력 (Siemens, GE, Philips 등) |
| 누적 이슈 | 이 장비에서 발생한 이슈 수/심각도별 분포 |
| 커스텀 규칙 | 특정 장비에만 적용되는 규칙 오버라이드 |
| 마지막 전송 | 가장 최근 DICOM 수신 시점 |
| 정규화 프리셋 | 이 장비 영상에 항상 적용할 정규화 설정 |

---

## 3. 데이터 모델

### 3.1 신규 테이블

```sql
-- 검증 규칙 설정 (관리자 커스터마이즈)
CREATE TABLE dicom_issue_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_code VARCHAR(64) UNIQUE NOT NULL,       -- 'MISSING_MANDATORY_TAG'
    display_name VARCHAR(128) NOT NULL,           -- 관리자 편집 가능
    category VARCHAR(32) NOT NULL,                -- METADATA, JPEG, UID 등
    default_severity VARCHAR(16) NOT NULL,        -- 코드 기본값
    severity VARCHAR(16) NOT NULL,                -- 관리자 조정값
    enabled BOOLEAN DEFAULT TRUE,
    default_message TEXT NOT NULL,                 -- 코드 기본 메시지
    custom_message TEXT,                           -- 관리자 커스텀 (null이면 기본 사용)
    auto_action VARCHAR(16) DEFAULT 'none',       -- none/normalize/quarantine/reject/alert
    thresholds JSONB DEFAULT '{}',                -- 규칙별 파라미터
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 모달리티 렌더링 설정
CREATE TABLE modality_render_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    modality VARCHAR(16) UNIQUE NOT NULL,         -- 'SR', 'RTSTRUCT' 등
    render_type VARCHAR(16) NOT NULL,             -- 'non_renderable', 'partial', 'renderable'
    display_label VARCHAR(64) NOT NULL,           -- '구조화 리포트'
    description TEXT NOT NULL,                     -- 경고 모달 설명
    action_text TEXT,                              -- 조치 안내
    enabled BOOLEAN DEFAULT TRUE,
    sort_order INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 에러 메시지 템플릿
CREATE TABLE dicom_message_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_key VARCHAR(128) UNIQUE NOT NULL,     -- 'viewer.non_renderable.title'
    context VARCHAR(32) NOT NULL,                  -- 'viewer', 'validation', 'queue'
    default_text TEXT NOT NULL,
    custom_text TEXT,                               -- null이면 기본 사용
    variables TEXT[],                               -- ['{modality}', '{diff}']
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 장비 프로필
CREATE TABLE ae_title_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ae_title VARCHAR(64) UNIQUE NOT NULL,
    display_name VARCHAR(128),                     -- 관리자 별칭
    manufacturer VARCHAR(64),                      -- 자동 감지 또는 수동
    model_name VARCHAR(128),
    issue_count INT DEFAULT 0,
    issue_summary JSONB DEFAULT '{}',              -- {critical: 0, error: 0, ...}
    rule_overrides JSONB DEFAULT '{}',             -- 장비별 규칙 오버라이드
    normalization_preset JSONB DEFAULT '{}',       -- 항상 적용할 정규화
    last_received_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 이슈 상태 추적 (기존 ValidationResult 확장)
-- validation_results 테이블에 컬럼 추가:
--   issue_status VARCHAR(16) DEFAULT 'unreviewed'  -- unreviewed/acknowledged/ignored/auto_fixed/manual_fixed
--   reviewer_id UUID REFERENCES users(id)
--   reviewer_note TEXT
--   reviewed_at TIMESTAMPTZ
```

### 3.2 기존 테이블 수정

| 테이블 | 변경 | 이유 |
|--------|------|------|
| `validation_results` | +`issue_status`, +`reviewer_id`, +`reviewer_note`, +`reviewed_at` | 이슈 상태 관리 |

---

## 4. API 설계

### 4.1 신규 API (18개)

**이슈 조회/관리 (6개)**:

| # | Method | Endpoint | 설명 | 권한 |
|---|--------|----------|------|------|
| 1 | GET | `/api/v1/dicom-issues` | 이슈 목록 (필터/페이지네이션/정렬) | ADMIN, RADIOLOGIST (읽기) |
| 2 | GET | `/api/v1/dicom-issues/{id}` | 이슈 상세 (DICOM 태그 포함) | ADMIN, RADIOLOGIST |
| 3 | PATCH | `/api/v1/dicom-issues/{id}/status` | 이슈 상태 변경 (확인/무시/수정) | ADMIN |
| 4 | POST | `/api/v1/dicom-issues/{id}/revalidate` | 재검증 실행 (Orthanc에서 원본 조회 → DicomValidator) | ADMIN |
| 5 | GET | `/api/v1/dicom-issues/statistics` | 이슈 통계 (기존 qc-dashboard 대체) | ADMIN |
| 6 | GET | `/api/v1/dicom-issues/trends` | 이슈 트렌드 (일별/주별, 기간 파라미터) | ADMIN |

**규칙/설정 관리 (6개)**:

| # | Method | Endpoint | 설명 | 권한 |
|---|--------|----------|------|------|
| 7 | GET | `/api/v1/dicom-issues/rules` | 검증 규칙 목록 | ADMIN |
| 8 | PUT | `/api/v1/dicom-issues/rules/{rule_code}` | 규칙 설정 수정 (심각도, 활성화, 메시지, 조치, 임계값) | ADMIN |
| 9 | POST | `/api/v1/dicom-issues/rules/reset` | 전체 규칙 기본값 복원 | ADMIN |
| 10 | GET | `/api/v1/dicom-issues/modality-config` | 모달리티 렌더링 설정 조회 (프론트엔드 동적 로드용, 인증 불필요) | 공개 |
| 11 | PUT | `/api/v1/dicom-issues/modality-config/{modality}` | 모달리티 설정 수정 | ADMIN |
| 12 | POST | `/api/v1/dicom-issues/modality-config` | 모달리티 설정 추가 | ADMIN |

**메시지/장비/내보내기 (6개)**:

| # | Method | Endpoint | 설명 | 권한 |
|---|--------|----------|------|------|
| 13 | GET | `/api/v1/dicom-issues/messages` | 에러 메시지 템플릿 목록 (프론트엔드 동적 로드용) | 공개 |
| 14 | PUT | `/api/v1/dicom-issues/messages/{key}` | 메시지 템플릿 수정 | ADMIN |
| 15 | GET | `/api/v1/dicom-issues/ae-profiles` | 장비 프로필 목록 | ADMIN |
| 16 | PUT | `/api/v1/dicom-issues/ae-profiles/{ae_title}` | 장비 프로필 수정 (별칭, 규칙 오버라이드, 정규화 프리셋) | ADMIN |
| 17 | GET | `/api/v1/dicom-issues/export` | 설정 전체 내보내기 (JSON) | ADMIN |
| 18 | POST | `/api/v1/dicom-issues/import` | 설정 가져오기 (JSON) | ADMIN |

### 4.2 수정 API (4개)

| # | Endpoint | 변경 | 영향 |
|---|----------|------|------|
| 1 | `POST /api/v1/validation/validate` | **결과를 ValidationResult/ValidationSummary 테이블에 저장** + 규칙 설정 DB 조회 → 활성 규칙만 실행, 커스텀 심각도/메시지 적용 | 핵심 변경 — 현재 Redis 캐시만 하는 것을 DB 영속 저장으로 |
| 2 | `POST /api/v1/validation/validate-batch` | 동일 (규칙 설정 반영 + DB 저장) | 배치 검증도 이력 남김 |
| 3 | `GET /api/v1/dashboard/reading-queue` | 모달리티 렌더링 설정을 DB에서 조회 (하드코딩 대체) | 프론트엔드 폴백 유지 |
| 4 | `GET /api/v1/system/qc-dashboard` | deprecated 표시, `/dicom-issues/statistics`로 리다이렉트 | 하위 호환 |

### 4.3 자동 검증 트리거 (신규 연동)

현재 DicomValidator는 **수동 업로드 시에만** 실행됨. C-STORE로 수신된 영상도 자동 검증하려면:

```
방법 1: Orthanc Lua/Python 플러그인 (권장)
  OnStableStudy() → POST /api/v1/validation/validate-study/{orthanc_id}
  
방법 2: Celery 주기 작업
  5분마다 미검증 스터디 스캔 → DicomValidator 실행 → DB 저장

방법 3: Orthanc Change Callback
  Orthanc REST /changes API 폴링 → 새 인스턴스 감지 → 검증
```

→ Phase C에서 방법 2(Celery beat) 구현 (기존 celery-beat 컨테이너 활용)

---

## 5. UI 설계

### 5.1 네비게이션 위치

```
관리 (우측 메뉴)
├── 대시보드
├── 사용자
├── ...
├── 정규화          ← 기존
├── DICOM 이슈      ← 신규 (아이콘: ⚠️)
│   ├── 이슈 현황   ← 기본 탭
│   └── 규칙 설정   ← 설정 탭
├── 아카이브
└── ...
```

### 5.2 이슈 현황 화면 와이어프레임

```
┌─────────────────────────────────────────────────────────────────┐
│ DICOM 이슈 컨트롤 센터                          [규칙 설정] [↻] │
├─────────────────────────────────────────────────────────────────┤
│ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐         │
│ │ 🔴 3 │ │ 🟠 12│ │ 🟡 28│ │ 🔵 45│ │ 📊120│ │ ✅ 85%│        │
│ │CRITICAL│ ERROR│ │WARNING│ │ INFO │ │총스터디│ │자동수정│       │
│ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘         │
├─────────────────────────────────────────────────────────────────┤
│ 필터: [심각도 ▾] [카테고리 ▾] [상태 ▾] [기간 ▾] [AE Title ▾]   │
│       [검색: 환자명/ID/설명...]                                  │
├────┬──────┬──────┬────────┬──────┬──────┬──────┬──────┬────────┤
│심각│규칙    │환자   │스터디    │모달  │AE     │상태   │발생일  │액션    │
├────┼──────┼──────┼────────┼──────┼──────┼──────┼──────┼────────┤
│ 🔴 │JPEG  │홍길동  │Chest CT │ CT  │CT_ER │미확인 │05-26 │[상세]  │
│    │DENSITY│       │         │     │      │      │      │[뷰어]  │
├────┼──────┼──────┼────────┼──────┼──────┼──────┼──────┼────────┤
│ 🟠 │MISSING│김영희 │Brain MR │ MR  │MR_2F │확인됨 │05-25 │[상세]  │
│    │TAG   │       │         │     │      │      │      │[재검증]│
└────┴──────┴──────┴────────┴──────┴──────┴──────┴──────┴────────┘
│ ◀ 1 2 3 ... 10 ▶                              20건/페이지 ▾    │
├─────────────────────────────────────────────────────────────────┤
│ 📊 통계                                                         │
│ ┌─────────────────────┐ ┌─────────────────────┐                │
│ │ 이슈 트렌드 (7일)    │ │ 장비별 이슈 분포     │                │
│ │ ▁▂▃▅▇▆▄ (라인차트)   │ │ ████ CT_ER          │                │
│ │                     │ │ ██ MR_2F             │                │
│ └─────────────────────┘ └─────────────────────┘                │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 규칙 설정 화면 와이어프레임

```
┌─────────────────────────────────────────────────────────────────┐
│ DICOM 이슈 규칙 설정                           [← 이슈 현황]    │
├─────────────────────────────────────────────────────────────────┤
│ [검증 규칙] [모달리티 설정] [에러 메시지]     ← 3탭             │
├─────────────────────────────────────────────────────────────────┤
│                        ── 검증 규칙 탭 ──                        │
├────┬────────┬──────┬──────┬──────┬──────────┬──────┬───────────┤
│활성│규칙 코드 │표시명 │카테고리│심각도 │자동 조치  │임계값 │커스텀 메시지│
├────┼────────┼──────┼──────┼──────┼──────────┼──────┼───────────┤
│ ✅ │JPEG_   │JPEG  │JPEG  │[WARN▾│[normalize│[5/20]│[편집]     │
│    │DENSITY │밀도   │      │     ]│    ▾]    │  %   │           │
├────┼────────┼──────┼──────┼──────┼──────────┼──────┼───────────┤
│ ✅ │MISSING_│필수   │META  │[CRIT▾│[reject ▾]│ -    │[편집]     │
│    │MANDATORY│태그  │DATA  │     ]│          │      │           │
├────┼────────┼──────┼──────┼──────┼──────────┼──────┼───────────┤
│ ⬜ │PRIVATE_│사설   │META  │[INFO▾│[none   ▾]│ -    │[편집]     │
│    │TAGS   │태그   │DATA  │     ]│          │      │           │
└────┴────────┴──────┴──────┴──────┴──────────┴──────┴───────────┘
│                                              [기본값 복원] [저장]│
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. 프론트엔드 연동 흐름

### 6.1 모달리티 렌더링 설정 동적 로드

현재 `dicom-renderability.ts`에서 하드코딩된 `NON_RENDERABLE_MODALITIES`를 **API에서 로드**하도록 변경:

```
앱 로드 → GET /api/v1/dicom-issues/modality-config → 캐시 (5분 TTL)
         ↓
ViewerButton / ReadingQueue에서 동적 참조
```

### 6.2 에러 메시지 동적 로드

```
앱 로드 → GET /api/v1/dicom-issues/messages → 캐시 (5분 TTL)
         ↓
ViewerButton 경고 모달에서 메시지 키로 조회 → 변수 치환 → 표시
```

### 6.3 검증 결과 실시간 알림

```
DICOM 수신 → DicomValidator 실행 → CRITICAL/ERROR 발견
  ↓
WebSocket 알림 → 🔔 벨 아이콘 배지 증가
  ↓
관리자 클릭 → DICOM 이슈 페이지로 이동
```

---

## 7. 구현 우선순위

### Phase A: 데이터 파이프라인 + 핵심 조회 (전제 조건)

**목표**: 검증 결과가 DB에 쌓이고, 조회할 수 있는 기본 화면

| # | 작업 | 상세 |
|---|------|------|
| 1 | DB 스키마 생성 (4 테이블 + 1 ALTER) | dicom_issue_rules, modality_render_config, dicom_message_templates, ae_title_profiles + validation_results ALTER |
| 2 | **validate API → DB 저장 연동** | 현재 Redis 캐시만 → ValidationResult/Summary 테이블에도 저장 |
| 3 | 규칙/모달리티/메시지 초기 데이터 시딩 | 20개 규칙 + 9개 모달리티 + 8개 메시지 |
| 4 | 이슈 조회 API 6개 (목록, 상세, 상태변경, 재검증, 통계, 트렌드) | 기존 qc-dashboard 대체 |
| 5 | 이슈 현황 페이지 (통계 카드 + 목록 테이블 + 필터) | `/pacs-admin/dicom-issues` |
| 6 | 이슈 상세 모달 (태그 목록, JPEG 비교, 메모, 상태 변경) | - |

### Phase B: 설정 관리 UI

**목표**: 관리자가 규칙·모달리티·메시지를 코드 수정 없이 제어

| # | 작업 | 상세 |
|---|------|------|
| 7 | 규칙/모달리티/메시지 설정 API 6개 | CRUD + reset |
| 8 | 규칙 설정 탭 (토글, 심각도, 자동 조치, 임계값, 메시지 편집) | CRITICAL 규칙 비활성화 시 확인 모달 |
| 9 | 모달리티 설정 탭 (렌더링 유형, 라벨, 설명, 복합 모달리티 정책) | - |
| 10 | 에러 메시지 템플릿 탭 (편집 + 변수 치환 미리보기) | - |
| 11 | 프론트엔드 동적 로드: `dicom-renderability.ts` API 연동 | 하드코딩 → API 로드 + 5분 캐시 + 폴백 |
| 12 | 프론트엔드 동적 로드: ViewerButton 메시지 API 연동 | - |

### Phase C: 자동화 + 고급 기능

**목표**: C-STORE 수신 시 자동 검증, 장비 관리, 정규화 통합

| # | 작업 | 상세 |
|---|------|------|
| 13 | **DicomValidator 수정**: 규칙 DB 연동 (활성 규칙만 실행, 커스텀 심각도/메시지) | 현재 하드코딩 → DB 조회 |
| 14 | **Celery beat 자동 검증**: 미검증 스터디 주기 스캔 → 자동 검증 | 기존 celery-beat 컨테이너에 태스크 추가 |
| 15 | 장비(AE Title) 프로필 관리 (API 2개 + UI) | 자동 프로필 생성 + 제조사 감지 + SupplierNormalizer 연동 |
| 16 | 통계 차트 (트렌드 라인, 장비별 바, 자동수정율 도넛) | - |
| 17 | 실시간 알림 연동 (CRITICAL/ERROR → WebSocket + 알림 벨) | 기존 alert_service.py 활용 |
| 18 | 설정 export/import (JSON) | 다기관 확장 대비 |
| 19 | 기존 정규화 페이지 알고리즘 설정 → DB 이관 | 프론트 하드코딩 DEFAULT_ALGORITHMS 제거 |

---

## 8. 비기능 요구사항

| 항목 | 요구사항 |
|------|---------|
| 성능 | 이슈 목록 조회 p95 < 200ms (인덱스 활용) |
| 캐시 | 규칙/모달리티/메시지 설정은 Redis 캐시 (5분 TTL, 설정 변경 시 즉시 무효화) |
| 권한 | ADMIN 역할만 설정 변경 가능, RADIOLOGIST는 이슈 조회만 |
| 감사 | 규칙 변경, 이슈 상태 변경 시 감사 로그 기록 |
| 호환 | 설정 export/import (JSON) 지원 — 다기관 확장 대비 |

---

## 9. 기대 효과

| 효과 | 설명 |
|------|------|
| **이슈 가시성** | 분산되어 있던 DICOM 이슈를 한 곳에서 모니터링 |
| **대응 시간 단축** | CRITICAL 이슈 실시간 알림 → 즉시 대응 |
| **운영 유연성** | 코드 배포 없이 규칙/메시지/심각도 조정 |
| **장비 관리** | 문제 장비 식별 → 제조사 연락/장비 설정 변경 |
| **규제 대응** | 검증 이력 + 감사 로그 → 의료기기 인증 시 근거 자료 |
| **오분류 방지** | CT+SR 같은 복합 모달리티 오분류 재발 방지 |

---

## 10. 위험 요소 및 대응

| 위험 | 영향 | 대응 |
|------|------|------|
| 설정 변경으로 CRITICAL 규칙 비활성화 | 위험 영상 통과 | `PARSE_FAILURE`, `MISSING_MANDATORY_TAG`는 심각도 잠금 + 비활성화 시 경고 모달 + 사유 입력 필수 |
| 대량 이슈 발생 시 DB 부하 | 조회 느려짐 | 90일 이전 이슈 자동 아카이브 + 기존 `ix_validation_severity_created` 인덱스 활용 |
| 메시지 변수 오입력 | 깨진 메시지 표시 | 미리보기 기능 + 저장 전 변수 유효성 검사 |
| 장비 AE Title 변경 | 프로필 단절 | AE Title 변경 감지 시 관리자 알림 |
| validate API에 DB 저장 추가 시 성능 저하 | 검증 응답 느려짐 | DB 저장은 비동기 (asyncio.create_task), 응답은 바로 반환 |
| 프론트엔드 API 로드 실패 시 모달리티 체크 불가 | 렌더링 판별 안 됨 | 기존 하드코딩 값을 폴백으로 유지 (API 실패 시 로컬 캐시 사용) |
| 정규화 페이지와 기능 중복 혼란 | 관리자 혼동 | 정규화 페이지에 "이슈 센터로 이동" 배너 표시, Phase C에서 설정 통합 |
| Celery 자동 검증으로 Orthanc 부하 | 영상 수신 성능 저하 | rate limiter 적용 (분당 최대 10건), 안정 스터디만 검증 |

---

## 11. 기존 시스템 영향 분석

| 기존 코드 | 변경 내용 | 하위 호환 |
|----------|----------|----------|
| `backend/app/api/validation.py` | DB 저장 로직 추가 | 기존 응답 형식 유지, 추가 필드만 |
| `backend/app/services/dicom_validator.py` | Phase C에서 규칙 DB 조회 추가 | 기본 동작 변경 없음 (DB 없으면 하드코딩 폴백) |
| `backend/app/api/system_admin.py` (qc-dashboard) | deprecated 표시 | 기존 API 유지, 새 API로 리다이렉트 |
| `admin/src/lib/dicom-renderability.ts` | API 로드 추가 | 하드코딩 폴백 유지 |
| `admin/src/components/ViewerButton.tsx` | 메시지 API 연동 | 폴백 유지 |
| `admin/src/app/normalization/page.tsx` | Phase C에서 알고리즘 설정 DB 이관 | 이관 전까지 현행 유지 |
| `backend/app/models/validation.py` | 4개 컬럼 ALTER ADD | 기존 데이터 없으므로 안전 |

---

## 12. 용어 정리

| 용어 | 정의 |
|------|------|
| **이슈** | DicomValidator가 감지한 개별 Finding (= validation_results 레코드 1건) |
| **규칙** | DicomValidator의 검증 항목 (rule_code로 식별, 예: JPEG_DENSITY_MISMATCH) |
| **자동 조치** | 이슈 발생 시 시스템이 자동 수행하는 동작 (none/normalize/quarantine/reject/alert) |
| **모달리티 렌더링 설정** | 각 DICOM 모달리티가 뷰어에서 표시 가능한지 여부 정의 |
| **장비 프로필** | AE Title 기반으로 특정 장비의 이슈 패턴과 대응 설정을 관리하는 단위 |
| **임계값** | 규칙별 수치 파라미터 (예: JPEG 밀도 차이 5%/20%) |
| **커스텀 메시지** | 관리자가 기본 메시지를 대체하여 입력한 에러/경고 문구 |
