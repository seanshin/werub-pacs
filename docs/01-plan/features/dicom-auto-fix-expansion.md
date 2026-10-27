# DICOM 자동수정 확대 기획서

> **버전**: v9.1  
> **작성일**: 2026-05-26  
> **선행 조건**: DICOM 이슈 컨트롤 센터 (v9.0) 구축 완료  
> **예상 API**: 5개 신규 + 4개 수정  
> **핵심 목표**: 수동 개입 없이 해결 가능한 이슈 비율을 현재 38% → 80% 이상으로 확대

---

## 1. 현재 상황 분석

### 1.1 현재 자동수정 현황 (v9.0)

| 구분 | 규칙 수 | 현재 상태 |
|------|---------|----------|
| 자동수정 가능 | 13 | `_apply_extra_fixes()` + `DicomNormalizer` |
| 자동수정 불가 | 9 | 안내 메시지만 표시 |
| **합계** | **22** | **자동수정률 38% (이슈 건수 기준)** |

### 1.2 실제 운영 데이터 (31개 스터디 스캔 결과)

```
34건 이슈 발생:
- MISSING_RECOMMENDED_TAG: 8건 → 자동수정 가능 ✅
- PRIVATE_TAGS_PRESENT:    8건 → 자동수정 가능 ✅ (v9.0에서 추가)
- EMPTY_MANDATORY_TAG:     5건 → 자동수정 가능 ✅
- MISSING_MANDATORY_TAG:   4건 → 자동수정 불가 ❌ (재전송 필요)
- INVALID_DATE_FORMAT:     3건 → 자동수정 가능 ✅
- UID_INVALID_CHARS:       3건 → 자동수정 가능 ✅ (v9.0에서 추가)
- MISSING_TRANSFER_SYNTAX: 3건 → 자동수정 가능 ✅

→ 자동수정 가능: 30/34 = 88% (건수 기준)
→ 자동수정 불가: 4/34 = 12% (MISSING_MANDATORY_TAG만)
```

### 1.3 해결해야 할 과제

| 과제 | 현상 | 영향 |
|------|------|------|
| **자동수정이 수동 트리거** | 관리자가 직접 버튼 클릭 필요 | 야간/주말 이슈 방치 |
| **제조사별 특화 수정 미연동** | Siemens/GE/Philips normalizer가 있으나 auto-fix에 미연동 | 제조사 고유 비표준 패턴 미처리 |
| **수정 전 원본 보관 없음** | 수정 후 원본 복구 불가 | 수정 오류 시 되돌리기 불가 |
| **수정 이력 추적 미흡** | fix_description에 텍스트만 저장 | 변경 전/후 비교 불가 |
| **연쇄 수정 미지원** | 하나 수정으로 다른 이슈도 해소될 수 있으나 개별 처리 | 불필요한 중복 처리 |
| **수신 시점 자동 검증/수정 없음** | DICOM C-STORE 수신 후 수동 스캔 필요 | 이슈 감지 지연 |

---

## 2. 확대 범위

### Phase 1: 자동 트리거 + 원본 보관 (핵심)

#### 2.1 C-STORE 수신 시 자동 검증 + 자동수정

```
DICOM C-STORE 수신
  ↓
Orthanc OnStableStudy 이벤트 (또는 Celery beat 5분 주기)
  ↓
DicomValidator 실행
  ↓
이슈 발견?
  ├─ No → 정상 (DB 저장 없음)
  └─ Yes → 규칙별 auto_action 확인
       ├─ none → 이슈만 DB 기록
       ├─ normalize → 자동수정 실행 → 재검증 → 해소되면 삭제
       ├─ alert → 이슈 기록 + WebSocket/Email 알림
       ├─ quarantine → 격리 큐로 이동 (관리자 확인 대기)
       └─ reject → Orthanc에서 삭제 + 전송측에 알림
```

**구현 방식**: 기존 `celery-beat` 컨테이너에 태스크 추가

```python
# tasks/dicom_auto_validate.py
@celery.task
def auto_validate_new_studies():
    """5분마다 미검증 스터디 스캔 → 규칙별 auto_action 실행."""
```

#### 2.2 원본 DICOM 보관 (수정 전 백업)

자동수정 전 원본을 보관하여 롤백 가능:

```sql
CREATE TABLE dicom_fix_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    validation_result_id UUID REFERENCES validation_results(id),
    study_instance_uid VARCHAR(128) NOT NULL,
    sop_instance_uid VARCHAR(128) NOT NULL,
    rule_code VARCHAR(64) NOT NULL,
    
    -- 변경 내역 (전/후)
    changes JSONB NOT NULL,           -- [{tag, original, corrected, rationale}]
    
    -- 원본 백업
    original_hash VARCHAR(64),        -- SHA256 of original file
    backup_orthanc_id VARCHAR(64),    -- Orthanc에 별도 저장된 원본 ID
    
    -- 수정 결과
    fix_status VARCHAR(16) NOT NULL,  -- applied, rolled_back, failed
    post_validation JSONB,            -- 재검증 결과 요약
    
    fixed_by UUID,
    fixed_at TIMESTAMPTZ DEFAULT NOW(),
    rolled_back_at TIMESTAMPTZ
);
```

**롤백 API**: `POST /api/v1/dicom-issues/rollback/{fix_history_id}`
- 백업된 원본을 Orthanc에 재업로드
- 현재 수정본 삭제
- fix_status → 'rolled_back'

---

### Phase 2: 제조사별 특화 자동수정

#### 2.3 SupplierNormalizer 연동

기존 `SiemensNormalizer`, `GENormalizer`, `PhilipsNormalizer`를 auto-fix 파이프라인에 통합:

```
auto-fix 요청
  ↓
제조사 자동 감지 (Manufacturer 태그)
  ↓
├─ SIEMENS → SiemensNormalizer.normalize()
│    ├─ Private tag (0019,1008) → PixelSpacing 추출
│    ├─ Private tag (0019,1010) → PhotometricInterpretation 추론
│    └─ InstanceCreationDate 보정
├─ GE → GENormalizer.normalize()
│    ├─ Private tag (0043,xxxx) → GE 전용 보정
│    └─ Window/Level 표준화
├─ PHILIPS → PhilipsNormalizer.normalize()
│    ├─ Private tag (2005,xxxx) → Philips 전용 보정
│    └─ Rescale Slope/Intercept 확인
└─ 기타 → 범용 DicomNormalizer만 적용
```

#### 2.4 장비 프로필 기반 자동수정

AE Title별로 반복되는 이슈에 대해 프리셋 자동 적용:

```
장비 프로필 설정:
  AE Title: "CT_ER_SIEMENS"
  ├─ 자동수정 프리셋: [pixel_spacing, charset_utf8, date_format]
  ├─ 사설 태그 정책: keep (Siemens 보정 데이터 유지)
  └─ 제조사: SIEMENS → SiemensNormalizer 자동 적용
```

---

### Phase 3: 지능형 자동수정

#### 2.5 연쇄 수정 (Cascade Fix)

하나의 인스턴스에 여러 이슈가 있을 때, 한 번의 수정 사이클로 모두 처리:

```
기존 (v9.0):
  이슈1 자동수정 → 재검증 → 이슈2 자동수정 → 재검증 → ...

개선 (v9.1):
  모든 이슈 분석 → 수정 계획 수립 → 일괄 적용 → 재검증 1회
```

**구현**: `_apply_extra_fixes()`에서 단일 rule_code가 아닌 해당 SOP의 모든 rule_code를 한 번에 처리

#### 2.6 AI 기반 수정 제안 (WeRU.B 연동)

자동수정 불가 이슈에 대해 AI가 수정 방안 제안:

| 규칙 | AI 활용 |
|------|--------|
| `MISSING_MANDATORY_TAG` | 같은 Study의 다른 인스턴스에서 태그 값 추론 |
| `UNKNOWN_PHOTOMETRIC` | 픽셀 데이터 분석으로 올바른 Photometric 추론 |
| `BITS_STORED_GT_ALLOCATED` | 실제 픽셀 데이터 비트 범위 분석 후 BitsAllocated 교정 |
| `MISSING_IMAGE_DIMENSIONS` | 픽셀 데이터 크기에서 Rows/Columns 역추산 |

```
POST /api/v1/dicom-issues/ai-suggest/{issue_id}
→ WeRU.B AI 분석 → 수정 제안 반환 (관리자 승인 후 적용)
```

#### 2.7 패턴 학습 + 자동 규칙 생성

반복되는 이슈 패턴을 감지하여 새 규칙 제안:

```
예시:
  장비 CT_ER에서 매주 "INVALID_DATE_FORMAT" 5건 이상 반복
  → 알림: "CT_ER 장비의 날짜 형식 설정을 점검하세요"
  → 자동 조치: 이 장비의 해당 규칙을 auto_action=normalize로 변경 제안
```

---

### Phase 4: 수신 게이트 + 격리

#### 2.8 Pre-Store Validation Gate

DICOM 수신 시점에서 검증 → 차단/수정/통과 결정:

```
Orthanc Lua Plugin:
  function OnStoredInstance(instanceId, tags, metadata)
    -- Call FastAPI validation endpoint
    local result = HttpPost("/api/v1/dicom-issues/gate-check", body)
    if result.action == "reject" then
      Delete(instanceId)  -- 저장 거부
      return
    elseif result.action == "normalize" then
      -- 수정 후 교체
    end
  end
```

#### 2.9 격리 큐 (Quarantine)

심각한 이슈가 있는 영상을 별도 격리 큐로 분리:

```sql
CREATE TABLE dicom_quarantine (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    study_instance_uid VARCHAR(128) NOT NULL,
    sop_instance_uid VARCHAR(128) NOT NULL,
    orthanc_id VARCHAR(64),
    reason VARCHAR(64) NOT NULL,        -- rule_code
    severity VARCHAR(16) NOT NULL,
    quarantined_at TIMESTAMPTZ DEFAULT NOW(),
    released_at TIMESTAMPTZ,
    released_by UUID,
    decision VARCHAR(16)                -- released, deleted, fixed
);
```

- 격리된 영상은 판독 큐에 표시되지 않음
- 관리자가 확인 후 릴리스/삭제/수정 결정

---

## 3. API 설계

### 3.1 신규 API (5개)

| # | Method | Endpoint | 설명 |
|---|--------|----------|------|
| 1 | POST | `/api/v1/dicom-issues/cascade-fix/{sop_uid}` | 연쇄 수정: SOP의 모든 이슈 일괄 수정 |
| 2 | GET | `/api/v1/dicom-issues/fix-history` | 수정 이력 조회 |
| 3 | POST | `/api/v1/dicom-issues/rollback/{fix_id}` | 수정 롤백 (원본 복원) |
| 4 | POST | `/api/v1/dicom-issues/ai-suggest/{issue_id}` | AI 수정 제안 (WeRU.B 연동) |
| 5 | POST | `/api/v1/dicom-issues/gate-check` | Pre-Store 게이트 체크 |

### 3.2 수정 API (4개)

| # | Endpoint | 변경 |
|---|----------|------|
| 1 | `POST /auto-fix/{issue_id}` | 원본 백업 + 제조사 Normalizer 연동 + fix_history 기록 |
| 2 | `POST /auto-fix-all` | 연쇄 수정 적용 (SOP 단위 일괄 처리) |
| 3 | `POST /scan` | 스캔 시 auto_action에 따라 자동수정까지 실행 |
| 4 | `PUT /rules/{rule_code}` | auto_action 변경 시 기존 이슈에도 소급 적용 옵션 |

---

## 4. 구현 우선순위

### Phase 1: 즉시 가치 (높은 ROI)

| # | 작업 | 효과 |
|---|------|------|
| 1 | **연쇄 수정** — SOP 단위 일괄 처리 | 수정 횟수 감소, 재검증 1회로 통합 |
| 2 | **원본 백업 + 이력** — fix_history 테이블 | 롤백 가능, 감사 추적 |
| 3 | **스캔 시 자동수정** — scan API에 auto_action 연동 | 수동 "일괄 자동수정" 불필요 |
| 4 | **Celery beat 자동 검증** — 5분 주기 미검증 스캔 | 실시간 이슈 감지 |

### Phase 2: 제조사 특화

| # | 작업 | 효과 |
|---|------|------|
| 5 | SupplierNormalizer 연동 | Siemens/GE/Philips 고유 이슈 자동 해결 |
| 6 | 장비 프로필 자동수정 프리셋 | 반복 이슈 원천 차단 |

### Phase 3: 지능형

| # | 작업 | 효과 |
|---|------|------|
| 7 | AI 수정 제안 (WeRU.B) | MISSING_MANDATORY_TAG 등 난제 해결 |
| 8 | 패턴 감지 + 장비 알림 | 근본 원인 해결 (장비 설정 변경) |

### Phase 4: 방어벽

| # | 작업 | 효과 |
|---|------|------|
| 9 | Pre-Store Gate (Orthanc Lua) | 비표준 영상 사전 차단 |
| 10 | 격리 큐 | 위험 영상 판독 큐에서 격리 |

---

## 5. 자동수정률 목표

| 단계 | 자동수정 가능 규칙 | 자동수정률 (예상) |
|------|------------------|------------------|
| **현재 (v9.0)** | 13/22 | 88% (실제 이슈 건수 기준) |
| **Phase 1** (연쇄+자동트리거) | 13/22 | 88% → **실시간 자동 처리** |
| **Phase 2** (제조사 특화) | 15/22 | 92% (UNKNOWN_PHOTOMETRIC, BITS 추가) |
| **Phase 3** (AI 제안) | 19/22 | 97% (MISSING_MANDATORY 등 AI 지원) |
| **Phase 4** (게이트) | 22/22 | **99%** (사전 차단으로 이슈 자체 감소) |

---

## 6. 데이터 모델

### 6.1 신규 테이블 (2개)

```sql
-- 수정 이력 + 롤백
CREATE TABLE dicom_fix_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    study_instance_uid VARCHAR(128) NOT NULL,
    sop_instance_uid VARCHAR(128) NOT NULL,
    rule_codes TEXT[] NOT NULL,               -- 수정한 규칙 목록
    changes JSONB NOT NULL,                    -- [{tag, original, corrected, rationale}]
    original_hash VARCHAR(64),                 -- SHA256 원본 해시
    backup_path TEXT,                          -- 원본 파일 경로 또는 Orthanc ID
    fix_status VARCHAR(16) DEFAULT 'applied',  -- applied, rolled_back, failed
    post_validation JSONB,                     -- 재검증 결과
    manufacturer VARCHAR(64),
    supplier_normalizer VARCHAR(32),           -- siemens, ge, philips, generic
    fixed_by UUID,
    fixed_at TIMESTAMPTZ DEFAULT NOW(),
    rolled_back_at TIMESTAMPTZ,
    
    INDEX ix_fix_history_study (study_instance_uid),
    INDEX ix_fix_history_status (fix_status)
);

-- 격리 큐
CREATE TABLE dicom_quarantine (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    study_instance_uid VARCHAR(128) NOT NULL,
    sop_instance_uid VARCHAR(128) NOT NULL,
    orthanc_id VARCHAR(64),
    rule_code VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    message TEXT,
    quarantined_at TIMESTAMPTZ DEFAULT NOW(),
    released_at TIMESTAMPTZ,
    released_by UUID,
    decision VARCHAR(16),                       -- released, deleted, fixed
    
    INDEX ix_quarantine_study (study_instance_uid),
    INDEX ix_quarantine_decision (decision)
);
```

---

## 7. 위험 요소 및 대응

| 위험 | 영향 | 대응 |
|------|------|------|
| UID 변경 시 스터디 참조 깨짐 | 기존 판독/AI 결과와 연결 끊김 | UID 변경 전 모든 참조 테이블 업데이트 + 매핑 테이블 유지 |
| 자동수정 오류로 영상 품질 저하 | 진단 영향 | 원본 백업 필수 + 롤백 API + CRITICAL 규칙은 자동수정 금지 |
| Celery 자동 검증으로 Orthanc 부하 | 수신 성능 저하 | rate limiter + stable study만 검증 (수신 후 30초 대기) |
| 사설 태그 삭제로 제조사 보정 손실 | 영상 품질 저하 | 장비 프로필에서 제조사별 정책 설정 (Siemens: keep, 기타: remove) |
| AI 제안 오적용 | 잘못된 태그 삽입 | AI 제안은 관리자 승인 후 적용 (auto_action=suggest) |
| Pre-Store Gate로 정상 영상 거부 | 판독 지연 | Gate는 CRITICAL만 차단, WARNING/INFO는 통과 후 기록 |

---

## 8. 기대 효과

| 효과 | 정량 목표 |
|------|----------|
| **자동수정률** | 88% → 97% (AI 포함 시) |
| **이슈 대응 시간** | 수동 수시간 → 자동 5분 이내 |
| **관리자 개입** | 매일 수십 건 → CRITICAL만 (예상 월 2~3건) |
| **원본 보호** | 롤백 가능 → 수정 오류 시 즉시 복구 |
| **장비 관리** | 반복 이슈 패턴 감지 → 장비 설정 변경 안내 |
| **규제 대응** | 전체 수정 이력 추적 가능 → 의료기기 인증 근거 |
