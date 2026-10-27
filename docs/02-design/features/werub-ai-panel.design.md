# WeRU.B AI Panel Extension — Design

**Feature**: AI 분석 뷰어 패널
**Phase**: Design
**Created**: 2026-05-19
**Plan**: `docs/01-plan/features/werub-ai-panel.plan.md`
**참조**: `docs/02-design/ohif-v3.12-architecture.md`, `memory/ohif_extension_lessons.md`

---

## 1. Extension 구조

```
extensions/werub-ai/
├── package.json
└── src/
    ├── id.ts                         # packageJson.name (교훈 #1)
    ├── index.ts                      # React.lazy 패턴 (교훈 #5)
    ├── getCommandsModule.ts          # runAiAnalysis 명령
    ├── panels/
    │   └── AiPanel.tsx               # 메인 패널
    ├── components/
    │   ├── AiActionButton.tsx        # 분석 버튼 (로딩 스피너)
    │   ├── AiResultCard.tsx          # 결과 표시 카드
    │   └── ServerStatus.tsx          # AI 서버 상태
    └── services/
        └── AiService.ts              # API 래퍼 (자체 이벤트, 교훈 #2)
```

---

## 2. 파일별 설계

### 2.1 `package.json`

```json
{
  "name": "@ohif/extension-werub-ai",
  "version": "1.0.0",
  "description": "WeRU.B AI Analysis Panel Extension",
  "license": "MIT",
  "main": "src/index.ts",
  "module": "src/index.ts",
  "engines": { "node": ">=14" },
  "peerDependencies": {
    "@ohif/ui-next": "3.12.0",
    "react": "18.3.1"
  }
}
```

### 2.2 `id.ts`

```typescript
import packageJson from '../package.json';
export const id = packageJson.name;
```

### 2.3 `index.ts`

```typescript
import { id } from './id';
import React from 'react';
import { AiService } from './services/AiService';
import getCommandsModule from './getCommandsModule';

export default {
  id,
  preRegistration({ servicesManager }) {
    try {
      servicesManager.registerService(AiService.REGISTRATION);
    } catch (e) {
      console.error('[werub-ai] AiService registration failed:', e);
    }
  },
  getPanelModule({ servicesManager, commandsManager }) {
    return [{
      name: 'aiPanel',
      iconName: 'tab-segmentation',   // 뇌 아이콘
      iconLabel: 'AI',
      label: 'AI 분석',
      component: (props) => {
        const AiPanel = React.lazy(() => import('./panels/AiPanel'));
        return React.createElement(React.Suspense,
          { fallback: React.createElement('div', { style: { padding: '16px', color: '#888' } }, '로딩 중...') },
          React.createElement(AiPanel, { ...props, servicesManager, commandsManager })
        );
      },
    }];
  },
  getCommandsModule,
};
```

### 2.4 `AiService.ts`

```typescript
class AiService {
  static REGISTRATION = {
    name: 'aiService',
    create: ({ servicesManager }) => new AiService(servicesManager),
  };

  // 이벤트 (자체 구현, PubSubService 사용 안 함 — 교훈 #2)
  subscribe(event, callback) → { unsubscribe }
  _emit(event, data)

  // API 메서드
  async analyzeStudy(studyUID: string): Promise<AiAnalysisResult>
  async compareStudies(studyUID: string): Promise<ComparisonResult>
  async soapSummary(findings, impression): Promise<SoapResult>
  async differentialDiagnosis(symptoms, findings): Promise<DdxResult>
  async getServerStatus(): Promise<ServerStatus>

  // Report 연동
  applyToReport(result: AiAnalysisResult): void
    → reportService.save({ findings, impression, recommendation })
}
```

### 2.5 `AiPanel.tsx` UI 구조

```
┌─────────────────────────────────┐
│ AI 분석          [🟢 서버 정상]  │  ← 헤더 + ServerStatus
├─────────────────────────────────┤
│                                 │
│ [🤖 AI 영상 분석]               │  ← AiActionButton (primary)
│  Study 영상을 AI로 분석합니다    │
│                                 │
│ [📊 이전 검사 비교]              │  ← AiActionButton
│  동일 환자의 이전 검사와 비교    │
│                                 │
│ [📝 SOAP 요약]                  │  ← AiActionButton (소견 필요)
│  소견을 SOAP 형식으로 정리      │
│                                 │
│ [🔬 감별진단]                   │  ← AiActionButton (소견 필요)
│  가능한 진단명을 제안합니다      │
│                                 │
├─────────────────────────────────┤
│ ┌─ 분석 결과 ─────────────────┐ │
│ │ 소견: 우상엽에 5mm 결절...   │ │  ← AiResultCard
│ │ 결론: 폐 결절 — 추적 관찰... │ │
│ │ [판독에 적용] [복사]         │ │
│ └─────────────────────────────┘ │
└─────────────────────────────────┘
```

### 2.6 `AiActionButton.tsx`

```typescript
interface Props {
  label: string;
  description: string;
  icon: string;
  loading: boolean;
  disabled: boolean;
  onClick: () => void;
  variant?: 'primary' | 'secondary';
}
```

- `loading` 시 스피너 표시, 버튼 비활성화
- `disabled` 시 회색 처리 + 툴팁 ("소견을 먼저 입력하세요")

### 2.7 `AiResultCard.tsx`

```typescript
interface Props {
  title: string;             // "AI 분석 결과"
  findings?: string;
  impression?: string;
  recommendation?: string;
  duration_ms?: number;
  onApplyToReport: () => void;  // "판독에 적용" 클릭
  onCopy: () => void;           // 클립보드 복사
}
```

### 2.8 `ServerStatus.tsx`

```typescript
// GET /pacs-api/api/v1/ai/server-status 결과 표시
// 🟢 정상 | 🟡 로딩 중 | 🔴 오프라인
```

### 2.9 `getCommandsModule.ts`

```typescript
definitions: {
  runAiAnalysis: {
    commandFn: () => aiService.analyzeStudy(currentStudyUID),
  },
}
```

---

## 3. Report Panel 연동

### 이벤트 흐름

```
AiPanel                    AiService                  ReportService
  │                          │                           │
  │ ── [AI 분석 클릭] ──→    │                           │
  │                          │ ── POST /analyze ──→ API  │
  │                          │ ←── result ──────────     │
  │ ←── 'analysisComplete'   │                           │
  │                          │                           │
  │ ── [판독에 적용] ──→     │                           │
  │                          │ ── applyToReport() ──→    │
  │                          │                    save({ findings, impression })
  │                          │                           │ ── 'reportSaved' ──→
```

### ReportService 접근

```typescript
// AiService에서 ReportService 접근
const { reportService } = this.servicesManager.services;
if (reportService) {
  await reportService.save({ findings, impression, recommendation });
}
```

---

## 4. Mode 등록

```typescript
// modes/longitudinal/src/index.ts
extensionDependencies: {
  ...basicDependencies,
  '@ohif/extension-measurement-tracking': '^3.0.0',
  '@ohif/extension-werub-report': '^1.0.0',
  '@ohif/extension-werub-ai': '^1.0.0',     // 추가
},

rightPanels: [
  cornerstone.segmentation,
  tracked.measurements,
  '@ohif/extension-werub-report.panelModule.reportPanel',
  '@ohif/extension-werub-ai.panelModule.aiPanel',      // 추가
],
```

### pluginConfig.json

```json
{
  "packageName": "@ohif/extension-werub-ai",
  "version": "1.0.0"
}
```

---

## 5. 구현 체크리스트

### Phase 1: 스캐폴딩 (0.5일)
- [ ] `extensions/werub-ai/package.json`
- [ ] `src/id.ts` (packageJson.name)
- [ ] `src/index.ts` (React.lazy 패턴)
- [ ] `pluginConfig.json`에 등록
- [ ] `modes/longitudinal` extensionDependencies + rightPanels 추가
- [ ] 빈 Extension 빌드 성공 확인

### Phase 2: AiService (0.5일)
- [ ] `services/AiService.ts` — 자체 이벤트 시스템
- [ ] analyzeStudy, compareStudies, soapSummary, differentialDiagnosis
- [ ] getServerStatus
- [ ] applyToReport (ReportService 연동)
- [ ] preRegistration 등록

### Phase 3: AiPanel + 컴포넌트 (1일)
- [ ] `panels/AiPanel.tsx` — Study UID 감지, 서비스 구독
- [ ] `components/AiActionButton.tsx` — 로딩/비활성 상태
- [ ] `components/AiResultCard.tsx` — 결과 표시 + 적용/복사
- [ ] `components/ServerStatus.tsx` — 서버 상태 인디케이터

### Phase 4: 연동 + 빌드 (0.5일)
- [ ] Report Panel 결과 자동 전달 테스트
- [ ] getCommandsModule 등록
- [ ] 빌드 성공 확인

### Phase 5: 배포 (0.5일)
- [ ] build.sh에 werub-ai 복사 단계 추가
- [ ] 서버 배포 + 동작 확인

---

*다음 단계: `/pdca do werub-ai-panel`*
