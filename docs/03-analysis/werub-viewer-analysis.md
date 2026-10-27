# WeRU.B Viewer 상세 분석서

**작성일**: 2026-06-05
**분석 대상**: `werub-viewer/` (OHIF v3.12.0 source build, Cornerstone3D)
**분석 범위**: 빌드 파이프라인, OHIF 소스 패치, 3개 커스텀 Extension, reading 모드, 앱 config, AI/판독 연동, 표준 SEG/SR 렌더링 능력, 배포 상태
**방법**: 소스 전수 정독(2,655 LOC) + `.ohif-src` OHIF 원본 대조 + 운영 서버 실측

---

## 0. 핵심 요약 (Executive Summary)

| # | 발견 | 심각도 | 비고 |
|---|------|:---:|------|
| F1 | **배포 번들이 ~3주 stale** — 서버 번들 "WeRU.B 7.0"(2026-05-19 빌드), v10.0/v10.1 미반영 | 🔴 High | 컨테이너 "Up 2 weeks", 소스엔 미빌드 변경 존재 |
| F2 | **뷰어 ↔ v10.1 표준 SEG/SR 워크플로우 단절** — AI 패널은 동기 LLM 엔드포인트 + 텍스트 리포트만. 표준 추론 잡(`/inferences`)을 트리거/대기/표시하지 않음 | 🔴 High | OHIF는 렌더 능력 보유(F4), 그러나 생성·노출 경로 없음 |
| F3 | **`onError`가 핵심 에러를 억제** (`extensionDependencies`, `Cannot read properties of undefined`) | 🟠 Med | 모드/확장 로딩 실패를 가림 |
| F4 | **SEG/SR/RT/PDF 렌더링 능력은 존재** — `modes/basic`(reading 베이스)에 전 SOPClassHandler 포함 | 🟢 양호 | P0은 "활성화·검증" 중심 |
| F5 | **모드 이중화** — `werub-reading`(신규) + 패치된 `longitudinal` 둘 다 WeRU.B 패널 주입 | 🟡 Low | 혼란/중복, 동작은 함 |
| F6 | **인증 처리 불일치** — AiService/ReportService는 Bearer 토큰 사용, WorkList 패치 fetch는 무인증 → v10.0 하에서 401 | 🟠 Med | 판독 상태 배지 미표시 가능 |
| F7 | **MPR/MIP 미설정** (pacs-plan v1.0 scope) | 🟠 Med | 툴바/뷰포트/단축키 어디에도 없음 |
| F8 | **버전 라벨 하드코딩 stale** — 패치 `WERUB_VERSION='7.0'`, `BUILD_DATE='2026.05.19'` | 🟡 Low | About 모달이 7.0 표시 |
| F9 | **이중 SR 경로** — AI `saveAsSR`는 `/reports/structured`(자체 스키마), v10.1 표준 빌더(`dicom_ai_standard`)와 별개 | 🟠 Med | 표준 SR 미생성 |

> **결론**: 뷰어의 *기반 능력*(OHIF 표준 핸들러, 한국형 커스터마이징, 판독/AI 패널)은 견고하나, **(1) 배포가 낡았고 (2) v10.1 표준 AI 결과(SEG/SR)를 생성·표시하는 워크플로우가 연결돼 있지 않다.** 개선 1순위는 "재빌드·배포 + 표준 결과 루프 연결"이며, 신규 대형 개발보다 **활성화·연결·검증** 비중이 크다.

---

## 1. 아키텍처 개요

### 1.1 빌드 파이프라인 (`build.sh`, 9단계)
```
OHIF v3.12.0 clone(.ohif-src) → 브랜딩 → config(default.js) → ko-KR i18n(네임스페이스 분할)
→ 소스 패치(werub-source.patch) → 커스텀 ext/mode 복사 → HTML title → yarn build → dist/
```
- **소스 레벨 빌드**: 런타임 주입이 아니라 OHIF 소스 트리에 병합 후 번들. (메모리 교훈: 번들 직접 패치는 SW/캐시로 미반영 → 반드시 `build.sh` 재빌드)
- 산출물 `dist/` → `openpacs-werub` 이미지(nginx) → `/werub-viewer/`.
- `.ohif-src` 클론이 로컬에 캐시됨(재빌드 가속).

### 1.2 레이어 구성
| 레이어 | 구성요소 |
|---|---|
| OHIF 코어 | v3.12.0 (extension-default, -cornerstone, -dicom-seg/-sr/-rt/-pdf/-video, measurement-tracking) |
| 소스 패치 | About 모달, longitudinal 모드(패널 주입), WorkList(판독상태 컬럼), formatDate(YYYY-MM-DD), formatPN(한글 인식), filtersMeta(한국 모달리티 우선), ErrorBoundary |
| 커스텀 Extension | `werub-report`, `werub-ai`, `shared`(BaseService 유틸) |
| 커스텀 Mode | `werub-reading` (`@ohif/mode-basic` 확장) |
| 런타임 config | `werub-app-config.js` — 브랜딩/CSS/W-L 프리셋/데이터소스/단축키/멀티모니터/WebSocket |

---

## 2. 컴포넌트별 분석

### 2.1 `werub-ai` Extension (AiPanel + AiService, ~440 LOC)
- **AiService API** (전부 동기 fetch, `/pacs-api/api/v1`):
  - `analyzeStudy` → `/ai/analyze-and-draft`
  - `compareStudies` → `/ai/compare-studies`
  - `soapSummary`, `differentialDiagnosis`, `getServerStatus`
  - `getProductionPipeline` → `/ai/orchestration/production`, `runPipeline` → `/ai/orchestration/run`
  - `saveAsSR` → **`/reports/structured`** (표준 빌더 아님 — F9)
  - `applyToReport` → `/ai/apply-to-report` + OHIF reportService + BroadcastChannel/localStorage 크로스탭 싱크
- **인증**: `localStorage('pacs_token')` → Bearer (일관).
- **갭**:
  - ❌ 비동기 추론 잡 API(`POST /inferences`, v10.1 수리분) 미사용 → 진행률/SEG 생성 모델 결과 미연동 (F2)
  - ❌ `ws/ai_progress` WebSocket 미구독
  - ❌ DICOM SEG 로드/오버레이/토글 코드 전무 → 표준 분할 결과 미표시
  - 패널 아이콘 `tab-segmentation` 재사용(혼동 소지)

### 2.2 `werub-report` Extension (ReportPanel + ReportService, ~570 LOC)
- **ReportService**: load/save(PATCH or POST)/sign(예비)/finalize/addendum/templates, 401→자동 로그아웃, 커스텀 이벤트(PubSubService 미사용 — OHIF 제약 회피).
- 예비판독 diff, 매크로바, 템플릿 선택, 상태 배지 컴포넌트.
- **평가**: 견고·완성도 높음. 갭 적음. (측정값→리포트 자동연동은 미구현 — P2)

### 2.3 `shared` (BaseService.ts, 58 LOC)
- 공통 서비스 베이스 유틸. OHIF extension 아님.

### 2.4 `werub-reading` Mode
- `@ohif/mode-basic` 확장(존재 확인) → **SEG/SR/RT/PDF/video/pmap SOPClassHandler 상속** (F4).
- 우측 패널: `report, ai, measurements, cornerstone.segmentation`. 좌측: 썸네일.
- HP: `mnGrid`, `hpCompare` (2종).
- **이중화(F5)**: `werub-source.patch`가 `longitudinal` 모드에도 동일 패널 주입 → 두 모드 공존.

### 2.5 `werub-app-config.js` (518 LOC)
- **W/L 프리셋**: 모달리티별 충실 (CT 7, MR 3, PT 4, CR/DX/MG/US). ✅
- **데이터소스**: dicomweb(`/dicom-web` QIDO/WADO, `/wado`), `bulkDataURI.enabled:false`.
- **단축키**: 회전/반전/줌/W-L프리셋(1-5)/HP스테이지/undo. MPR 미바인딩(F7).
- **런타임 주입 3종**(OHIF 비표준):
  - N키 → `/reports/next-unread` (Bearer ✅)
  - M키 → 보조창 open
  - WebSocket → `/pacs-api/ws/notifications` (긴급소견 브라우저 알림)
- **`onError` 억제(F3)**: `ImageOverlayViewerTool`, `Cannot read properties of undefined`, `extensionDependencies` 메시지를 삼킴 → 로딩 실패 은폐.

### 2.6 OHIF 소스 패치 (`werub-source.patch`, 15KB)
- **About 모달**: WeRU.B 버전·라이선스(OHIF MIT/Cornerstone/Orthanc GPLv3). `WERUB_VERSION='7.0'` 하드코딩(F8).
- **longitudinal 모드**: rightPanels에 report/ai 패널 추가(F5).
- **pluginConfig.json**: werub-report/-ai 확장 + mode-werub-reading 등록.
- **WorkList**: 판독상태 배지 컬럼 + `/reports/status-batch` fetch — **무인증(F6)**. 한국 모달리티 우선 정렬, 컬럼폭 조정.
- **formatDate**: `YYYY-MM-DD`. **formatPN**: 한글이면 `홍^길동→홍길동`, 서양식 `Last, First`.
- ErrorBoundary 문자열 버그 수정.

---

## 3. 표준 SEG/SR 렌더링 능력 — 상세 판정 (P0 핵심)

| 질문 | 판정 | 근거 |
|---|:---:|---|
| 뷰어가 표준 SEG(66.4)를 **렌더 가능?** | ✅ 능력 보유 | `modes/basic`에 `extension-cornerstone-dicom-seg` SOPClassHandler+viewport |
| 뷰어가 TID 1500 SR(88.33)을 **렌더 가능?** | ✅ 능력 보유 | `extension-cornerstone-dicom-sr` SOPClassHandler(+3D)+viewport |
| AI 패널이 표준 SEG/SR을 **생성/트리거?** | ❌ 없음 | AiService에 `/inferences` 호출·SEG 처리 전무 (F2) |
| 생성된 SEG/SR이 **자동 로드·강조?** | ❌ 미연동 | 스터디 재로드 시 추가 시리즈로만 나타남, 패널 연계 없음 |
| AI `saveAsSR`이 **표준 SR 생성?** | ❌ 아님 | `/reports/structured` 자체 스키마 (F9) |

**해석**: OHIF 기반 렌더링 파이프라인은 표준 객체를 *그릴 수 있다*. 그러나 v10.1 백엔드가 만든 SEG/SR은 **추론 워커가 Orthanc에 저장한 뒤 사용자가 스터디를 재로드해야** 추가 시리즈로 보일 뿐, 뷰어 AI 패널 워크플로우(분석→오버레이→판독반영)와 **연결돼 있지 않다.** → P0-1은 (a) 표준 추론 잡 트리거/대기, (b) 결과 SEG 오버레이·SR 측정 자동 로드·강조, (c) 1회 E2E 실증.

---

## 4. 배포 상태 분석

| 항목 | 값 | 평가 |
|---|---|---|
| 서버 번들 버전 | "WeRU.B 7.0" (About) | 🔴 stale (현 제품 v10.1) |
| 빌드 추정일 | 2026-05-19 (`BUILD_DATE`) | 🔴 ~3주 경과 |
| 컨테이너 | `openpacs-werub` Up 2 weeks | 미재빌드 |
| 미반영 변경 | v10.0(2026-06-01, 보안) + v10.1(표준 SEG/SR) | 소스엔 있음, 번들엔 없음 |

→ **배포된 뷰어는 v7.x 시점 산출물**. 소스의 v10.0 보안/UX 변경조차 미반영. 표준 SEG/SR은 차치하고, **재빌드·배포가 선행 필요**.

---

## 5. 기술부채 / 리스크

- **R1 (High)**: 에러 억제(F3) + stale 배포(F1) 조합 → 실제 동작과 소스 괴리를 진단하기 어려움. "동작한다"는 인상이 실측과 다를 수 있음.
- **R2 (Med)**: 모드 이중화(F5) — 어느 모드가 기본 진입인지/유지보수 대상인지 불명확.
- **R3 (Med)**: 인증 불일치(F6) — v10.0 보안 강화 후 무인증 fetch가 조용히 실패(`onError` 억제와 겹쳐 무증상).
- **R4 (Low)**: 버전 라벨 수동 관리(F8) → 릴리즈마다 누락 위험.
- **R5 (제약)**: OHIF v3.12 버전 고정 필수 — SEG/SR/RT 확장 호환성 유지. 메이저 업글 시 재검증 대규모.

---

## 6. 분석 결론 → 개선 우선순위 (기획서 입력)

1. **P0-A 재빌드·배포** — 소스(v10.0/v10.1)를 반영한 번들 빌드·배포 + 버전 라벨 v10.1 동기화. *(다른 모든 개선의 전제)*
2. **P0-B 표준 SEG/SR 루프 연결·실증** — AI 패널이 표준 추론 결과를 트리거/대기/오버레이·측정 자동 로드. OHIF 능력은 보유(F4) → 연결·검증 중심.
3. **P1 진단 위생** — `onError` 억제 완화(화이트리스트 최소화) + 모드 이중화 정리 + WorkList 인증 수정(F6).
4. **P1 MPR/MIP 활성화**(F7) + 모달리티별 HP 확충.
5. **P2** — 측정→구조화 SR 연동, 비표준 검증 경고 인뷰어 배지, Key Image, saveAsSR 표준 빌더 통합(F9).

> 상세 로드맵은 `docs/01-plan/werub-viewer-improvement-plan.md` 참조 (본 분석으로 P0 항목을 "확장 추가"에서 "재빌드+연결+검증"으로 정정).

---

## 부록: 분석 범위 외(후속 정독 권장)
- `AiPanel.tsx`(304), `ReportPanel.tsx`(355) UI 로직 상세 — 본 분석은 서비스/연동/구성 계층 중심.
- `.ohif-src`의 `modes/segmentation`, `tmtv` — MPR/세그 편집 기능 차용 가능성 검토.

---

## 7. 구현·검증 결과 (2026-06-06 추가)

분석 직후 P0/P1 일부를 구현·배포하고 브라우저 실측으로 검증했다. 그 과정에서 **2건의 분석 정정**이 나왔다.

### 처리 완료
| 발견 | 조치 | 검증 |
|---|---|---|
| F1 stale 배포 | OHIF 재빌드(node_modules 캐시 ~10s) → v10.1 배포. About 라벨 v10.1 | ✅ 브라우저 확인 |
| F2 표준 SR 워크플로우 단절 | **데이터**: 추론 1회 실행 → TID 1500 SR(88.33) 생성·Orthanc 저장·DICOMweb 조회 E2E ✅. **표시**: AI 패널 "🤖 저장된 AI 판독" 카드(`getStudyResult`→`/ai/jobs`) + **SR 텍스트 뷰포트 렌더** | ✅ 브라우저(SR 내용 렌더 확인) |
| F6 WorkList 무인증 | `/reports/status-batch`에 Bearer 토큰 추가 | ✅ 콘솔 401 사라짐 |
| F3 onError 과억제 | `Cannot read properties of undefined` 억제 제거(나머지 무해 2건 유지) | ✅ 배포 |
| **SR 뷰포트 크래시(신규 발견)** | `OHIFCornerstoneSRViewport` 라우팅 패치 — 재수화 가능 측정 없으면 **Text 뷰포트로 폴백**(측정 뷰포트 크래시 회피) | ✅ SR이 텍스트 문서로 렌더 |

### 분석 정정
- **F4 보강**: SEG/SR 핸들러 존재는 맞으나, OHIF SR 뷰포트는 **두 종류**(Measurement/Text)이며 `isImagingMeasurementReport`로 라우팅. 우리 **범주형 AI SR(SCOORD 좌표 없음)** 은 측정 뷰포트로 가서 `not rehydratable`→크래시. → **올바른 표시는 Text 뷰포트 + AI 패널**(역할 분리). 라우팅 패치로 해결.
- **F7 철회(오류)**: "MPR 미설정"은 **오류**. `modes/basic`이 MPR toolGroup + **Layout/Crosshairs 툴바 버튼**을 제공하고 `werub-reading`이 상속 → **MPR 이미 가용**(Layout 버튼→MPR 레이아웃). 구현 불필요.

### 잔여
- SR Text 뷰포트의 `[IMAGE is not supported]`(근거영상 IMAGE 항목 인라인 미지원) + 잔여 토스트 1건 — onError 완화로 콘솔 노출되므로 다음 진단 시 가드.
- F5 모드 이중화 정리(저우선), F9 saveAsSR 표준 통합, 분할 모델 트랙(SEG 실증).

### SEG 실증 보류 사유
현재 활성 모델은 전부 **분류(classification)** — 마스크 미출력 → SEG 0개. 표준 SEG 표시 검증은 **분할 모델(마스크 출력)** 선행 필요(별도 트랙).
