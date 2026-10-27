# WeRU.B AI Panel Extension — Plan

**Feature**: AI 분석 결과를 OHIF 뷰어 사이드 패널로 통합
**Status**: Plan
**Created**: 2026-05-19
**Priority**: P1
**Prerequisite**: werub-report-extension (완료, 94%)

---

## 1. 배경 및 목표

### 현재 상태
- AI API 7개 엔드포인트 존재 (FastAPI, Phase 5에서 구현)
- AI 기능은 **admin 판독뷰**에서만 사용 가능 (reading/view/page.tsx)
- 뷰어(WeRU.B)에서는 AI 기능 접근 불가 → 판독의가 별도 창으로 이동해야 함

### 목표
Report Extension과 동일한 패턴으로 AI Panel Extension을 만들어, **뷰어 사이드 패널에서 직접 AI 분석을 실행**하고 결과를 Report Panel에 연동.

### 비목표 (Scope Out)
- 모델 관리 UI (admin에서 처리)
- 학습/파인튜닝 기능
- 실시간 추론 진행률 (WebSocket, 추후)

---

## 2. 기존 AI API 목록

### 분석 API (`/pacs-api/api/v1/ai/`)

| # | API | 메서드 | 기능 | 입력 | 출력 |
|---|-----|--------|------|------|------|
| 1 | `/analyze-and-draft` | POST | 영상 AI 분석 + 판독 초안 | `study_instance_uid` | findings, impression, recommendations |
| 2 | `/compare-studies` | POST | 이전 검사 비교 | `current_study_uid` | comparison.text, progression |
| 3 | `/soap-summary` | POST | SOAP 요약 생성 | findings, impression | summary (S/O/A/P), icd_codes |
| 4 | `/differential-diagnosis` | POST | 감별진단 | symptoms, findings | differential_diagnosis[] |
| 5 | `/explain-findings` | POST | 소견 해석 | findings text | 설명 텍스트 |
| 6 | `/compare-report` | POST | 리포트 비교 | report_id | 비교 결과 |
| 7 | `/server-status` | GET | AI 서버 상태 | - | ollama/model 상태 |

### 추론 API (`/pacs-api/api/v1/ai-inference/`)

| # | API | 기능 |
|---|-----|------|
| 1 | `POST /inference` | 추론 작업 생성 |
| 2 | `GET /jobs` | 추론 작업 목록 |
| 3 | `GET /jobs/{id}` | 작업 상태 조회 |

---

## 3. AI Panel 기능 목록

| # | 기능 | API | 우선순위 |
|---|------|-----|:--------:|
| 1 | AI 분석 (영상 분석 + 판독 초안) | `/analyze-and-draft` | P0 |
| 2 | 이전 검사 비교 | `/compare-studies` | P0 |
| 3 | SOAP 요약 | `/soap-summary` | P1 |
| 4 | 감별진단 | `/differential-diagnosis` | P1 |
| 5 | 결과를 Report Panel에 자동 전달 | ReportService 연동 | P0 |
| 6 | AI 서버 상태 표시 | `/server-status` | P2 |
| 7 | 추론 작업 이력 | `/jobs` | P2 |

---

## 4. Report Panel 연동 설계

```
┌──────────────────┐     결과 전달      ┌──────────────────┐
│   AI Panel       │ ─────────────────→ │  Report Panel    │
│                  │                    │                  │
│  [AI 분석] 클릭  │  findings →        │  소견 자동 입력  │
│  [감별진단] 클릭 │  impression →      │  결론 자동 입력  │
│  [SOAP] 클릭     │  recommendation →  │  권고 자동 입력  │
└──────────────────┘                    └──────────────────┘
         ↕ ReportService 이벤트
```

AI 분석 결과를 `reportService`에 전달하여 Report Panel의 폼 필드에 자동 반영.

---

## 5. Extension 구조 (Report Extension 패턴 재사용)

```
extensions/werub-ai/
├── package.json
└── src/
    ├── id.ts
    ├── index.ts                    # preRegistration + getPanelModule
    ├── getCommandsModule.ts        # runAiAnalysis 명령
    ├── panels/
    │   └── AiPanel.tsx             # 메인 패널 (~150줄)
    ├── components/
    │   ├── AiActionButton.tsx      # 분석 버튼 (로딩 상태 포함)
    │   ├── AiResultCard.tsx        # 결과 표시 카드
    │   └── ServerStatus.tsx        # AI 서버 상태 인디케이터
    └── services/
        └── AiService.ts            # API 래퍼 + 이벤트
```

---

## 6. 구현 순서

| Phase | 작업 | 예상 |
|:-----:|------|:----:|
| 1 | Extension 스캐폴딩 (Report Extension 복제) | 0.5일 |
| 2 | AiService (7개 API 래퍼) | 0.5일 |
| 3 | AiPanel + 컴포넌트 | 1일 |
| 4 | Report Panel 연동 (결과 자동 전달) | 0.5일 |
| 5 | Mode 등록 + 빌드 + 배포 | 0.5일 |
| **합계** | | **3일** |

---

## 7. 리스크

| 리스크 | 대응 |
|--------|------|
| AI 서버(Ollama) 미구동 시 | serverStatus 체크 후 비활성화 표시 |
| 분석 시간 지연 (>10초) | 로딩 스피너 + 취소 버튼 |
| Report Panel과 동시 열기 시 패널 공간 부족 | 탭 전환 방식 (한 번에 하나만 표시) |

---

## 8. 성공 기준

- [ ] 뷰어에서 AI 분석 실행 (Study UID 자동 감지)
- [ ] 분석 결과를 Report Panel에 자동 반영
- [ ] 4개 AI 기능 (분석, 비교, SOAP, 감별진단) 동작
- [ ] 빌드 + 서버 배포

---

*다음 단계: `/pdca design werub-ai-panel`*
