"use strict";
(globalThis["webpackChunk"] = globalThis["webpackChunk"] || []).push([[6743],{

/***/ 86743:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

// ESM COMPAT FLAG
__webpack_require__.r(__webpack_exports__);

// EXPORTS
__webpack_require__.d(__webpack_exports__, {
  "default": () => (/* binding */ src)
});

;// ../../../extensions/werub-ai/package.json
const package_namespaceObject = /*#__PURE__*/JSON.parse('{"UU":"@ohif/extension-werub-ai"}');
;// ../../../extensions/werub-ai/src/id.ts

const id = package_namespaceObject.UU;
// EXTERNAL MODULE: ../../../node_modules/react/index.js
var react = __webpack_require__(86326);
;// ../../../extensions/werub-ai/src/services/AiService.ts
var _AiService;
const API_BASE = '/pacs-api/api/v1';
class AiService {
  constructor(servicesManager) {
    this.servicesManager = void 0;
    this._listeners = {};
    this._token = null;
    this._lastResult = null;
    this._loading = false;
    this.servicesManager = servicesManager;
    this._token = typeof localStorage !== 'undefined' ? localStorage.getItem('pacs_token') : null;
  }

  // --- Event system ---
  subscribe(event, callback) {
    if (!this._listeners[event]) this._listeners[event] = [];
    this._listeners[event].push(callback);
    return {
      unsubscribe: () => {
        this._listeners[event] = (this._listeners[event] || []).filter(cb => cb !== callback);
      }
    };
  }
  _emit(event, data) {
    (this._listeners[event] || []).forEach(cb => {
      try {
        cb(data);
      } catch (e) {
        console.error('[AiService]', e);
      }
    });
  }

  // --- Getters ---
  get loading() {
    return this._loading;
  }
  get lastResult() {
    return this._lastResult;
  }

  // --- API helper ---
  async api(path, opts = {}) {
    this._token = typeof localStorage !== 'undefined' ? localStorage.getItem('pacs_token') : null;
    const headers = {
      'Content-Type': 'application/json'
    };
    if (this._token) headers['Authorization'] = `Bearer ${this._token}`;
    try {
      const res = await fetch(`${API_BASE}${path}`, {
        ...opts,
        headers: {
          ...headers,
          ...opts.headers
        }
      });
      if (res.status === 401) {
        // K9: 토큰 만료 시 ReportService와 동일하게 재인증 유도(무한 "분석 실패" 방지)
        try {
          localStorage.removeItem('pacs_token');
          this._emit('authChanged', {
            authenticated: false
          });
        } catch {}
        return null;
      }
      if (!res.ok) return null;
      return res.json();
    } catch {
      return null;
    }
  }
  _setLoading(val) {
    this._loading = val;
    this._emit('loadingChanged', {
      loading: val
    });
  }

  // --- AI API Methods ---

  // Available active AI models (for the model picker).
  async getModels() {
    const res = await this.api('/ai/models?active_only=true');
    return res?.models || [];
  }
  async analyzeStudy(studyUID, modelName) {
    this._setLoading(true);
    const res = await this.api('/ai/analyze-and-draft', {
      method: 'POST',
      body: JSON.stringify({
        study_instance_uid: studyUID,
        auto_create_report: false,
        ...(modelName ? {
          model_name: modelName
        } : {})
      })
    });
    this._setLoading(false);
    if (res?.ai_analysis) {
      this._lastResult = res.ai_analysis;
      this._emit('analysisComplete', {
        result: res.ai_analysis,
        type: 'analyze'
      });
      return res.ai_analysis;
    }
    this._emit('analysisError', {
      error: 'AI 분석 실패',
      type: 'analyze'
    });
    return null;
  }
  async compareStudies(studyUID) {
    this._setLoading(true);
    const res = await this.api('/ai/compare-studies', {
      method: 'POST',
      body: JSON.stringify({
        current_study_uid: studyUID
      })
    });
    this._setLoading(false);
    if (res?.comparison) {
      this._emit('analysisComplete', {
        result: res.comparison,
        type: 'compare'
      });
      return res.comparison;
    }
    this._emit('analysisComplete', {
      result: {
        message: res?.message || '이전 검사 없음'
      },
      type: 'compare'
    });
    return res;
  }
  async soapSummary(findings, impression) {
    this._setLoading(true);
    const res = await this.api('/ai/soap-summary', {
      method: 'POST',
      body: JSON.stringify({
        findings,
        impression,
        clinical_info: ''
      })
    });
    this._setLoading(false);
    if (res) {
      this._emit('analysisComplete', {
        result: res,
        type: 'soap'
      });
    }
    return res;
  }
  async differentialDiagnosis(symptoms, findings) {
    this._setLoading(true);
    const res = await this.api('/ai/differential-diagnosis', {
      method: 'POST',
      body: JSON.stringify({
        symptoms,
        findings
      })
    });
    this._setLoading(false);
    if (res) {
      this._emit('analysisComplete', {
        result: res,
        type: 'ddx'
      });
    }
    return res;
  }
  async getServerStatus() {
    return this.api('/ai/server-status');
  }

  // --- 저장된 표준 추론 결과 (TID 1500 SR을 만든 잡) ---
  // OHIF의 측정-SR 뷰포트는 좌표 없는 범주형 AI SR을 렌더하지 못하므로,
  // 패널에서 저장된 추론 결과(소견/신뢰도)를 직접 표시한다.
  async getStudyResult(studyUID) {
    const res = await this.api(`/ai/jobs?study_uid=${encodeURIComponent(studyUID)}&status=completed&limit=1`);
    return res?.results?.length ? res.results[0] : null;
  }

  // --- Orchestration Pipeline ---
  async getProductionPipeline() {
    const res = await this.api('/ai/orchestration/production');
    return res?.reading || null;
  }
  async runPipeline(pipeline, studyUID) {
    this._setLoading(true);
    const res = await this.api('/ai/orchestration/run', {
      method: 'POST',
      body: JSON.stringify({
        pipeline,
        study_instance_uid: studyUID,
        debug: false
      })
    });
    this._setLoading(false);
    if (res && !res.error) {
      this._emit('analysisComplete', {
        result: res,
        type: 'pipeline'
      });
      return res;
    }
    this._emit('analysisError', {
      error: res?.error || '파이프라인 실행 실패',
      type: 'pipeline'
    });
    return null;
  }

  // --- DICOM SR 저장 ---
  async saveAsSR(studyUID, findings, impression) {
    return this.api('/reports/structured', {
      method: 'POST',
      body: JSON.stringify({
        study_instance_uid: studyUID,
        schema_type: 'basic_diagnostic',
        structured_data: {
          findings,
          impression
        },
        source: 'ai_analysis'
      })
    });
  }

  // --- Report Panel 연동 ---
  async applyToReport(data, studyUID) {
    // 1. OHIF internal report service (non-blocking)
    try {
      const {
        reportService
      } = this.servicesManager.services;
      if (reportService) {
        await reportService.save(data);
      }
    } catch (e) {
      console.warn('[AiService] reportService.save failed:', e);
    }

    // 2. OpenPACS backend API — save AI result to report (upsert)
    if (studyUID && (data.findings || data.impression || data.recommendation)) {
      const res = await this.api('/ai/apply-to-report', {
        method: 'POST',
        body: JSON.stringify({
          study_instance_uid: studyUID,
          findings: data.findings || '',
          impression: data.impression || '',
          recommendation: data.recommendation || ''
        })
      });
      console.log('[AiService] apply-to-report result:', res);
    }

    // 3. Broadcast to reading view for real-time sync
    try {
      const ch = new BroadcastChannel('pacs-ai-result');
      ch.postMessage({
        type: 'ai_applied',
        studyUID,
        data
      });
      ch.close();
    } catch {}
    // Fallback: localStorage event (cross-tab)
    try {
      localStorage.setItem('pacs-ai-applied', JSON.stringify({
        studyUID,
        data,
        ts: Date.now()
      }));
    } catch {}
  }
}
_AiService = AiService;
AiService.REGISTRATION = {
  name: 'aiService',
  create: ({
    servicesManager
  }) => new _AiService(servicesManager)
};

;// ../../../extensions/werub-ai/src/priorCompare.ts
/**
 * Prior 원클릭 비교 (viewer-ux B, v13.17).
 *
 * 툴바 '이전검사' 버튼/단축키(p) → 백엔드 prior 조회(services/prior_lookup 재사용)
 * → 현재+prior 두 study를 로드하며 hpCompare(URL hangingprotocolid — 문자열이라
 * 매칭 우회·직접 적용)로 재진입. prior 없으면 토스트.
 */
const priorCompare_API_BASE = '/pacs-api/api/v1';
function currentStudyUids() {
  const params = new URLSearchParams(window.location.search);
  return params.getAll('StudyInstanceUIDs').flatMap(v => v.split(/[,;]/)).map(s => s.trim()).filter(Boolean);
}
async function comparePrior(servicesManager) {
  const {
    uiNotificationService
  } = servicesManager.services;
  const notify = (title, message, type = 'info') => uiNotificationService?.show?.({
    title,
    message,
    type,
    duration: 5000
  });
  const uids = currentStudyUids();
  if (!uids.length) {
    return;
  }
  if (uids.length > 1) {
    notify('이전검사 비교', '이미 비교 화면입니다. 현재 검사만 보려면 스터디 하나로 다시 여세요.');
    return;
  }
  const current = uids[0];
  const token = localStorage.getItem('pacs_token');
  if (!token) {
    notify('이전검사 비교', '로그인 정보가 없어 이전 검사를 조회할 수 없습니다.', 'warning');
    return;
  }
  try {
    const res = await fetch(`${priorCompare_API_BASE}/studies/${encodeURIComponent(current)}/priors?max_results=1`, {
      headers: {
        Authorization: `Bearer ${token}`
      }
    });
    if (!res.ok) {
      throw new Error(`priors ${res.status}`);
    }
    const data = await res.json();
    const prior = (data.priors || [])[0];
    if (!prior?.study_instance_uid) {
      notify('이전검사 비교', '이 환자의 이전 검사가 없습니다.');
      return;
    }
    const date = prior.study_date ? ` (${String(prior.study_date).replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3')})` : '';
    notify('이전검사 비교', `이전 검사${date}와 비교 화면으로 전환합니다.`);
    const uids = `${encodeURIComponent(current)},${encodeURIComponent(prior.study_instance_uid)}`;
    const url = `/werub-viewer/viewer?StudyInstanceUIDs=${uids}` + `&hangingprotocolid=${encodeURIComponent('@ohif/hpCompare')}`;
    window.location.assign(url);
  } catch (e) {
    console.error('[werub-ai] prior compare failed:', e);
    notify('이전검사 비교', '이전 검사 조회에 실패했습니다.', 'error');
  }
}
;// ../../../extensions/werub-ai/src/getCommandsModule.ts

function getCommandsModule({
  servicesManager
}) {
  return {
    definitions: {
      runAiAnalysis: {
        commandFn: () => {
          const {
            aiService
          } = servicesManager.services;
          // StudyUID would need to be passed or read from viewport
          if (aiService) console.log('[werub-ai] runAiAnalysis command invoked');
        }
      },
      // 이전검사 원클릭 비교 (viewer-ux B) — 툴바 버튼·단축키 p
      werubComparePrior: {
        commandFn: () => comparePrior(servicesManager)
      }
    },
    defaultContext: 'VIEWER'
  };
}
/* harmony default export */ const src_getCommandsModule = (getCommandsModule);
// EXTERNAL MODULE: ../../../node_modules/@cornerstonejs/core/dist/esm/index.js + 1 modules
var esm = __webpack_require__(15327);
;// ../../../extensions/werub-ai/src/prefetchEvents.ts
/**
 * Study-open instrumentation + prefetch trigger (3d-ai-performance Track A).
 *
 * DICOMweb traffic goes nginx -> Orthanc and never touches the PACS backend,
 * so the viewer must announce study opens itself:
 *  - study-opened fires immediately on mode enter (starts server-side warming
 *    of the predicted next studies — must not wait for rendering)
 *  - load-measured fires once the first image renders (baseline/effect metric)
 *  - volume-complete reports full 3D volume load (progressive-loading measurement)
 */

const prefetchEvents_API_BASE = '/pacs-api/api/v1';

// @cornerstonejs/core Events.IMAGE_RENDERED. Hardcoded to avoid a build-time
// dependency; it is dispatched on the viewport element without bubbling, so we
// listen in the capture phase on document.
const IMAGE_RENDERED_EVENT = 'CORNERSTONE_IMAGE_RENDERED';
const RENDER_TIMEOUT_MS = 60_000;
// Full-volume load completion (progressive-loading measurement). This fires on
// cornerstone's eventTarget (NOT the DOM), so we attach there. Resolved from the
// monorepo even though it's not a package.json dep (other extensions import it).
const VOLUME_COMPLETE_EVENT = 'IMAGE_VOLUME_LOADING_COMPLETED';
const VOLUME_TIMEOUT_MS = 300_000; // big CT volumes can take minutes

let cleanupFns = [];
function post(path, payload) {
  const token = typeof localStorage !== 'undefined' ? localStorage.getItem('pacs_token') : null;
  if (!token) {
    return;
  }
  fetch(`${prefetchEvents_API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`
    },
    body: JSON.stringify(payload),
    keepalive: true
  }).catch(() => {
    /* instrumentation must never break the viewer */
  });
}
function prefetchEvents_currentStudyUids() {
  const params = new URLSearchParams(window.location.search);
  const raw = params.get('StudyInstanceUIDs') || '';
  return raw.split(/[,;]/).map(s => s.trim()).filter(Boolean);
}
function startStudyOpenTracking() {
  stopStudyOpenTracking();
  const uids = prefetchEvents_currentStudyUids();
  if (!uids.length) {
    return;
  }
  const t0 = performance.now();
  uids.forEach(uid => post('/prefetch/events/study-opened', {
    study_instance_uid: uid
  }));

  // Load time is attributed to the primary (first) study of the URL.
  const primaryUid = uids[0];
  let reported = false;
  const onRendered = () => {
    if (reported) {
      return;
    }
    reported = true;
    post('/prefetch/events/load-measured', {
      study_instance_uid: primaryUid,
      load_ms: Math.round(performance.now() - t0)
    });
    // Do NOT stop tracking here — the volume-complete listener fires later.
    // onModeExit() calls stopStudyOpenTracking() for cleanup.
  };
  document.addEventListener(IMAGE_RENDERED_EVENT, onRendered, {
    capture: true,
    once: true
  });
  const timer = window.setTimeout(() => {
    reported = true; // never rendered within budget — skip the metric
  }, RENDER_TIMEOUT_MS);

  // Full-volume load completion — the gap from t0 vs first image is the
  // progressive-loading benefit. Independent of onRendered (fires later).
  let volumeReported = false;
  const onVolumeComplete = () => {
    if (volumeReported) {
      return;
    }
    volumeReported = true;
    post('/prefetch/events/load-measured', {
      study_instance_uid: primaryUid,
      volume_complete_ms: Math.round(performance.now() - t0)
    });
  };
  try {
    esm.eventTarget.addEventListener(VOLUME_COMPLETE_EVENT, onVolumeComplete);
  } catch (e) {
    console.error('[werub-ai] volume-complete listener failed:', e);
  }
  const volTimer = window.setTimeout(() => {
    volumeReported = true;
  }, VOLUME_TIMEOUT_MS);
  cleanupFns = [() => document.removeEventListener(IMAGE_RENDERED_EVENT, onRendered, {
    capture: true
  }), () => window.clearTimeout(timer), () => {
    try {
      esm.eventTarget.removeEventListener(VOLUME_COMPLETE_EVENT, onVolumeComplete);
    } catch {/* noop */}
  }, () => window.clearTimeout(volTimer)];
}
function stopStudyOpenTracking() {
  cleanupFns.forEach(fn => fn());
  cleanupFns = [];
}
;// ../../../extensions/werub-ai/src/vrtTelemetry.ts
/**
 * 3D 사용 텔레메트리 (vrt-rendering Phase 1 §1.2-5).
 *
 * 레이아웃이 3D 계열 행잉 프로토콜로 전환될 때 백엔드에 기록한다 —
 * 서버사이드 GPU 렌더링(Phase 2)의 수요 근거 데이터.
 */
const vrtTelemetry_API_BASE = '/pacs-api/api/v1';
const THREE_D_PROTOCOLS = new Set(['main3D', 'only3D', 'primary3D', 'mprAnd3DVolumeViewport', 'fourUp']);
let subscription = null;
let presetListener = null;
let wasIn3D = false;
function vrtTelemetry_post(path, payload) {
  const token = typeof localStorage !== 'undefined' ? localStorage.getItem('pacs_token') : null;
  if (!token) {
    return;
  }
  fetch(`${vrtTelemetry_API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`
    },
    body: JSON.stringify(payload),
    keepalive: true
  }).catch(() => {
    /* telemetry must never break the viewer */
  });
}
function currentStudyUid() {
  const params = new URLSearchParams(window.location.search);
  return (params.get('StudyInstanceUIDs') || '').split(/[,;]/)[0]?.trim() || '';
}
function startVrtTelemetry(servicesManager) {
  stopVrtTelemetry();
  try {
    const {
      hangingProtocolService,
      uiNotificationService
    } = servicesManager.services;
    subscription = hangingProtocolService.subscribe(hangingProtocolService.EVENTS.PROTOCOL_CHANGED, () => {
      try {
        const {
          protocol
        } = hangingProtocolService.getActiveProtocol();
        const in3D = Boolean(protocol?.id && THREE_D_PROTOCOLS.has(protocol.id));
        if (in3D) {
          vrtTelemetry_post('/vrt/events/protocol', {
            study_instance_uid: currentStudyUid(),
            protocol_id: protocol.id
          });
          // 참고용 3D 안내 — 3D 뷰포트는 HP가 hideOverlays:true로 오버레이 전체를
          // 숨기므로 뷰포트 배지가 불가(v11.6 배지가 렌더된 적 없던 이유). 토스트로 대체.
          if (!wasIn3D) {
            uiNotificationService?.show?.({
              title: '참고용 3D 렌더링',
              message: '3D 화면은 참고용입니다 — 측정은 MPR 뷰포트에서 하세요.',
              type: 'info',
              duration: 8000
            });
          }
        }
        wasIn3D = in3D;
      } catch {
        /* ignore */
      }
    });
  } catch (e) {
    console.error('[werub-ai] vrt telemetry init failed:', e);
  }
  // VR 프리셋 적용 텔레메트리 (C2) — VolumeRenderingPresetsContent(werub-source.patch)가 발행
  presetListener = e => {
    try {
      const preset = e.detail?.preset;
      if (preset) {
        vrtTelemetry_post('/vrt/events/preset', {
          study_instance_uid: currentStudyUid(),
          preset_name: String(preset).slice(0, 64)
        });
      }
    } catch {
      /* ignore */
    }
  };
  document.addEventListener('werub:vrt-preset-applied', presetListener);
}
function stopVrtTelemetry() {
  subscription?.unsubscribe?.();
  subscription = null;
  wasIn3D = false;
  if (presetListener) {
    document.removeEventListener('werub:vrt-preset-applied', presetListener);
    presetListener = null;
  }
}
;// ../../../extensions/werub-ai/src/vrtCustomizations.ts
/**
 * 3D VRT 임상 튜닝 — 경량 스코프 (C2, docs/02-design/vrt-clinical-tuning-c2.design.md §2).
 *
 * 1) VR 프리셋 큐레이션: cornerstone 코어 26종 → 한국 임상 핵심 13종(순서 고정).
 *    preset.name은 cornerstone 룩업 키·아이콘 키이므로 불변 — 한글 표시는
 *    기존 i18n(WindowLevelActionMenu ns, 68f83ef)이 담당한다.
 * 2) 레이아웃 셀렉터 Advanced 목록 한글화·정렬(3D 진입 UX).
 *
 * onModeEnter에서 global scope로 설정 — 확장 로드 순서와 무관하게
 * cornerstone 확장의 default 값을 확정적으로 덮는다($ 키 없음 = 통째 교체).
 */

const CURATED_PRESET_NAMES = ['CT-Bone', 'CT-Soft-Tissue', 'CT-Lung', 'CT-Cardiac', 'CT-Chest-Contrast-Enhanced', 'CT-Coronary-Arteries', 'CT-Pulmonary-Arteries', 'CT-Liver-Vasculature', 'CT-AAA', 'CT-MIP', 'MR-Default', 'MR-Angio', 'MR-MIP'];

// HP id → 한글 타이틀. protocolId는 반드시 hangingProtocolService에 등록된 hp.id를 써야 한다
// (ToolbarLayoutSelector의 하드코딩 폴백 '3d-main' 등은 미등록 id — 클릭해도 "No protocol found").
const HP_TITLES_KO = {
  mpr: 'MPR',
  main3D: '3D 메인',
  mprAnd3DVolumeViewport: 'MPR + 3D',
  fourUp: '3D 4분할',
  only3D: '3D 단독',
  primary3D: '3D 주화면',
  primaryAxial: 'Axial 우선',
  '@ohif/frameView': '프레임 뷰'
};
const HP_ORDER = Object.keys(HP_TITLES_KO);

/**
 * cornerstone 기본 layoutSelectorCustomization과 동일하게 등록 HP(isPreset)를 열거하고
 * displaySet 선택자 검증으로 disabled를 계산하되, 타이틀 한글화 + 3D 우선 정렬만 더한다.
 */
function generateAdvancedPresets({
  servicesManager
}) {
  const {
    hangingProtocolService,
    viewportGridService,
    displaySetService
  } = servicesManager.services;
  const viewportId = viewportGridService.getActiveViewportId();
  if (!viewportId) {
    return [];
  }
  const displaySetInstanceUIDs = viewportGridService.getDisplaySetsUIDsForViewport(viewportId);
  if (!displaySetInstanceUIDs) {
    return [];
  }
  const displaySets = displaySetInstanceUIDs.map(uid => {
    const displaySet = displaySetService.getDisplaySetByUID(uid);
    const referencedDisplaySetUID = displaySet?.measurements?.[0]?.displaySetInstanceUID;
    if (displaySet?.Modality === 'SR' && referencedDisplaySetUID) {
      return displaySetService.getDisplaySetByUID(referencedDisplaySetUID);
    }
    return displaySet;
  });
  const isValid = hp => {
    if (!hp.displaySetSelectors || Object.values(hp.displaySetSelectors).length === 0) {
      return true;
    }
    return hangingProtocolService.areRequiredSelectorsValid(Object.values(hp.displaySetSelectors), displaySets[0]);
  };
  return Array.from(hangingProtocolService.protocols.values()).filter(hp => hp.isPreset).map(hp => ({
    icon: hp.icon,
    title: HP_TITLES_KO[hp.id] || hp.name,
    commandOptions: {
      protocolId: hp.id
    },
    disabled: !isValid(hp)
  })).sort((a, b) => {
    const ia = HP_ORDER.indexOf(a.commandOptions.protocolId);
    const ib = HP_ORDER.indexOf(b.commandOptions.protocolId);
    return (ia === -1 ? HP_ORDER.length : ia) - (ib === -1 ? HP_ORDER.length : ib);
  });
}
function setupVrtCustomizations(servicesManager) {
  try {
    const {
      customizationService
    } = servicesManager.services;
    if (!customizationService) {
      return;
    }
    const all = esm.CONSTANTS.VIEWPORT_PRESETS || [];
    const byName = new Map(all.map(p => [p.name, p]));
    const curated = CURATED_PRESET_NAMES.map(n => byName.get(n)).filter(Boolean);
    customizationService.setCustomizations({
      'cornerstone.3dVolumeRendering': {
        // 코어 버전업으로 이름이 어긋나 큐레이션이 비면 전체 목록으로 폴백
        volumeRenderingPresets: curated.length ? curated : all,
        volumeRenderingQualityRange: {
          min: 1,
          max: 4,
          step: 1
        }
      },
      'layoutSelector.advancedPresetGenerator': generateAdvancedPresets
    }, 'global');
  } catch (e) {
    console.error('[werub-ai] vrt customizations failed:', e);
  }
}
;// ../../../extensions/werub-ai/src/getHangingProtocolModule.ts
/**
 * 모달리티별 자동 Hanging Protocol (viewer-ux A, v13.17).
 *
 * 'werubAutoMPR' = 코어 mpr HP의 클론 + protocolMatchingRules.
 * 매칭은 mode의 hangingProtocol이 **배열**일 때만 동작한다(문자열이면 직접 적용) —
 * longitudinal 모드가 ['werubAutoMPR', 'default']를 지정(werub-source.patch).
 * required 규칙이 커스텀 속성 'werubHasReconstructable'(index.ts에서 등록,
 * displaySets에 재구성 가능 시리즈 존재)이라 단면/SR-only 검사에서는 매칭 실패
 * → 엔진이 'default'(1×1)로 폴백. 적용 단계 실패(빈 볼륨)가 원천 차단된다.
 * isPreset: false — 레이아웃 Advanced 메뉴(큐레이션)에는 노출하지 않는다.
 */

const VOI_SYNC_GROUP = {
  type: 'voi',
  id: 'mpr',
  source: true,
  target: true,
  options: {
    syncColormap: true
  }
};
const HYDRATE_SEG_SYNC_GROUP = {
  type: 'hydrateseg',
  id: 'sameFORId',
  source: true,
  target: true,
  options: {
    matchingRules: ['sameFOR']
  }
};
function mprViewport(viewportId, orientation) {
  return {
    viewportOptions: {
      viewportId,
      toolGroupId: 'mpr',
      viewportType: 'volume',
      orientation,
      initialImageOptions: {
        preset: 'middle'
      },
      syncGroups: [VOI_SYNC_GROUP, HYDRATE_SEG_SYNC_GROUP]
    },
    displaySets: [{
      id: 'activeDisplaySet'
    }]
  };
}
const werubAutoMPR = {
  id: 'werubAutoMPR',
  name: '자동 MPR',
  locked: true,
  icon: 'layout-advanced-mpr',
  isPreset: false,
  createdDate: '2026-07-11',
  modifiedDate: '2026-07-11',
  availableTo: {},
  editableBy: {},
  numberOfPriorsReferenced: 0,
  protocolMatchingRules: [{
    id: 'werubReconstructable',
    weight: 10,
    attribute: 'werubHasReconstructable',
    constraint: {
      equals: {
        value: true
      }
    },
    required: true
  },
  // 모달리티 가중치(선택) — CT/MR이면 우선순위를 높인다
  {
    id: 'werubCT',
    weight: 2,
    attribute: 'ModalitiesInStudy',
    constraint: {
      contains: {
        value: 'CT'
      }
    }
  }, {
    id: 'werubMR',
    weight: 2,
    attribute: 'ModalitiesInStudy',
    constraint: {
      contains: {
        value: 'MR'
      }
    }
  }],
  imageLoadStrategy: 'nth',
  callbacks: {},
  displaySetSelectors: {
    activeDisplaySet: {
      seriesMatchingRules: [{
        weight: 1,
        attribute: 'isReconstructable',
        constraint: {
          equals: {
            value: true
          }
        },
        required: true
      }]
    }
  },
  stages: [{
    name: 'MPR 1x3',
    viewportStructure: {
      layoutType: 'grid',
      properties: {
        rows: 1,
        columns: 3,
        layoutOptions: [{
          x: 0,
          y: 0,
          width: 1 / 3,
          height: 1
        }, {
          x: 1 / 3,
          y: 0,
          width: 1 / 3,
          height: 1
        }, {
          x: 2 / 3,
          y: 0,
          width: 1 / 3,
          height: 1
        }]
      }
    },
    viewports: [mprViewport('mpr-axial', 'axial'), mprViewport('mpr-sagittal', 'sagittal'), mprViewport('mpr-coronal', 'coronal')]
  }]
};
function getHangingProtocolModule() {
  return [{
    name: werubAutoMPR.id,
    protocol: werubAutoMPR
  }];
}
;// ../../../extensions/werub-ai/src/index.ts








const werubAiExtension = {
  id: id,
  preRegistration({
    servicesManager
  }) {
    try {
      servicesManager.registerService(AiService.REGISTRATION);
    } catch (e) {
      console.error('[werub-ai] AiService registration failed:', e);
    }
  },
  onModeEnter({
    servicesManager
  }) {
    try {
      startStudyOpenTracking();
    } catch (e) {
      console.error('[werub-ai] study-open tracking failed:', e);
    }
    startVrtTelemetry(servicesManager);
    setupVrtCustomizations(servicesManager);
    // 자동 HP 매칭용 커스텀 속성 — werubAutoMPR의 required 규칙이 참조.
    // 확장 onModeEnter는 mode의 HP run보다 먼저 실행된다(Mode.tsx 순서 보장).
    try {
      const {
        hangingProtocolService
      } = servicesManager.services;
      hangingProtocolService?.addCustomAttribute?.('werubHasReconstructable', '재구성 가능 시리즈 존재 여부', (_study, options) => Boolean(options?.displaySets?.some(ds => ds?.isReconstructable === true)));
    } catch (e) {
      console.error('[werub-ai] custom HP attribute registration failed:', e);
    }
  },
  onModeExit() {
    stopStudyOpenTracking();
    stopVrtTelemetry();
  },
  getPanelModule({
    servicesManager,
    commandsManager
  }) {
    return [{
      name: 'aiPanel',
      iconName: 'tab-segmentation',
      iconLabel: 'AI',
      label: 'AI 분석',
      component: props => {
        const AiPanel = /*#__PURE__*/react.lazy(() => __webpack_require__.e(/* import() */ 7993).then(__webpack_require__.bind(__webpack_require__, 7993)));
        return /*#__PURE__*/react.createElement(react.Suspense, {
          fallback: /*#__PURE__*/react.createElement('div', {
            style: {
              padding: '16px',
              color: '#888'
            }
          }, '로딩 중...')
        }, /*#__PURE__*/react.createElement(AiPanel, {
          ...props,
          servicesManager,
          commandsManager
        }));
      }
    }];
  },
  getCommandsModule: src_getCommandsModule,
  getHangingProtocolModule: getHangingProtocolModule
};
/* harmony default export */ const src = (werubAiExtension);

/***/ })

}]);