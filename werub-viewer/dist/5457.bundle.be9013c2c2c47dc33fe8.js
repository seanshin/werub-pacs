"use strict";
(globalThis["webpackChunk"] = globalThis["webpackChunk"] || []).push([[5457],{

/***/ 95457:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

// ESM COMPAT FLAG
__webpack_require__.r(__webpack_exports__);

// EXPORTS
__webpack_require__.d(__webpack_exports__, {
  "default": () => (/* binding */ longitudinal_src),
  extensionDependencies: () => (/* binding */ extensionDependencies),
  initToolGroups: () => (/* reexport */ src.initToolGroups),
  longitudinalInstance: () => (/* binding */ longitudinalInstance),
  longitudinalRoute: () => (/* binding */ longitudinalRoute),
  modeInstance: () => (/* binding */ modeInstance),
  toolbarButtons: () => (/* reexport */ src.toolbarButtons),
  tracked: () => (/* binding */ tracked)
});

// EXTERNAL MODULE: ../../../node_modules/i18next/dist/esm/i18next.js
var i18next = __webpack_require__(40680);
;// ../../../modes/longitudinal/package.json
const package_namespaceObject = /*#__PURE__*/JSON.parse('{"UU":"@ohif/mode-longitudinal"}');
;// ../../../modes/longitudinal/src/id.js

const id = package_namespaceObject.UU;

// EXTERNAL MODULE: ../../../modes/basic/src/index.tsx + 4 modules
var src = __webpack_require__(35485);
;// ../../../modes/longitudinal/src/index.ts



const tracked = {
  measurements: '@ohif/extension-measurement-tracking.panelModule.trackedMeasurements',
  thumbnailList: '@ohif/extension-measurement-tracking.panelModule.seriesList',
  viewport: '@ohif/extension-measurement-tracking.viewportModule.cornerstone-tracked'
};
const extensionDependencies = {
  // Can derive the versions at least process.env.from npm_package_version
  ...src.extensionDependencies,
  '@ohif/extension-measurement-tracking': '^3.0.0',
  '@ohif/extension-werub-report': '^1.0.0',
  '@ohif/extension-werub-ai': '^1.0.0'
};
const longitudinalInstance = {
  ...src.basicLayout,
  id: src.ohif.layout,
  props: {
    ...src.basicLayout.props,
    leftPanels: [tracked.thumbnailList],
    rightPanels: [src.cornerstone.segmentation, tracked.measurements, '@ohif/extension-werub-report.panelModule.reportPanel', '@ohif/extension-werub-ai.panelModule.aiPanel'],
    viewports: [{
      namespace: tracked.viewport,
      // Re-use the display sets from basic
      displaySetsToDisplay: src.basicLayout.props.viewports[0].displaySetsToDisplay
    }, ...src.basicLayout.props.viewports]
  }
};
const longitudinalRoute = {
  ...src.basicRoute,
  path: 'longitudinal',
  /*init: ({ servicesManager, extensionManager }) => {
    //defaultViewerRouteInit
  },*/
  layoutInstance: longitudinalInstance
};

// WeRU.B viewer-ux: prior 원클릭 비교 버튼 — 명령은 werub-ai getCommandsModule 제공
const werubPriorCompareButton = {
  id: 'werubPriorCompare',
  uiType: 'ohif.toolButton',
  props: {
    icon: 'layout-side-by-side',
    label: '이전검사',
    tooltip: '이전 검사와 나란히 비교 (p)',
    commands: 'werubComparePrior',
    evaluate: 'evaluate.action'
  }
};

// WeRU.B viewer-ux: Layout 버튼 뒤에 이전검사 버튼 삽입
const werubToolbarSections = Object.fromEntries(Object.entries(src.modeInstance.toolbarSections).map(([key, ids]) => {
  if (Array.isArray(ids) && ids.includes('Layout')) {
    const next = [...ids];
    next.splice(next.indexOf('Layout') + 1, 0, 'werubPriorCompare');
    return [key, next];
  }
  return [key, ids];
}));

// WeRU.B: SM(WSI) 스터디가 기본 /viewer(longitudinal)로 열리면 이미지는 나오지만 microscopy 전용
// UI(드로잉 도구·MicroscopyPanel·주석 저장)가 없다. 백엔드 뷰어 링크 20+곳이 /viewer로 생성되고
// isValidMode도 SM을 배제하지 않아, 병리 스터디를 워크리스트/포털 링크로 열면 잘못된 모드로 열림.
// → 단일 지점 해결: longitudinal 진입 시 SM 디스플레이셋을 감지하면 /microscopy로 리다이렉트.
// (LIS 런처 viewer/launch는 이미 SM→microscopy 라우팅. 이건 그 외 모든 직접 링크를 커버.)
function redirectSMToMicroscopy(servicesManager) {
  try {
    const {
      displaySetService
    } = servicesManager.services;
    const tryRedirect = () => {
      const hasSM = (displaySetService.getActiveDisplaySets() || []).some(ds => ds && ds.Modality === 'SM');
      if (!hasSM) return false;
      const u = new URL(window.location.href);
      if (/\/viewer\/?$/.test(u.pathname)) {
        u.pathname = u.pathname.replace(/\/viewer\/?$/, '/microscopy');
        window.location.replace(u.href);
        return true;
      }
      return false;
    };
    if (tryRedirect()) {
      return undefined;
    }
    const {
      unsubscribe
    } = displaySetService.subscribe(displaySetService.EVENTS.DISPLAY_SETS_ADDED, () => {
      if (tryRedirect()) {
        unsubscribe && unsubscribe();
      }
    });
    return unsubscribe; // 미발동 구독은 onModeExit에서 해제(비-SM 진입 반복 시 누수 방지)
  } catch (e) {
    // 리다이렉트는 편의 기능 — 실패해도 기존 동작 유지
    return undefined;
  }
}
let _smRedirectUnsub;
const modeInstance = {
  ...src.modeInstance,
  // TODO: We're using this as a route segment
  // We should not be.
  id: id,
  routeName: 'viewer',
  // ★basic onModeEnter는 this.toolbarButtons/this.toolbarSections를 등록 —
  // basicModeInstance.onModeEnter(params)로 위임하면 this=basic이 되어 이 모드가
  // 병합한 버튼(werubPriorCompare)이 소실됨(v13.24 회귀) → 반드시 .call(this, ...)
  onModeEnter: function (params) {
    src.modeInstance.onModeEnter && src.modeInstance.onModeEnter.call(this, params);
    _smRedirectUnsub = redirectSMToMicroscopy(params.servicesManager);
  },
  onModeExit: function (params) {
    if (_smRedirectUnsub) {
      try {
        _smRedirectUnsub();
      } catch (e) {
        /* no-op */
      }
      _smRedirectUnsub = undefined;
    }
    src.modeInstance.onModeExit && src.modeInstance.onModeExit.call(this, params);
  },
  displayName: i18next/* default */.A.t('Modes:Basic Viewer'),
  routes: [longitudinalRoute],
  extensions: extensionDependencies,
  // WeRU.B viewer-ux: 배열이면 HP 매칭 엔진이 동작(문자열은 직접 적용) —
  // werubAutoMPR(재구성 가능 CT/MR→MPR 자동), 아니면 default(1×1) 폴백
  hangingProtocol: ['werubAutoMPR', 'default'],
  toolbarButtons: [...src.modeInstance.toolbarButtons, werubPriorCompareButton],
  toolbarSections: werubToolbarSections
};
const mode = {
  ...src.mode,
  id: id,
  modeInstance,
  extensionDependencies
};
/* harmony default export */ const longitudinal_src = (mode);


/***/ })

}]);