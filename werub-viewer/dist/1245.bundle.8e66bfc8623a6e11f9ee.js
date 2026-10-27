"use strict";
(globalThis["webpackChunk"] = globalThis["webpackChunk"] || []).push([[1245],{

/***/ 1245:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

// ESM COMPAT FLAG
__webpack_require__.r(__webpack_exports__);

// EXPORTS
__webpack_require__.d(__webpack_exports__, {
  "default": () => (/* binding */ src)
});

;// ../../../extensions/werub-report/package.json
const package_namespaceObject = /*#__PURE__*/JSON.parse('{"UU":"@ohif/extension-werub-report"}');
;// ../../../extensions/werub-report/src/id.ts

const id = package_namespaceObject.UU;
// EXTERNAL MODULE: ../../../node_modules/react/index.js
var react = __webpack_require__(86326);
;// ../../../extensions/werub-report/src/services/ReportService.ts
var _ReportService;
const API_BASE = '/pacs-api/api/v1';
class ReportService {
  constructor(servicesManager) {
    this.servicesManager = void 0;
    this._token = null;
    this._currentReport = null;
    this._templates = [];
    this._studyUID = null;
    this._loading = false;
    this._listeners = {};
    this.servicesManager = servicesManager;
    this._token = typeof localStorage !== 'undefined' ? localStorage.getItem('pacs_token') : null;
  }

  // --- Event system (simple, no PubSubService dependency) ---
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
        console.error('[ReportService] event error:', e);
      }
    });
  }

  // --- Getters ---
  get token() {
    return this._token;
  }
  get currentReport() {
    return this._currentReport;
  }
  get templates() {
    return this._templates;
  }
  get studyUID() {
    return this._studyUID;
  }
  get loading() {
    return this._loading;
  }
  get isAuthenticated() {
    return !!this._token;
  }

  // --- Auth ---
  async login(username, password) {
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          username,
          password
        })
      });
      if (!res.ok) return false;
      const data = await res.json();
      this._token = data.access_token;
      localStorage.setItem('pacs_token', this._token);
      this._emit('authChanged', {
        authenticated: true
      });
      return true;
    } catch {
      return false;
    }
  }
  logout() {
    this._token = null;
    localStorage.removeItem('pacs_token');
    this._emit('authChanged', {
      authenticated: false
    });
  }

  // --- API Helper ---
  async api(path, opts = {}) {
    // A10 fix: re-read the token from localStorage per request (same pattern as
    // AiService). Previously _token was only set in the constructor/login, so a
    // token rotated/refreshed in the admin tab after the viewer loaded made every
    // report save/sign/finalize 401 → silent loss of the physician's edits.
    this._token = localStorage.getItem('pacs_token');
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
        this._token = null;
        localStorage.removeItem('pacs_token');
        this._emit('authChanged', {
          authenticated: false
        });
        return null;
      }
      if (!res.ok) return null;
      return res.json();
    } catch {
      return null;
    }
  }

  // --- Report CRUD ---
  async loadReport(studyUID) {
    if (studyUID === this._studyUID && this._currentReport) return;
    this._studyUID = studyUID;
    this._setLoading(true);
    const data = await this.api(`/reports?study_uid=${studyUID}`);
    this._currentReport = data?.results?.length ? data.results[0] : null;
    this._emit('reportLoaded', {
      report: this._currentReport,
      studyUID
    });
    this._setLoading(false);
  }
  async save(fields) {
    this._setLoading(true);
    let result = null;
    if (this._currentReport) {
      result = await this.api(`/reports/${this._currentReport.id}`, {
        method: 'PATCH',
        body: JSON.stringify(fields)
      });
    } else if (this._studyUID) {
      result = await this.api('/reports', {
        method: 'POST',
        body: JSON.stringify({
          study_instance_uid: this._studyUID,
          patient_id: '-',
          ...fields
        })
      });
    }
    if (result) {
      this._currentReport = result;
      this._emit('reportSaved', {
        report: result
      });
      this._emit('reportLoaded', {
        report: result,
        studyUID: this._studyUID
      });
    }
    this._setLoading(false);
    return result;
  }
  async sign(asPreliminary = false) {
    if (!this._currentReport) return null;
    this._setLoading(true);
    const qs = asPreliminary ? '?as_preliminary=true' : '';
    const result = await this.api(`/reports/${this._currentReport.id}/sign${qs}`, {
      method: 'POST'
    });
    if (result) {
      this._currentReport = result;
      this._emit('reportSigned', {
        report: result
      });
    }
    this._setLoading(false);
    return result;
  }
  async finalize(updates) {
    if (!this._currentReport) return null;
    this._setLoading(true);
    const result = await this.api(`/reports/${this._currentReport.id}/finalize`, {
      method: 'POST',
      body: updates ? JSON.stringify(updates) : undefined
    });
    if (result) {
      this._currentReport = result;
      this._emit('reportSigned', {
        report: result
      });
    }
    this._setLoading(false);
    return result;
  }
  async addendum() {
    if (!this._currentReport) return null;
    const result = await this.api(`/reports/${this._currentReport.id}/addendum`, {
      method: 'POST',
      body: JSON.stringify({
        findings: '',
        impression: ''
      })
    });
    if (result) {
      this._currentReport = result;
      this._emit('reportLoaded', {
        report: result
      });
    }
    return result;
  }

  // --- Key Images (KOS) ---
  async saveKeyImages(sopUIDs, description) {
    if (!sopUIDs.length) return null;
    this._setLoading(true);
    const result = await this.api('/reports/key-images', {
      method: 'POST',
      body: JSON.stringify({
        sop_instance_uids: sopUIDs,
        description
      })
    });
    this._setLoading(false);
    if (result) this._emit('keyImagesSaved', result);
    return result;
  }

  // --- Annotations (measurements + key images persistence) ---
  async loadAnnotations(studyUID) {
    return this.api(`/studies/${studyUID}/annotations`);
  }
  async saveAnnotations(studyUID, payload) {
    const result = await this.api(`/studies/${studyUID}/annotations`, {
      method: 'POST',
      body: JSON.stringify({
        measurements: payload.measurements || [],
        key_images: payload.key_images || [],
        notes: payload.notes ?? null
      })
    });
    if (result) this._emit('annotationsSaved', result);
    return result;
  }
  async loadTemplates() {
    if (this._templates.length > 0) return;
    const data = await this.api('/templates');
    if (data?.templates) {
      this._templates = data.templates;
      this._emit('templatesLoaded', {
        templates: this._templates
      });
    }
  }
  _setLoading(val) {
    this._loading = val;
    this._emit('loadingChanged', {
      loading: val
    });
  }
  resetForStudy(studyUID) {
    this._studyUID = null;
    this._currentReport = null;
    this.loadReport(studyUID);
  }
}
_ReportService = ReportService;
ReportService.REGISTRATION = {
  name: 'reportService',
  create: ({
    servicesManager
  }) => new _ReportService(servicesManager)
};

;// ../../../extensions/werub-report/src/getCommandsModule.ts
function getCommandsModule({
  servicesManager
}) {
  return {
    definitions: {
      saveReport: {
        commandFn: () => {
          const {
            reportService
          } = servicesManager.services;
          if (reportService) reportService.save({});
        }
      },
      signReport: {
        commandFn: () => {
          const {
            reportService
          } = servicesManager.services;
          if (reportService) reportService.sign();
        }
      },
      toggleReportPanel: {
        commandFn: () => {
          const {
            panelService
          } = servicesManager.services;
          if (panelService) {
            panelService.activatePanel('@ohif/extension-werub-report.panelModule.reportPanel');
          }
        }
      },
      openSecondWindow: {
        commandFn: () => {
          // Get current StudyInstanceUIDs from URL
          const params = new URLSearchParams(window.location.search);
          const studyUIDs = params.get('StudyInstanceUIDs') || '';
          if (!studyUIDs) return;

          // Open a second viewer window with the same study
          const basePath = window.location.pathname.replace(/\/[^/]*$/, '');
          const url = `${basePath}/viewer?StudyInstanceUIDs=${studyUIDs}`;
          const screenWidth = window.screen.availWidth;
          const screenHeight = window.screen.availHeight;

          // Position: right half of screen
          window.open(url, 'werub-secondary', `width=${Math.floor(screenWidth / 2)},height=${screenHeight},left=${Math.floor(screenWidth / 2)},top=0,toolbar=no,menubar=no,location=no`);
        }
      }
    },
    defaultContext: 'VIEWER'
  };
}
/* harmony default export */ const src_getCommandsModule = (getCommandsModule);
;// ../../../extensions/werub-report/src/index.ts




const werubReportExtension = {
  id: id,
  preRegistration({
    servicesManager
  }) {
    try {
      servicesManager.registerService(ReportService.REGISTRATION);
    } catch (e) {
      console.error('[werub-report] ReportService registration failed:', e);
    }
  },
  getPanelModule({
    servicesManager,
    commandsManager
  }) {
    return [{
      name: 'reportPanel',
      iconName: 'tab-patient-info',
      iconLabel: '판독',
      label: '판독 리포트',
      component: props => {
        const ReportPanel = /*#__PURE__*/react.lazy(() => Promise.all(/* import() */[__webpack_require__.e(4019), __webpack_require__.e(3584), __webpack_require__.e(6409), __webpack_require__.e(7412), __webpack_require__.e(1256)]).then(__webpack_require__.bind(__webpack_require__, 79944)));
        return /*#__PURE__*/react.createElement(react.Suspense, {
          fallback: /*#__PURE__*/react.createElement('div', {
            style: {
              padding: '16px',
              color: '#888'
            }
          }, '로딩 중...')
        }, /*#__PURE__*/react.createElement(ReportPanel, {
          ...props,
          servicesManager,
          commandsManager
        }));
      }
    }];
  },
  getCommandsModule: src_getCommandsModule
};
/* harmony default export */ const src = (werubReportExtension);

/***/ })

}]);