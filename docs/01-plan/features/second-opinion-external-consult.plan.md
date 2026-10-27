# 세컨드 오피니언 & 외부 판독 의뢰 기획서

> **Summary**: 판독 화면에서 세컨드 오피니언 요청 + 외부 판독 의뢰 프로세스 통합
>
> **Project**: OpenPACS (WeRU.B)
> **Version**: v7.6+
> **Date**: 2026-05-20
> **Status**: Draft

---

## 1. 현재 구현 상태

### 이미 구현된 백엔드 API

| API | 엔드포인트 | 상태 |
|-----|----------|:----:|
| 피어 리뷰 배정 | `POST /api/v1/peer-review/assign` | ✅ |
| 피어 리뷰 대기 목록 | `GET /api/v1/peer-review/pending` | ✅ |
| 피어 리뷰 제출 | `PUT /api/v1/peer-review/{id}/submit` | ✅ |
| 피어 리뷰 통계 | `GET /api/v1/peer-review/statistics` | ✅ |
| 세컨드 오피니언 요청 | `POST /api/v1/conferences/second-opinion/request` | ✅ |
| 세컨드 오피니언 이력 | `GET /api/v1/conferences/second-opinion/history` | ✅ |
| 공유 링크 생성 | `POST /api/v1/share-links` | ✅ |

### 미구현

| 항목 | 상태 |
|------|:----:|
| 판독 화면에서 세컨드 오피니언 버튼 | ❌ |
| 판독 화면에서 피어 리뷰 요청 버튼 | ❌ |
| 외부 판독 의뢰 프로세스 (공식) | ❌ |
| 의뢰 상태 추적 (대기→진행→완료) | ❌ |
| 의뢰 결과 수신 및 리포트 연결 | ❌ |
| 알림 (의뢰 결과 도착 시) | ❌ |

---

## 2. 3가지 프로세스 구분

### A. 피어 리뷰 (내부 동료 검토)

```
판독의 A가 판독 완료 → 피어 리뷰 배정 (랜덤/지정)
→ 판독의 B가 검토 → agree/disagree/partial 제출
→ 불일치율 통계에 반영
```

- **대상**: 내부 판독의 간 품질 관리
- **시점**: 판독 완료(final) 후
- **결과**: agree/disagree/partial + 코멘트

### B. 세컨드 오피니언 (전문가 자문)

```
판독의가 난해한 케이스 발견 → 세컨드 오피니언 요청
→ 내부 상급 전문의 또는 외부 전문의에게 전달
→ 의견 수신 → 리포트에 참고 기록
```

- **대상**: 난해/복잡 케이스
- **시점**: 판독 중 또는 판독 후
- **결과**: 전문가 소견 텍스트

### C. 외부 판독 의뢰 (정식 위탁)

```
기관에서 특정 검사를 외부 기관에 공식 위탁
→ 영상 공유 (링크 또는 DICOM 전송)
→ 외부 기관 판독 → 결과 수신
→ 자체 리포트에 외부 판독 결과 첨부
```

- **대상**: 자체 판독 불가 검사 (PET-CT, 특수 MRI 등)
- **시점**: 촬영 후, 판독 전
- **결과**: 외부 기관 판독문 (PDF/텍스트)

---

## 3. 기능 요구사항

### 3.1 판독 화면 통합

| ID | 기능 | 우선순위 |
|----|------|:--------:|
| FR-01 | 판독 화면에 "세컨드 오피니언" 버튼 추가 | High |
| FR-02 | 판독 화면에 "피어 리뷰 요청" 버튼 추가 (final 상태에서) | High |
| FR-03 | 판독 화면에 "외부 의뢰" 버튼 추가 | High |
| FR-04 | 내 피어 리뷰 대기 건수 네비 배지 | Medium |
| FR-05 | 세컨드 오피니언 / 외부 의뢰 상태 추적 패널 | Medium |
| FR-06 | 의뢰 결과 도착 시 알림 (WebSocket) | Medium |

### 3.2 외부 판독 의뢰 API (신규)

| ID | 기능 | 설명 |
|----|------|------|
| FR-07 | `POST /api/v1/external-consult` | 외부 판독 의뢰 생성 |
| FR-08 | `GET /api/v1/external-consult` | 의뢰 목록 조회 |
| FR-09 | `PUT /api/v1/external-consult/{id}/respond` | 외부 판독 결과 입력 |
| FR-10 | `PUT /api/v1/external-consult/{id}/cancel` | 의뢰 취소 |

### 3.3 외부 판독 의뢰 데이터

```sql
CREATE TABLE external_consults (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    study_instance_uid VARCHAR(128) NOT NULL,
    report_id UUID REFERENCES reports(id),
    -- 의뢰 정보
    consult_type VARCHAR(32) DEFAULT 'external_read',  -- external_read, subspecialty, teleradiology
    institution_name VARCHAR(256),        -- 외부 기관명
    physician_name VARCHAR(256),          -- 외부 판독의
    physician_email VARCHAR(256),         -- 이메일
    reason TEXT,                          -- 의뢰 사유
    clinical_info TEXT,                   -- 임상 정보
    urgency VARCHAR(16) DEFAULT 'routine', -- routine, urgent, stat
    -- 공유
    share_link_id UUID,                   -- 영상 공유 링크
    share_method VARCHAR(32) DEFAULT 'link', -- link, dicom_send, cd
    -- 상태
    status VARCHAR(16) DEFAULT 'requested', -- requested, in_progress, completed, cancelled
    -- 결과
    external_findings TEXT,               -- 외부 판독 소견
    external_impression TEXT,             -- 외부 판독 결론
    external_report_pdf TEXT,             -- PDF 경로
    -- 추적
    requested_by_id UUID REFERENCES users(id),
    requested_by_name VARCHAR(256),
    requested_at TIMESTAMPTZ DEFAULT NOW(),
    responded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_ext_consult_study ON external_consults(study_instance_uid);
CREATE INDEX idx_ext_consult_status ON external_consults(status);
```

---

## 4. 판독 화면 UI

### 4.1 현재 판독 화면 하단

```
┌────────────┬──────────────┐
│  임시 저장  │  서명        │
└────────────┴──────────────┘
```

### 4.2 변경 후 — 추가 액션 드롭다운

```
┌────────────┬──────────────┬────────┐
│  임시 저장  │  서명        │  더보기 ▾│
└────────────┴──────────────┴────────┘
                              ├─ 피어 리뷰 요청
                              ├─ 세컨드 오피니언
                              ├─ 외부 판독 의뢰
                              └─ 공유 링크 생성
```

### 4.3 세컨드 오피니언 모달

```
┌────────────────────────────────────┐
│ 세컨드 오피니언 요청                │
├────────────────────────────────────┤
│ 대상:  ○ 내부 전문의  ● 외부 전문의 │
│                                    │
│ 전문의: [___________________] (선택)│
│ 이메일: [___________________]      │
│                                    │
│ 질문/사유:                         │
│ [________________________________] │
│ [________________________________] │
│                                    │
│ □ 영상 공유 링크 자동 생성          │
│                                    │
│        [취소]  [요청 전송]          │
└────────────────────────────────────┘
```

### 4.4 외부 판독 의뢰 모달

```
┌────────────────────────────────────┐
│ 외부 판독 의뢰                      │
├────────────────────────────────────┤
│ 의뢰 유형: ○ 외부 판독  ○ 세부전공   │
│           ○ 원격판독(Teleradiology)│
│                                    │
│ 외부 기관: [___________________]    │
│ 판독의:   [___________________]    │
│ 이메일:   [___________________]    │
│                                    │
│ 긴급도: ○ 일반  ○ 긴급  ○ STAT     │
│                                    │
│ 의뢰 사유:                         │
│ [________________________________] │
│                                    │
│ 임상 정보:                         │
│ [________________________________] │
│                                    │
│ 영상 공유: ○ 링크  ○ DICOM 전송    │
│                                    │
│        [취소]  [의뢰 전송]          │
└────────────────────────────────────┘
```

---

## 5. 워크플로우

### 5.1 세컨드 오피니언 흐름

```
판독의 → [세컨드 오피니언] 클릭
→ 대상/질문 입력 → 요청 전송
→ 내부: 지정 판독의에게 알림 (WebSocket)
→ 외부: 이메일 + 공유 링크 전송
→ 응답 수신 → 원본 리포트에 참고 기록
→ 판독의에게 알림
```

### 5.2 외부 판독 의뢰 흐름

```
판독의/관리자 → [외부 의뢰] 클릭
→ 기관/판독의/사유 입력 → 의뢰 전송
→ 영상 공유 링크 자동 생성
→ 외부 기관 판독 (비동기)
→ 결과 입력 (관리자가 수동 입력 또는 API)
→ 원본 Study에 외부 판독 결과 첨부
→ 의뢰 완료 알림
```

### 5.3 상태 흐름

```
requested → in_progress → completed
                        → cancelled
```

---

## 6. 구현 순서

### Phase A: 백엔드 API

| # | 작업 | 규모 |
|---|------|:----:|
| 1 | external_consults 테이블 생성 (DB 마이그레이션) | 소 |
| 2 | 외부 판독 의뢰 CRUD API (4개 엔드포인트) | 중 |
| 3 | 의뢰 시 공유 링크 자동 생성 연동 | 소 |
| 4 | 의뢰 결과 도착 시 알림 (Notification + WebSocket) | 소 |

### Phase B: Admin 판독 화면 UI

| # | 작업 | 규모 |
|---|------|:----:|
| 5 | 판독 화면 "더보기" 드롭다운 추가 | 소 |
| 6 | 세컨드 오피니언 요청 모달 | 중 |
| 7 | 외부 판독 의뢰 모달 | 중 |
| 8 | 피어 리뷰 요청 버튼 (final 상태) | 소 |
| 9 | 의뢰 상태 표시 (리포트 하단) | 소 |

### Phase C: 목록/관리

| # | 작업 | 규모 |
|---|------|:----:|
| 10 | 외부 의뢰 관리 페이지 (`/pacs-admin/consults`) | 중 |
| 11 | 피어 리뷰 대기 배지 (네비바) | 소 |

---

## 7. 테스트 계정별 권한

| 기능 | admin | radiologist | resident | physician |
|------|:-----:|:-----------:|:--------:|:---------:|
| 피어 리뷰 요청 | ✅ | ✅ | ❌ | ❌ |
| 피어 리뷰 제출 | ✅ | ✅ | ❌ | ❌ |
| 세컨드 오피니언 | ✅ | ✅ | ✅ | ❌ |
| 외부 판독 의뢰 | ✅ | ✅ | ❌ | ❌ |
| 의뢰 결과 입력 | ✅ | ✅ | ❌ | ❌ |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-05-20 | Initial draft | AI Assistant |
