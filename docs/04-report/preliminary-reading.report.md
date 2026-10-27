# 예비 판독 (Preliminary Reading) — PDCA 완료 보고서

> **Feature**: preliminary-reading
> **Date**: 2026-05-20
> **Match Rate**: 100% (14/14)
> **PDCA Cycle**: Plan → Design → Do → Check → Act → Report

---

## 1. Summary

레지던트가 예비 판독(preliminary) 후 전문의가 검토·확정(finalize)하는 2단계 판독 워크플로우를 완성했다. 기존 인프라(`ReportStatus.PRELIMINARY`, `preliminary_by_*` 필드, `as_preliminary` 파라미터)를 활용하여 최소 변경으로 백엔드 API, WeRU.B Viewer, Admin UI 전체를 구현했다.

---

## 2. PDCA Phase Summary

| Phase | 산출물 | 결과 |
|:-----:|--------|------|
| **Plan** | `docs/01-plan/features/preliminary-reading.plan.md` | FR 15개 정의 (백엔드 8 + 뷰어 5 + Admin 2) |
| **Design** | `docs/02-design/features/preliminary-reading.design.md` | API 상세 설계, UI 레이아웃, 구현 순서 14단계 |
| **Do** | 코드 구현 (Phase A/B/C) | 5개 파일 변경, 1개 파일 신규 |
| **Check** | Gap 분석 | 초기 93% (13/14) → B6 수정 후 100% |
| **Act** | B6 Gap 수정 | PreliminaryDiff 컴포넌트 파일 분리 |

---

## 3. Implementation Details

### 3.1 변경 파일 목록

| 파일 | 변경 유형 | 주요 내용 |
|------|:--------:|----------|
| `backend/app/models/report.py` | 수정 | `preliminary_content` JSONB 필드 추가 |
| `backend/app/api/report.py` | 수정 | `_to_response` 3필드 확장, `finalize` API 신규, 예비 서명 알림, next-unread 개선 |
| `werub-viewer/.../ReportService.ts` | 수정 | Report 인터페이스 확장, `sign(asPreliminary)`, `finalize()` 메서드 |
| `werub-viewer/.../ReportPanel.tsx` | 수정 | 3버튼/2버튼 Footer 분리, 서명 정보 확장, import 추가 |
| `werub-viewer/.../PreliminaryDiff.tsx` | **신규** | PreliminaryInfo + PreliminaryDiff 컴포넌트 |
| `admin/src/app/reading/page.tsx` | 수정 | '예비 판독' 필터 탭 + 건수 배지 |

### 3.2 신규 API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/reports/{id}/finalize` | preliminary → final 전환 (원본 보존, 감사 로그, 알림) |

### 3.3 DB 마이그레이션 (배포 시 실행)

```sql
ALTER TABLE reports ADD COLUMN preliminary_content JSONB;
```

---

## 4. Gap Analysis Results

### 초기 분석: 93% (13/14)

| Gap | 내용 | 영향 |
|-----|------|:----:|
| B6 | PreliminaryDiff가 별도 파일이 아닌 ReportPanel 인라인 | Low |

### Act 후: 100% (14/14)

B6 수정 — `components/PreliminaryDiff.tsx`로 분리, ReportPanel에서 import

---

## 5. Feature Checklist

| # | 기능 | Status |
|---|------|:------:|
| 1 | 예비 서명 (`as_preliminary=true`) | ✅ (기존) |
| 2 | `finalize` API (preliminary → final) | ✅ |
| 3 | 예비 판독 원본 보존 (`preliminary_content`) | ✅ |
| 4 | `_to_response` 3필드 확장 | ✅ |
| 5 | 예비 서명 시 전문의 알림 | ✅ |
| 6 | next-unread에서 preliminary 제외 | ✅ |
| 7 | 뷰어: `sign(asPreliminary)` 파라미터 | ✅ |
| 8 | 뷰어: `finalize()` 메서드 | ✅ |
| 9 | 뷰어: 3버튼 Footer (임시/예비/최종) | ✅ |
| 10 | 뷰어: preliminary 수정 허용 + finalize 버튼 | ✅ |
| 11 | 뷰어: PreliminaryDiff 접기/펼치기 | ✅ |
| 12 | 뷰어: 서명 정보 확장 (예비판독자 표시) | ✅ |
| 13 | Admin: '예비 판독' 필터 탭 | ✅ |
| 14 | Admin: 예비 판독 건수 배지 | ✅ |

---

## 6. Bonus Features (Design 범위 외)

| 기능 | 위치 |
|------|------|
| `PreliminaryInfo` 안내 배너 | `PreliminaryDiff.tsx` |
| `Ctrl+P` 예비 서명 단축키 | `ReportPanel.tsx` |
| `Ctrl+Enter` 최종 서명 유지 | `ReportPanel.tsx` |

---

## 7. 배포 체크리스트

- [ ] DB 마이그레이션: `ALTER TABLE reports ADD COLUMN preliminary_content JSONB`
- [ ] 백엔드 코드 업로드 + 재시작
- [ ] WeRU.B Viewer 빌드 + 배포
- [ ] Admin 빌드 + 배포
- [ ] curl 검증: 예비 서명 → finalize → 원본 보존 확인

---

## 8. 잔여 백로그 (P2)

| # | 기능 | 대상 | 규모 |
|---|------|------|:----:|
| 1 | 판독 통계 (뷰어 접근) | 판독의 | 낮음 |
| 2 | 측정값 자동 리포트 삽입 | 판독의 | 중간 |
| 3 | 장비 전송 상태 모니터링 | 방사선사 | 중간 |
| 4 | STAT 자동 정렬 | 판독의 | 낮음 |
| 5 | 온콜 판독의 교대 | 관리자 | 중간 |
| 6 | DB 테이블 생성 (peer_review, dose, conferences) | 관리자 | 낮음 |

---

*Generated: 2026-05-20 | PDCA Cycle Complete*
