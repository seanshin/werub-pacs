# WeRU.B Report Extension — Design

**Feature**: Report Panel OHIF Extension 전환
**Phase**: Design
**Created**: 2026-05-19
**Plan**: `docs/01-plan/features/werub-report-extension.plan.md`

---

## 1. Extension 패키지 구조

```
extensions/werub-report/
├── package.json
└── src/
    ├── id.ts                         # Extension ID 상수
    ├── index.ts                      # Extension 엔트리포인트
    ├── getPanelModule.tsx            # 패널 모듈 등록
    ├── getCommandsModule.ts          # 키보드 단축키 명령
    ├── panels/
    │   └── ReportPanel.tsx           # 메인 패널 (~200줄)
    ├── components/
    │   ├── ReportForm.tsx            # 소견/결론/권고 입력 폼
    │   ├── TemplateSelector.tsx      # 템플릿 목록 + 적용
    │   ├── StatusBadge.tsx           # 판독 상태 배지 (final/draft/unread)
    │   └── MacroBar.tsx             # 매크로 단축어 바
    └── services/
        └── ReportService.ts          # API 래퍼 + 이벤트 발행
```

---

## 2. 파일별 상세 설계

### 2.1 `package.json`

```json
{
  "name": "@ohif/extension-werub-report",
  "version": "1.0.0",
  "description": "WeRU.B Reading Report Panel Extension",
  "license": "MIT",
  "main": "dist/ohif-extension-werub-report.umd.js",
  "module": "src/index.ts",
  "engines": { "node": ">=14" },
  "keywords": ["ohif-extension"],
  "peerDependencies": {
    "@ohif/core": "3.12.0",
    "@ohif/ui": "3.12.0",
    "@ohif/ui-next": "3.12.0",
    "react": "18.3.1"
  }
}
```

### 2.2 `id.ts`

```typescript
export const id = 'werub-report';
```

### 2.3 `index.ts` — Extension 엔트리포인트

```typescript
import { id } from './id';
import getPanelModule from './getPanelModule';
import getCommandsModule from './getCommandsModule';
import { ReportService } from './services/ReportService';

export default {
  id,

  preRegistration({ servicesManager }) {
    servicesManager.registerService(ReportService.REGISTRATION);
  },

  getPanelModule,
  getCommandsModule,
};
```

### 2.4 `getPanelModule.tsx` — 패널 등록

```typescript
import React from 'react';
import { Types } from '@ohif/core';
import ReportPanel from './panels/ReportPanel';

function getPanelModule({
  commandsManager,
  extensionManager,
  servicesManager,
}): Types.Panel[] {
  return [
    {
      name: 'reportPanel',
      iconName: 'tab-linear',         // OHIF 내장 아이콘
      iconLabel: '판독',
      label: '판독 리포트',
      component: props => (
        <ReportPanel
          {...props}
          commandsManager={commandsManager}
          servicesManager={servicesManager}
        />
      ),
    },
  ];
}

export default getPanelModule;
```

**패널 모듈 ID**: `werub-report.panelModule.reportPanel`

### 2.5 `getCommandsModule.ts` — 키보드 단축키

```typescript
function getCommandsModule({ servicesManager }) {
  return {
    definitions: {
      saveReport: {
        commandFn: () => {
          const { reportService } = servicesManager.services;
          reportService.save();
        },
      },
      signReport: {
        commandFn: () => {
          const { reportService } = servicesManager.services;
          reportService.sign();
        },
      },
    },
    defaultContext: 'VIEWER',
  };
}

export default getCommandsModule;
```

### 2.6 `ReportService.ts` — API + 상태 관리

```typescript
// 상태
interface ReportState {
  token: string | null;
  currentReport: Report | null;
  templates: Template[];
  studyUID: string | null;
  loading: boolean;
}

// 이벤트
enum EVENTS {
  REPORT_LOADED = 'reportLoaded',
  REPORT_SAVED = 'reportSaved',
  REPORT_SIGNED = 'reportSigned',
  AUTH_CHANGED = 'authChanged',
}

// API 래퍼
class ReportService {
  static REGISTRATION = {
    name: 'reportService',
    create: ({ servicesManager }) => new ReportService(servicesManager),
  };

  // API 엔드포인트
  private API = '/pacs-api/api/v1';

  // 메서드
  async login(username: string, password: string): Promise<boolean>;
  async loadReport(studyUID: string): Promise<void>;
  async save(data: Partial<Report>): Promise<Report>;
  async sign(): Promise<Report>;
  async addendum(): Promise<Report>;
  async loadTemplates(): Promise<Template[]>;

  // 이벤트
  subscribe(event: EVENTS, callback: Function): { unsubscribe: Function };
}
```

### 2.7 `ReportPanel.tsx` — 메인 패널 컴포넌트

```
┌─────────────────────────────┐
│ 📋 판독 리포트    [상태배지] │  ← 헤더
├─────────────────────────────┤
│ [CT] [MR] [US] [Chest]     │  ← TemplateSelector
├─────────────────────────────┤
│ 소견 (Findings)             │
│ ┌─────────────────────────┐ │
│ │                         │ │  ← textarea
│ └─────────────────────────┘ │
│ 결론 (Impression)           │
│ ┌─────────────────────────┐ │
│ │                         │ │  ← textarea
│ └─────────────────────────┘ │
│ 권고 사항                   │
│ ┌─────────────────────────┐ │
│ │                         │ │  ← textarea
│ └─────────────────────────┘ │
│ 긴급도 [normal ▼]          │
├─────────────────────────────┤
│ [정상] [비긴급] [간기능↓]   │  ← MacroBar
├─────────────────────────────┤
│ [임시 저장]  [✍️ 서명]      │  ← 푸터
└─────────────────────────────┘
```

**React hooks 구성**:
```typescript
function ReportPanel({ servicesManager, commandsManager }) {
  const { reportService, displaySetService, uiNotificationService } = 
    servicesManager.services;
  const [viewportGrid] = useViewportGrid();

  // Study UID 감지 — displaySetService에서
  const [studyUID, setStudyUID] = useState<string | null>(null);

  useEffect(() => {
    const activeViewport = viewportGrid.viewports.get(viewportGrid.activeViewportId);
    if (!activeViewport?.displaySetInstanceUIDs?.length) return;
    const ds = displaySetService.getDisplaySetByUID(activeViewport.displaySetInstanceUIDs[0]);
    if (ds?.StudyInstanceUID) setStudyUID(ds.StudyInstanceUID);
  }, [viewportGrid.activeViewportId, viewportGrid.viewports]);

  // Study 변경 시 리포트 로딩
  useEffect(() => {
    if (studyUID) reportService.loadReport(studyUID);
  }, [studyUID]);

  // 서비스 이벤트 구독
  useEffect(() => {
    const subs = [
      reportService.subscribe(EVENTS.REPORT_LOADED, (report) => { ... }),
      reportService.subscribe(EVENTS.REPORT_SAVED, () => { 
        uiNotificationService.show({ title: '저장', message: '임시 저장됨', type: 'success' });
      }),
    ];
    return () => subs.forEach(s => s.unsubscribe());
  }, []);

  // Ctrl+Enter 단축키
  useEffect(() => {
    const handler = (e) => {
      if (e.ctrlKey && e.key === 'Enter') commandsManager.runCommand('signReport');
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);
}
```

---

## 3. Mode 등록 설계

기존 OHIF basic 모드를 복제하여 `werub-reading` 모드를 생성하거나, 기존 모드의 `rightPanels`에 추가합니다.

### 3.1 기존 모드에 추가 (최소 변경)

```typescript
// modes/longitudinal/src/index.ts 수정
rightPanels: [
  tracked.measurements,
  'werub-report.panelModule.reportPanel',  // 추가
],
```

### 3.2 extensionDependencies

```typescript
extensionDependencies: {
  '@ohif/extension-default': '^3.0.0',
  '@ohif/extension-cornerstone': '^3.0.0',
  '@ohif/extension-measurement-tracking': '^3.0.0',
  'werub-report': '^1.0.0',  // 추가
},
```

---

## 4. 인증 흐름

```
┌──────────┐     ┌──────────────┐     ┌───────────┐
│ 패널 열림 │────→│ token 확인   │────→│ API 호출  │
└──────────┘     │ (localStorage)│     └───────────┘
                 └──────┬───────┘
                        │ 없음/만료
                        ▼
                 ┌──────────────┐
                 │ 로그인 폼    │
                 │ 표시         │
                 └──────┬───────┘
                        │ POST /auth/login
                        ▼
                 ┌──────────────┐
                 │ token 저장   │
                 │ → API 호출   │
                 └──────────────┘
```

- 401 응답 시 자동 로그인 폼 표시
- token은 `localStorage.pacs_token`에 저장 (admin과 공유)

---

## 5. 기존 코드 제거 계획

| 제거 대상 | 시점 | 조건 |
|----------|------|------|
| `werub-viewer/config/werub-app-config.js`의 report-panel 로더 | Phase 5 | Extension 동작 확인 후 |
| `werub-viewer/extensions/report-panel.js` | Phase 5 | Extension 동작 확인 후 |
| `viewer/report-panel.js` (OHIF용) | 유지 | OHIF 백업 뷰어에서 사용 |

---

## 6. 빌드 통합

### build.sh 수정 불필요
- `extensions/*` glob에 자동 포함
- 별도 workspace 등록 불필요 (monorepo 자동 탐지)

### 패치 전략
- `werub-source.patch`에 mode 수정분 추가
- Extension 소스는 `.ohif-src/extensions/werub-report/`에 직접 생성

---

## 7. 구현 체크리스트

### Phase 1: 스캐폴딩 (0.5일)
- [ ] `extensions/werub-report/package.json`
- [ ] `extensions/werub-report/src/id.ts`
- [ ] `extensions/werub-report/src/index.ts`
- [ ] 빌드 성공 확인 (빈 Extension)

### Phase 2: ReportService (1일)
- [ ] `services/ReportService.ts` — 클래스 + REGISTRATION
- [ ] API 메서드: login, loadReport, save, sign, addendum, loadTemplates
- [ ] 이벤트 시스템 (subscribe/publish)
- [ ] preRegistration에서 서비스 등록

### Phase 3: ReportPanel (1.5일)
- [ ] `panels/ReportPanel.tsx` — 메인 컴포넌트
- [ ] `components/ReportForm.tsx` — textarea 폼
- [ ] `components/TemplateSelector.tsx` — 버튼 목록
- [ ] `components/StatusBadge.tsx` — 상태 표시
- [ ] `components/MacroBar.tsx` — 매크로 삽입
- [ ] `getPanelModule.tsx` — 패널 등록

### Phase 4: Mode 등록 (0.5일)
- [ ] longitudinal mode의 rightPanels에 추가
- [ ] extensionDependencies에 추가
- [ ] `getCommandsModule.ts` — save/sign 명령
- [ ] 빌드 성공 확인

### Phase 5: 정리 (0.5일)
- [ ] werub-app-config.js에서 report-panel.js 로더 제거
- [ ] werub-viewer/extensions/report-panel.js 제거
- [ ] CSS customCSS에서 report-panel 관련 스타일 제거 (있으면)

### Phase 6: 배포 (0.5일)
- [ ] 빌드 → dist 복사 → 서버 업로드
- [ ] Docker 이미지 재빌드
- [ ] 기능 14개 동작 검증

---

*다음 단계: `/pdca do werub-report-extension`*
