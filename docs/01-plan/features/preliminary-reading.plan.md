# 예비 판독 (Preliminary Reading) 기획서

> **Summary**: 레지던트가 예비 판독 → 전문의가 검토/수정 → 최종 서명하는 2단계 판독 워크플로우
>
> **Project**: OpenPACS (WeRU.B)
> **Version**: v7.3+
> **Author**: AI Assistant
> **Date**: 2026-05-20
> **Status**: Draft

---

## 1. Overview

### 1.1 Purpose

교육 병원(수련 병원)에서 레지던트/전공의가 예비 판독(preliminary read)을 작성하고, 전문의(attending)가 검토·수정 후 최종 서명(final)하는 워크플로우를 완성한다.

### 1.2 Background

- 기존 기획서(`role-based-workflow.plan.md` §10)에서 예비 판독 필요성 식별
- **이미 구현된 인프라**: `ReportStatus.PRELIMINARY`, `preliminary_by_id/name/at` 필드, Sign API `as_preliminary` 파라미터
- **미구현**: 전문의 전용 검토 워크플로우, 예비→최종 변환 시 원본 보존, 역할 기반 접근 제어, 대시보드/필터, 알림

### 1.3 Related Documents

- `docs/01-plan/features/role-based-workflow.plan.md` §10
- `docs/01-plan/features/werub-report-extension.plan.md`

---

## 2. Scope

### 2.1 In Scope

- [ ] 예비 판독 서명 시 역할 검증 (레지던트 허용, 전문의도 가능)
- [ ] 전문의 검토 API — preliminary → final 변환 + 원본 내용 보존
- [ ] 예비 판독 목록 조회 API (전문의 대시보드용)
- [ ] 응답에 preliminary 관련 필드 포함 (`_to_response` 확장)
- [ ] 예비 판독 완료 시 전문의 알림 (WebSocket + Notification)
- [ ] next-unread에서 preliminary 상태 제외 (이미 예비 판독됨)
- [ ] 워크리스트 예비판독 필터/배지

- [ ] **[FE-뷰어]** ReportService.sign()에 `as_preliminary` 파라미터 지원
- [ ] **[FE-뷰어]** ReportPanel 서명 버튼 분리: "예비 서명" / "최종 서명"
- [ ] **[FE-뷰어]** preliminary 상태 리포트에 "최종 서명" 버튼 표시 (전문의용)
- [ ] **[FE-뷰어]** ReportService.finalize() 메서드 추가
- [ ] **[FE-뷰어]** 예비 판독 원본 비교 표시 (preliminary_content 접기/펼치기)
- [ ] **[FE-Admin]** 판독 큐 필터에 '예비 판독' 탭 추가
- [ ] **[FE-Admin]** 예비 판독 건수 배지 표시

### 2.2 Out of Scope

- 레지던트 성과 평가/통계 (별도 기능)
- 다단계 승인 (레지던트→펠로우→전문의)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 예비 서명: 레지던트가 `as_preliminary=true`로 서명 시 `PRELIMINARY` 상태 | High | ✅ 구현됨 |
| FR-02 | 전문의 검토 API: `POST /reports/{id}/finalize` — preliminary 리포트를 검토·수정 후 final로 전환 | High | Pending |
| FR-03 | 원본 보존: finalize 시 예비 판독 원문을 `preliminary_content` (JSONB)에 저장 | High | Pending |
| FR-04 | 예비 판독 목록: `GET /reports?status=preliminary` 이미 동작, 전문의 전용 뷰 추가 | Medium | Pending |
| FR-05 | 응답 확장: `_to_response`에 `preliminary_by_name`, `preliminary_at`, `preliminary_content` 포함 | High | Pending |
| FR-06 | 알림: 예비 서명 시 전문의에게 "예비 판독 대기" 알림 발송 | Medium | Pending |
| FR-07 | next-unread 개선: preliminary 상태 study를 "미판독"에서 제외 | Low | Pending |
| FR-08 | 역할 제어: `create_report` — 레지던트(RADIOLOGIST)도 리포트 생성 가능 (현재 동작) | High | ✅ 구현됨 |
| FR-09 | **[FE]** ReportService.sign()에 `as_preliminary` 파라미터 전달 | High | Pending |
| FR-10 | **[FE]** ReportPanel 서명 버튼 분리 — "예비 서명" + "최종 서명" | High | Pending |
| FR-11 | **[FE]** preliminary 리포트에 "최종 서명(finalize)" 버튼 표시 | High | Pending |
| FR-12 | **[FE]** ReportService.finalize() 메서드 추가 | High | Pending |
| FR-13 | **[FE]** 예비 판독 원본 비교 표시 (접기/펼치기) | Medium | Pending |
| FR-14 | **[FE-Admin]** 판독 큐 필터에 '예비 판독' 탭 추가 | Medium | Pending |
| FR-15 | **[FE-Admin]** 예비 판독 건수 배지 표시 | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement |
|----------|----------|-------------|
| Performance | finalize API < 200ms | curl 측정 |
| Security | 전문의(RADIOLOGIST+attending)만 finalize 가능 | RBAC 테스트 |
| Audit | 예비→최종 전환 감사 로그 기록 | audit_logs 테이블 |

---

## 4. Detailed Design

### 4.1 워크플로우

```
레지던트                          전문의
─────────                      ─────────
리포트 작성 (DRAFT)
    │
    ▼
예비 서명 (PRELIMINARY)
    │
    ├──── 알림 ────────────────▶ 대기 목록에 표시
    │                              │
    │                              ▼
    │                          리포트 열기/검토
    │                              │
    │                         ┌────┴────┐
    │                    수정 필요    수정 없음
    │                         │         │
    │                    내용 수정      │
    │                         │         │
    │                         ▼         ▼
    │                      최종 서명 (FINAL)
    │                     (원본 보존)
    │                              │
    ▼                              ▼
판독 완료 확인              주치의 알림 발송
```

### 4.2 DB 변경

```python
# Report 모델에 추가
preliminary_content: Mapped[dict | None] = mapped_column(JSONB)
# → 최종 서명 시 예비 판독 원문 { findings, impression, recommendation } 저장
```

### 4.3 API 변경

#### 신규: `POST /reports/{report_id}/finalize`

```python
# 전문의 전용 — preliminary → final 전환
# Request body: ReportUpdate (findings, impression 수정 가능)
# 동작:
#   1. status == PRELIMINARY 확인
#   2. 예비 원문을 preliminary_content에 백업
#   3. 전문의 수정 내용 반영
#   4. status = FINAL, signed_by = 전문의
#   5. 감사 로그 + 주치의 알림
```

#### 변경: `_to_response()`

```python
# 추가 필드:
"preliminary_by_name": r.preliminary_by_name,
"preliminary_at": r.preliminary_at.isoformat() if r.preliminary_at else None,
"preliminary_content": r.preliminary_content,
```

#### 변경: `next-unread`

```python
# reported_uids 조회 시 preliminary도 포함
Report.status.in_(["final", "draft", "preliminary"])
```

### 4.4 프론트엔드 변경

#### WeRU.B Viewer — ReportService.ts

```typescript
// sign()에 as_preliminary 파라미터 추가
async sign(asPreliminary = false): Promise<Report | null> {
  const qs = asPreliminary ? '?as_preliminary=true' : '';
  const result = await this.api<Report>(
    `/reports/${this._currentReport.id}/sign${qs}`, { method: 'POST' }
  );
  // ...
}

// finalize() 신규 — preliminary → final 전환
async finalize(updates?: Partial<Report>): Promise<Report | null> {
  const result = await this.api<Report>(
    `/reports/${this._currentReport.id}/finalize`,
    { method: 'POST', body: JSON.stringify(updates || {}) }
  );
  // ...
}
```

#### WeRU.B Viewer — ReportPanel.tsx

```
현재 Footer (draft/preliminary 상태):
┌──────────────┬──────────────┐
│  임시 저장    │  서명        │  ← 현재: 무조건 final
└──────────────┴──────────────┘

변경 후 Footer (draft 상태):
┌──────────────┬──────────────┬──────────────┐
│  임시 저장    │  예비 서명    │  최종 서명    │
└──────────────┴──────────────┴──────────────┘

변경 후 Footer (preliminary 상태 — 전문의가 열었을 때):
┌────────────────────┬──────────────────────┐
│  원본 비교          │  최종 서명 (확정)     │
└────────────────────┴──────────────────────┘
```

- `handleSign` → `handleSign(asPreliminary: boolean)` 분리
- preliminary 상태이면 수정 가능 (readOnly 해제) + finalize 버튼 표시
- 예비 판독 원본(`preliminary_content`) 접기/펼치기 패널

#### Admin — reading/page.tsx

```typescript
// 필터 버튼에 'preliminary' 추가
{ key: 'preliminary', label: '예비 판독' }

// 예비 판독 건수 배지 (unread 옆에 표시)
{preliminary > 0 && <span className="bg-purple-100 ...">예비 {preliminary}건</span>}
```

### 4.5 Report Interface 확장

```typescript
// ReportService.ts — Report 인터페이스에 추가
export interface Report {
  // ... 기존 필드
  preliminary_by_name?: string;
  preliminary_at?: string;
  preliminary_content?: {
    findings: string;
    impression: string;
    recommendation: string;
  };
}
```

---

## 5. Success Criteria

### 5.1 Definition of Done

- [ ] finalize API 정상 동작 (preliminary → final)
- [ ] 예비 판독 원문 보존 확인
- [ ] 전문의 알림 발송 확인
- [ ] _to_response 필드 확인
- [ ] next-unread에서 preliminary 제외 확인
- [ ] 감사 로그 기록 확인
- [ ] **[FE]** 뷰어에서 "예비 서명" 버튼으로 preliminary 서명 가능
- [ ] **[FE]** 뷰어에서 preliminary 리포트 열면 "최종 서명" 버튼 표시
- [ ] **[FE]** 예비 판독 원본 비교 패널 동작
- [ ] **[FE-Admin]** 판독 큐에서 '예비 판독' 필터 동작

### 5.2 Quality Criteria

- [ ] 기존 테스트 깨지지 않음
- [ ] 서버 배포 후 curl 검증 통과

---

## 6. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| DB 마이그레이션 (preliminary_content 컬럼) | Medium | Low | nullable JSONB — ALTER TABLE ADD COLUMN |
| 기존 PRELIMINARY 상태 리포트와 충돌 | Low | Low | 기존 데이터 없음 (운영 초기) |
| 레지던트/전문의 역할 구분 미비 | Medium | Medium | 현재 둘 다 RADIOLOGIST — 향후 세분화 가능, 지금은 as_preliminary flag로 구분 |

---

## 7. Implementation Plan

### Phase A: 백엔드

| 순서 | 작업 | 파일 | 규모 |
|:----:|------|------|:----:|
| 1 | Report 모델에 `preliminary_content` 필드 추가 | `models/report.py` | 소 |
| 2 | `_to_response()` 확장 | `api/report.py` | 소 |
| 3 | `POST /reports/{id}/finalize` API 구현 | `api/report.py` | 중 |
| 4 | 예비 서명 시 전문의 알림 추가 | `api/report.py` | 소 |
| 5 | `next-unread` 수정 | `api/report.py` | 소 |
| 6 | 서버 배포 + DB 마이그레이션 | SQL | 소 |

### Phase B: 프론트엔드 (WeRU.B Viewer)

| 순서 | 작업 | 파일 | 규모 |
|:----:|------|------|:----:|
| 7 | Report 인터페이스 확장 (preliminary 필드) | `ReportService.ts` | 소 |
| 8 | `sign(asPreliminary)` 파라미터 추가 | `ReportService.ts` | 소 |
| 9 | `finalize()` 메서드 추가 | `ReportService.ts` | 소 |
| 10 | 서명 버튼 분리 ("예비 서명" / "최종 서명") | `ReportPanel.tsx` | 중 |
| 11 | preliminary 상태 — 수정 허용 + finalize 버튼 | `ReportPanel.tsx` | 중 |
| 12 | 예비 판독 원본 비교 패널 (접기/펼치기) | `ReportPanel.tsx` | 중 |

### Phase C: 프론트엔드 (Admin)

| 순서 | 작업 | 파일 | 규모 |
|:----:|------|------|:----:|
| 13 | 판독 큐 필터에 '예비 판독' 탭 추가 | `reading/page.tsx` | 소 |
| 14 | 예비 판독 건수 배지 표시 | `reading/page.tsx` | 소 |

---

## 8. Next Steps

1. [ ] Design 문서 작성 (`preliminary-reading.design.md`)
2. [ ] 구현 (Do phase)
3. [ ] Gap 분석 (Check phase)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-05-20 | Initial draft (백엔드 only) | AI Assistant |
| 0.2 | 2026-05-20 | 프론트엔드 포함 (FR-09~15, Phase B/C) | AI Assistant |
