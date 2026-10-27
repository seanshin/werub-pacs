# 예비 판독 (Preliminary Reading) Design Document

> **Summary**: 레지던트 예비 판독 → 전문의 검토·확정 2단계 워크플로우 상세 설계
>
> **Project**: OpenPACS (WeRU.B)
> **Version**: v7.3+
> **Author**: AI Assistant
> **Date**: 2026-05-20
> **Status**: Draft
> **Planning Doc**: [preliminary-reading.plan.md](../01-plan/features/preliminary-reading.plan.md)

---

## 1. Overview

### 1.1 Design Goals

- 기존 인프라(`ReportStatus.PRELIMINARY`, `preliminary_by_*` 필드, `as_preliminary` 파라미터) 활용, 최소 변경으로 완성
- 전문의가 예비 판독 리포트를 검토·수정·확정하는 `finalize` API 신규 구현
- 예비 판독 원문 보존으로 수련 교육 목적 지원
- 뷰어/Admin 프론트엔드에서 예비 판독 워크플로우 UX 완성

### 1.2 Design Principles

- **Backward Compatible**: 기존 sign API 동작 변경 없음 — `as_preliminary=false`(기본값) 유지
- **Minimal Model Change**: Report 모델에 `preliminary_content` JSONB 컬럼 1개만 추가
- **Role-Agnostic Workflow**: 레지던트/전문의 모두 `RADIOLOGIST` 역할 — `as_preliminary` flag로 워크플로우 구분

---

## 2. Architecture

### 2.1 Component Diagram

```
┌──────────────────┐     ┌──────────────────┐     ┌─────────────┐
│  WeRU.B Viewer   │     │   FastAPI Backend │     │ PostgreSQL  │
│  (ReportPanel)   │────▶│   /api/v1/reports │────▶│  reports    │
│                  │     │                  │     │  table      │
│  Admin UI        │     │  WebSocket       │     │             │
│  (ReadingPage)   │     │  Notification    │     │             │
└──────────────────┘     └──────────────────┘     └─────────────┘
```

### 2.2 Data Flow

```
[레지던트] draft → save → sign(as_preliminary=true) → PRELIMINARY
                                    │
                        ┌───────────┘
                        ▼
              WebSocket 알림 → 전문의
                        │
                        ▼
[전문의] 리포트 열기 → 수정(선택) → finalize → FINAL
                                    │
                        ┌───────────┘
                        ▼
              원본 보존 (preliminary_content)
              감사 로그 기록
              주치의 알림 발송
```

### 2.3 Dependencies

| Component | Depends On | Purpose |
|-----------|-----------|---------|
| finalize API | Report model | preliminary_content 저장 |
| finalize API | Notification API | 주치의 알림 발송 |
| finalize API | WebSocket manager | 실시간 브로드캐스트 |
| finalize API | AuditLogger | 감사 로그 |
| ReportPanel | ReportService | sign/finalize 호출 |
| ReadingPage | Dashboard API | preliminary 건수 조회 |

---

## 3. Data Model

### 3.1 Report 모델 변경 (1개 컬럼 추가)

```python
# backend/app/models/report.py — Report 클래스에 추가

# 기존 필드 (변경 없음):
# preliminary_by_id: Mapped[PyUUID | None]      — line 71
# preliminary_by_name: Mapped[str | None]        — line 72
# preliminary_at: Mapped[datetime | None]        — line 73

# 신규 필드:
preliminary_content: Mapped[dict | None] = mapped_column(JSONB)
# finalize 시 예비 판독 원문을 여기에 백업
```

### 3.2 preliminary_content 구조

```json
{
  "findings": "레지던트가 작성한 소견 원문",
  "impression": "레지던트가 작성한 결론 원문",
  "recommendation": "레지던트가 작성한 권고 원문",
  "backed_up_at": "2026-05-20T10:30:00Z"
}
```

### 3.3 DB 마이그레이션 SQL

```sql
ALTER TABLE reports ADD COLUMN preliminary_content JSONB;
```

---

## 4. API Specification

### 4.1 Endpoint List

| Method | Path | Description | Auth | 상태 |
|--------|------|-------------|------|:----:|
| POST | `/api/v1/reports/{id}/sign?as_preliminary=true` | 예비 서명 | RADIOLOGIST | ✅ 구현됨 |
| POST | `/api/v1/reports/{id}/finalize` | 예비→최종 확정 | RADIOLOGIST, ADMIN | **신규** |
| GET | `/api/v1/reports?status=preliminary` | 예비 판독 목록 | 인증 필요 | ✅ 구현됨 |
| GET | `/api/v1/reports/{id}` | 리포트 상세 (preliminary 필드 포함) | 인증 필요 | **변경** |

### 4.2 신규: `POST /api/v1/reports/{report_id}/finalize`

**목적**: preliminary 리포트를 전문의가 검토 후 최종 서명(final)으로 전환

**권한**: `RADIOLOGIST`, `ADMIN`

**Request Body** (선택 — 수정 없이 확정도 가능):

```json
{
  "findings": "전문의가 수정한 소견 (선택)",
  "impression": "전문의가 수정한 결론 (선택)",
  "recommendation": "전문의가 수정한 권고 (선택)"
}
```

**Response (200 OK):**

```json
{
  "id": "uuid",
  "status": "final",
  "signed_by_name": "전문의 이름",
  "signed_at": "2026-05-20T10:30:00Z",
  "preliminary_by_name": "레지던트 이름",
  "preliminary_at": "2026-05-20T09:00:00Z",
  "preliminary_content": {
    "findings": "원본 소견",
    "impression": "원본 결론",
    "recommendation": "원본 권고",
    "backed_up_at": "2026-05-20T10:30:00Z"
  },
  "findings": "최종 소견 (수정된 경우 전문의 버전)",
  "impression": "최종 결론",
  "..."
}
```

**Error Responses:**

| Code | Condition |
|------|-----------|
| 404 | 리포트 없음 |
| 400 | `status != preliminary` (draft/final/cancelled에서 호출 불가) |
| 403 | 권한 없음 (PHYSICIAN, TECHNOLOGIST 등) |

**처리 순서**:

```python
1. Report 조회 + status == PRELIMINARY 검증
2. 예비 원문 백업 → preliminary_content
3. Request body에 수정 내용 있으면 반영
4. status = FINAL
5. signed_by = 현재 사용자 (전문의)
6. signed_at = now()
7. lock 해제
8. DB commit
9. 감사 로그: "REPORT_FINALIZED"
10. 주치의 알림 (Notification + WebSocket)
```

### 4.3 변경: `_to_response()` 확장

```python
# 기존 응답에 3개 필드 추가:
def _to_response(r: Report) -> dict:
    return {
        # ... 기존 필드 유지
        "preliminary_by_name": r.preliminary_by_name,
        "preliminary_at": r.preliminary_at.isoformat() if r.preliminary_at else None,
        "preliminary_content": r.preliminary_content,
    }
```

### 4.4 변경: `next-unread` 개선

```python
# 현재 (line 145):
Report.status.in_(["final", "draft"])

# 변경:
Report.status.in_(["final", "draft", "preliminary"])
```

### 4.5 변경: `sign_report` — 예비 서명 시 전문의 알림 추가

```python
# sign_report 함수 내, as_preliminary=true 분기 뒤에 추가:
if as_preliminary:
    # ... 기존 코드 ...
    # 전문의에게 알림 추가
    await create_notification(
        db,
        type="preliminary_ready",
        title=f"예비 판독 대기: {report.patient_name or report.patient_id}",
        message=f"{report.modality or ''} {report.study_description or ''} — 예비 판독 by {user.full_name}",
        urgency="normal",
        target_role="radiologist",
        study_instance_uid=report.study_instance_uid,
        patient_id=report.patient_id,
        action_url=f"/viewer/?StudyInstanceUIDs={report.study_instance_uid}",
    )
```

---

## 5. UI/UX Design

### 5.1 WeRU.B Viewer — ReportPanel Footer 변경

**현재 상태 (모든 비-final 리포트):**

```
┌──────────────────┬──────────────────┐
│   임시 저장       │  서명 (Ctrl+Enter)│
└──────────────────┴──────────────────┘
```

**변경 후 — draft 상태:**

```
┌────────────┬────────────────┬────────────────┐
│  임시 저장  │  예비 서명 (P)  │ 최종 서명 (⏎)  │
│  (blue)    │  (purple)      │ (green)        │
└────────────┴────────────────┴────────────────┘
```

**변경 후 — preliminary 상태 (수정 가능):**

```
┌────────────────────────────────────────────┐
│ ▶ 예비 판독 원본 (접기/펼치기)              │  ← 새 섹션
│   소견: 레지던트 원문...                    │
│   결론: 레지던트 원문...                    │
└────────────────────────────────────────────┘

┌────────────────────┬──────────────────────┐
│   임시 저장         │  최종 서명 (확정)     │
│   (blue)           │  (green)             │
└────────────────────┴──────────────────────┘
```

**변경 후 — final 상태 (변경 없음, 기존 유지):**

```
┌────────────────────────────────────────────┐
│              수정본 추가                    │
└────────────────────────────────────────────┘
+ 예비 판독 정보가 있으면 접기/펼치기 표시
```

### 5.2 WeRU.B Viewer — 서명 정보 표시 확장

```
┌────────────────────────────────────────────┐
│ 판독의: 김전문 · 2026-05-20 10:30          │  ← 최종 서명자
│ 예비판독: 최레지 · 2026-05-20 09:00        │  ← 예비 서명자 (있을 때만)
└────────────────────────────────────────────┘
```

### 5.3 Admin — 판독 큐 필터 확장

**현재 필터 버튼:**

```
[전체] [판독 대기] [작성 중] [완료]
```

**변경:**

```
[전체] [판독 대기] [작성 중] [예비 판독] [완료]
                             ↑ 신규 (purple)
```

**헤더 배지:**

```
전체 42건  대기 12건  예비 3건
                     ↑ 신규 (purple badge)
```

### 5.4 User Flow

```
레지던트:
  뷰어 로그인 → Study 선택 → 리포트 작성 → [예비 서명] 클릭
  → "예비 서명 완료" 알림 → 다음 Study

전문의:
  뷰어 로그인 → Study 선택 (또는 Admin '예비 판독' 필터)
  → preliminary 리포트 열림 → 원본 비교 (선택)
  → 수정 (선택) → [최종 서명] 클릭
  → "최종 서명 완료" 알림 → 다음 Study
```

### 5.5 Component List

| Component | Location | Responsibility |
|-----------|----------|----------------|
| ReportService | `werub-report/src/services/ReportService.ts` | sign/finalize API 호출 |
| ReportPanel | `werub-report/src/panels/ReportPanel.tsx` | 서명 버튼 분리, 원본 비교 |
| PreliminaryDiff | `werub-report/src/components/PreliminaryDiff.tsx` | **신규** — 원본 비교 접기/펼치기 |
| StatusBadge | `werub-report/src/components/StatusBadge.tsx` | 변경 없음 (이미 preliminary 지원) |
| ReadingPage | `admin/src/app/reading/page.tsx` | 필터 탭 + 배지 추가 |

---

## 6. Error Handling

| Code | Message | Cause | Handling |
|------|---------|-------|----------|
| 400 | "Report is not in preliminary status" | draft/final에서 finalize 호출 | 클라이언트에서 버튼 비활성화로 방지 |
| 403 | "Forbidden" | PHYSICIAN 등 비인가 역할 | 로그인 사용자 역할 확인 |
| 404 | "Report not found" | 잘못된 report_id | 에러 표시 |

---

## 7. Security Considerations

- [x] `finalize` API: `RequireRole(Role.RADIOLOGIST, Role.ADMIN)` 적용
- [x] 감사 로그: `@AuditLogger.log("REPORT_FINALIZED", "Report")`
- [x] `preliminary_content`에는 PHI(환자건강정보) 포함 — 기존 Report와 동일 보안 수준
- [x] Edit lock 해제 시 본인/관리자 확인

---

## 8. Test Plan

### 8.1 백엔드 curl 검증

```bash
# 1. 리포트 생성 (레지던트)
curl -X POST .../reports -H "Authorization: Bearer $RESIDENT_TOKEN" \
  -d '{"study_instance_uid":"1.2.3", "patient_id":"P001", "findings":"test", "impression":"test"}'

# 2. 예비 서명
curl -X POST .../reports/{id}/sign?as_preliminary=true -H "Authorization: Bearer $RESIDENT_TOKEN"
# → status: "preliminary", preliminary_by_name 확인

# 3. finalize (전문의)
curl -X POST .../reports/{id}/finalize -H "Authorization: Bearer $ATTENDING_TOKEN" \
  -d '{"findings":"수정된 소견"}'
# → status: "final", preliminary_content 확인

# 4. 원본 보존 확인
curl .../reports/{id} -H "Authorization: Bearer $TOKEN"
# → preliminary_content.findings == 원래 소견

# 5. 에러 케이스: draft에서 finalize 시도
curl -X POST .../reports/{draft_id}/finalize → 400

# 6. next-unread에서 preliminary 제외 확인
curl .../reports/next-unread → preliminary study 미포함
```

### 8.2 프론트엔드 수동 검증

- [ ] 레지던트 로그인 → 리포트 작성 → "예비 서명" 버튼 클릭 → preliminary 상태 확인
- [ ] 전문의 로그인 → 같은 Study 열기 → 수정 가능 확인 → "최종 서명" 클릭 → final 확인
- [ ] 예비 판독 원본 비교 접기/펼치기 동작 확인
- [ ] Admin 판독 큐 → '예비 판독' 필터 동작 확인
- [ ] Admin 헤더 배지 — 예비 판독 건수 표시 확인

---

## 9. Implementation Order

### Phase A: 백엔드 (순서대로)

| # | 작업 | 파일 | 변경 내용 |
|---|------|------|----------|
| A1 | `preliminary_content` 필드 추가 | `models/report.py:74` | JSONB 컬럼 1줄 추가 |
| A2 | `_to_response()` 확장 | `api/report.py:50-75` | 3개 필드 추가 |
| A3 | `finalize` API 구현 | `api/report.py` (sign 아래) | 신규 엔드포인트 ~50줄 |
| A4 | `sign_report` — 예비 서명 시 알림 | `api/report.py:307-311` | `create_notification` 호출 추가 |
| A5 | `next-unread` — preliminary 포함 | `api/report.py:145` | `["final","draft"]` → `["final","draft","preliminary"]` |
| A6 | DB 마이그레이션 | 서버 SSH | `ALTER TABLE reports ADD COLUMN preliminary_content JSONB` |

### Phase B: 프론트엔드 — WeRU.B Viewer

| # | 작업 | 파일 | 변경 내용 |
|---|------|------|----------|
| B1 | Report 인터페이스 확장 | `ReportService.ts:3-15` | `preliminary_*` 필드 3개 추가 |
| B2 | `sign(asPreliminary)` 변경 | `ReportService.ts:149-159` | 쿼리스트링 조건부 추가 |
| B3 | `finalize()` 신규 | `ReportService.ts` (sign 아래) | 신규 메서드 ~15줄 |
| B4 | ReportPanel 서명 버튼 분리 | `ReportPanel.tsx:254-270` | 3버튼 Footer (draft), 2버튼 Footer (preliminary) |
| B5 | preliminary 상태 수정 허용 | `ReportPanel.tsx:210` | `isFinal` → `isFinalized` (final만 readOnly) |
| B6 | PreliminaryDiff 컴포넌트 | `components/PreliminaryDiff.tsx` | **신규** 접기/펼치기 ~40줄 |
| B7 | 서명 정보 확장 | `ReportPanel.tsx:235-239` | preliminary_by_name 표시 추가 |

### Phase C: 프론트엔드 — Admin

| # | 작업 | 파일 | 변경 내용 |
|---|------|------|----------|
| C1 | 필터 탭에 '예비 판독' 추가 | `reading/page.tsx:76-84` | `{ key: 'preliminary', label: '예비 판독' }` |
| C2 | 예비 판독 건수 배지 | `reading/page.tsx:68-71` | Dashboard API에서 preliminary count 표시 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-05-20 | Initial design — 백엔드 + 프론트엔드 포함 | AI Assistant |
