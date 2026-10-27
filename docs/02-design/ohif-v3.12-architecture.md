# OHIF v3.12.0 Architecture Reference

**목적**: WeRU.B Extension 개발을 위한 OHIF 내부 구조 참조 문서
**분석일**: 2026-05-19
**소스**: `werub-viewer/.ohif-src/` (OHIF Viewers v3.12.0)

---

## 1. CustomizationService — 우선순위 시스템

### 저장소 3개
```
globalCustomizations  ← config + extension global   (최우선)
modeCustomizations    ← mode에서 설정               (2순위)
defaultCustomizations ← extension default            (폴백)
```

### 조회 우선순위 (`getCustomization`)
```typescript
const customization =
  this.globalCustomizations.get(id) ??   // 1st
  this.modeCustomizations.get(id) ??     // 2nd
  this.defaultCustomizations.get(id);    // 3rd
```

### 초기화 순서 (init)
1. Extension `customizationModule.default` → `defaultCustomizations`
2. Extension `customizationModule.global` → `globalCustomizations`
3. `addReferences(appConfig.customizationService)` → `globalCustomizations` **(덮어씀)**

**핵심**: config의 `customizationService` 객체는 **항상 최우선**. plain object로 설정하면 Extension의 React 컴포넌트를 완전히 덮어씀.

### `_update` 병합 규칙
- `$` 접두사 키 없음 → **전체 교체** (plain object)
- `$set`, `$push` 등 → `immutability-helper`로 부분 병합

---

## 2. PubSubService — 이벤트 시스템

### API
```typescript
// 구독
const sub = service.subscribe(service.EVENTS.XXX, (data) => { ... });
sub.unsubscribe();

// 디바운스 구독
const sub = service.subscribeDebounced(service.EVENTS.XXX, callback, 300);

// 발행 (서비스 내부)
this._broadcastEvent(this.EVENTS.XXX, data);
```

### 특징
- 모든 OHIF 서비스가 `PubSubService`를 상속
- `_broadcastEvent`는 DOM CustomEvent **동시 발행** (document.body)
- `reset()`으로 모든 리스너 해제

---

## 3. ServicesManager — 서비스 등록

### REGISTRATION 형태
```typescript
{
  name: 'reportService',       // servicesManager.services.reportService
  altName?: 'ReportService',   // 별칭 (선택)
  create: ({ configuration, servicesManager, commandsManager, extensionManager }) => {
    return new ReportService(servicesManager);
  },
}
```

### 등록
```typescript
// Extension의 preRegistration에서:
servicesManager.registerService(ReportService.REGISTRATION);

// 또는 config 전달:
servicesManager.registerService(ReportService.REGISTRATION, configObject);
```

### 접근
```typescript
const { reportService } = servicesManager.services;
// 또는
const { servicesManager } = useSystem();
```

---

## 4. DisplaySetService — Study UID 감지

### EVENTS
```
DISPLAY_SETS_ADDED    — 새 displaySet 생성됨
DISPLAY_SETS_CHANGED  — displaySet 변경됨
DISPLAY_SETS_REMOVED  — displaySet 제거됨
```

### Study UID 획득 패턴
```typescript
// 1. ViewportGrid에서 active viewport의 displaySetInstanceUIDs 가져오기
const [viewportGrid] = useViewportGrid();
const { viewports, activeViewportId } = viewportGrid;
const activeViewport = viewports.get(activeViewportId);

// 2. DisplaySetService에서 displaySet 조회
const dsUID = activeViewport.displaySetInstanceUIDs[0];
const ds = displaySetService.getDisplaySetByUID(dsUID);

// 3. StudyInstanceUID 획득
const studyUID = ds.StudyInstanceUID;
```

### 주요 메서드
```typescript
getActiveDisplaySets(): DisplaySet[]          // 현재 활성 displaySet 배열
getDisplaySetByUID(uid: string): DisplaySet   // UID로 조회
getMostRecentDisplaySet(): DisplaySet         // 최근 추가된 것
```

### ViewportGrid 구조
```typescript
viewportGrid = {
  activeViewportId: string,
  viewports: Map<string, {
    displaySetInstanceUIDs: string[],
    viewportOptions: { ... },
    displaySetOptions: [{ ... }],
  }>,
}
```

---

## 5. Mode — 생명주기

### Mode 내보내기 구조
```typescript
export const mode = {
  id: '@ohif/mode-longitudinal',
  modeFactory,                    // ({ modeConfiguration }) => modeInstance
  extensionDependencies: {
    '@ohif/extension-default': '^3.0.0',
    'werub-report': '^1.0.0',     // ← 커스텀 Extension 추가 위치
  },
};
```

### modeInstance 구조
```typescript
{
  id, routeName, displayName, hide,
  onModeEnter({ servicesManager, panelService, ... }),
  onModeExit({ servicesManager }),
  isValidMode({ modalities, study }): { valid, description },
  routes: [{ path, layoutTemplate, layoutInstance }],
  extensions: extensionDependencies,
  hangingProtocol, sopClassHandlers,
  toolbarButtons, toolbarSections,
}
```

### onModeEnter — 초기화
- `measurementService.clearMeasurements()`
- `toolGroupService` 초기화
- `toolbarService.register(buttons)` + `updateSection(key, section)`
- `panelService.addActivatePanelTriggers(...)` — 이벤트 기반 패널 자동 열기

### onModeExit — 정리
- `uiDialogService.hideAll()` + `uiModalService.hide()`
- `toolGroupService.destroy()` + `syncGroupService.destroy()`
- `segmentationService.destroy()` + `cornerstoneViewportService.destroy()`

---

## 6. Panel 렌더링 — PanelService + SidePanel

### 패널 ID 형식
```
{extensionId}.panelModule.{panelName}
예: werub-report.panelModule.reportPanel
```

### PanelService 내부
```typescript
// 패널 추가 (Mode route에서 호출)
panelService.addPanel('right', 'werub-report.panelModule.reportPanel', options);

// 패널 조회
panelService.getPanels('right'): PanelData[]

// 패널 데이터 형태
PanelData = {
  id: string,           // 패널 모듈 ID
  iconName: string,     // 탭 아이콘
  iconLabel: string,    // 탭 라벨
  label: string,        // 전체 이름
  name: string,         // 패널 이름
  content: React.ComponentType  // 렌더링할 컴포넌트
}
```

### SidePanelWithServices 동작
1. `panelService.getPanels(side)`로 탭 목록 초기화
2. `panelService.EVENTS.PANELS_CHANGED` 구독 → 탭 목록 갱신
3. `panelService.EVENTS.ACTIVATE_PANEL` 구독 → 특정 탭 자동 활성화
4. 각 탭의 `content`를 React 컴포넌트로 렌더링

### Layout Instance에서 패널 등록
```typescript
// modes/longitudinal/src/index.ts
const longitudinalInstance = {
  id: ohif.layout,
  props: {
    leftPanels: [tracked.thumbnailList],
    rightPanels: [tracked.measurements, 'werub-report.panelModule.reportPanel'],
    viewports: [{ namespace: tracked.viewport, ... }],
  },
};
```

---

## 7. Extension 개발 체크리스트 (이 문서 기반)

### 서비스 만들 때
- [ ] `PubSubService` 상속
- [ ] `EVENTS` 상수 정의
- [ ] `static REGISTRATION = { name, create }` 
- [ ] `preRegistration`에서 `servicesManager.registerService()` 호출

### 패널 만들 때
- [ ] `getPanelModule` export — `{ name, iconName, iconLabel, label, component }` 반환
- [ ] 패널 컴포넌트에서 `useSystem()` → `servicesManager.services`로 서비스 접근
- [ ] `useViewportGrid()`로 active viewport → `displaySetService`로 Study UID 획득
- [ ] `service.subscribe(EVENTS.XXX, cb)` + cleanup in `useEffect` return

### Mode에 등록할 때
- [ ] `extensionDependencies`에 Extension ID 추가
- [ ] `rightPanels` 또는 `leftPanels`에 패널 모듈 ID 추가
- [ ] `onModeEnter`에서 서비스 초기화 (필요 시)

### config에서 절대 하면 안 되는 것
- [ ] `customizationService`에 React 컴포넌트를 대체하는 plain object 설정 금지
  - 소스의 컴포넌트가 plain object로 덮어씌워져 렌더링 실패 (검은 화면)
