# WeRU.B Report Extension — Plan

**Feature**: Report Panel을 OHIF Extension API로 전환
**Status**: Plan
**Created**: 2026-05-18
**Priority**: P1

---

## 1. 배경 및 목표

### 현재 문제
- `report-panel.js` (397줄)가 바닐라 JS IIFE로 OHIF에 스크립트 주입됨
- `innerHTML` 직접 조작, `setInterval` 폴링, 글로벌 스코프 오염
- OHIF React 생태계와 분리되어 있어 모달 충돌, 스타일 충돌 발생 이력
- 테스트 불가, 유지보수 어려움

### 목표
바닐라 JS → OHIF Extension API (React) 전환:
- OHIF 사이드 패널로 네이티브 통합
- React 컴포넌트 + 서비스 패턴
- OHIF 서비스 (UINotification, Modal, Panel) 활용
- Mode에 등록하여 자동 로딩

### 비목표 (Scope Out)
- AI 분석 패널 (별도 Extension으로 추후 개발)
- 음성입력 (admin 판독뷰에만 존재, 뷰어에는 불필요)
- SOAP/감별진단 (admin 판독뷰 기능)

---

## 2. 현재 report-panel.js 기능 목록

| # | 기능 | API | 전환 대상 |
|---|------|-----|:---------:|
| 1 | JWT 로그인 | `POST /auth/login` | ReportService |
| 2 | 리포트 조회 | `GET /reports?study_uid=` | ReportService |
| 3 | 리포트 생성 | `POST /reports` | ReportService |
| 4 | 리포트 수정 | `PATCH /reports/{id}` | ReportService |
| 5 | 판독 서명 | `POST /reports/{id}/sign` | ReportService |
| 6 | 수정본 추가 | `POST /reports/{id}/addendum` | ReportService |
| 7 | 템플릿 로딩 | `GET /templates` | ReportService |
| 8 | 템플릿 적용 | - | ReportPanel |
| 9 | 매크로 삽입 | - | ReportPanel |
| 10 | Study UID 감지 | URL 폴링 (1.5초) | React useEffect |
| 11 | 상태 배지 | draft/final/unread | ReportPanel |
| 12 | 토글 버튼 | FAB (우하단) | OHIF 사이드 패널 탭 |
| 13 | Ctrl+Enter 서명 | keydown 리스너 | React useEffect |
| 14 | 토스트 알림 | 커스텀 DOM | UINotificationService |

---

## 3. 기술 설계 개요

### 3.1 Extension 구조

```
extensions/werub-report/
├── package.json
├── src/
│   ├── index.ts                    # Extension 엔트리포인트
│   ├── getPanelModule.tsx          # 패널 등록
│   ├── getCommandsModule.ts        # 명령어 (save, sign)
│   ├── panels/
│   │   └── ReportPanel.tsx         # 메인 React 컴포넌트 (~200줄)
│   ├── components/
│   │   ├── ReportForm.tsx          # 소견/결론/권고 폼
│   │   ├── TemplateSelector.tsx    # 템플릿 선택
│   │   ├── StatusBadge.tsx         # 판독 상태 배지
│   │   └── LoginForm.tsx           # 인증 폼
│   └── services/
│       └── ReportService.ts        # API 래퍼 + 상태 관리
```

### 3.2 OHIF 통합 포인트

| OHIF 서비스 | 용도 |
|-------------|------|
| `panelService` | 우측 사이드 패널 등록 |
| `uiNotificationService` | 토스트 알림 |
| `uiModalService` | 로그인 모달 |
| `displaySetService` | 현재 Study UID 감지 |
| `hangingProtocolService` | 뷰어 상태 연동 |

### 3.3 Mode 등록

```typescript
// modes/werub-mode/src/index.ts
rightPanels: [
  '@ohif/extension-werub-report.panelModule.reportPanel',
],
```

---

## 4. 구현 순서

| Phase | 작업 | 예상 |
|:-----:|------|:----:|
| 1 | Extension 스캐폴딩 + package.json + index.ts | 0.5일 |
| 2 | ReportService (API 래퍼, 상태 관리) | 1일 |
| 3 | ReportPanel React 컴포넌트 | 1.5일 |
| 4 | Mode 등록 + 빌드 테스트 | 0.5일 |
| 5 | 기존 report-panel.js 로더 제거 | 0.5일 |
| 6 | 서버 배포 + 검증 | 0.5일 |
| **합계** | | **4.5일** |

---

## 5. 리스크

| 리스크 | 영향 | 대응 |
|--------|------|------|
| OHIF Extension API 변경 (v3.12→v3.13) | 빌드 실패 | 버전 고정, 패치 전략 |
| 인증 토큰 관리 | 보안 | ReportService에 토큰 갱신 로직 |
| Study UID 감지 타이밍 | UX | displaySetService 이벤트 구독 |
| 기존 admin 판독뷰와 기능 중복 | 혼란 | 역할 분리: 뷰어=간편판독, admin=상세판독 |

---

## 6. 성공 기준

- [ ] OHIF 사이드 패널에서 판독 리포트 CRUD 동작
- [ ] 바닐라 JS (report-panel.js) 완전 제거
- [ ] 빌드 성공 + 서버 배포
- [ ] 기존 기능 14개 모두 동작 (위 표 참조)
- [ ] `setInterval` 폴링 제거 → React 이벤트 기반

---

*다음 단계: `/pdca design werub-report-extension`*
