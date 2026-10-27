const API_BASE = '/pacs-api/api/v1';

export interface Report {
  id: string;
  study_instance_uid: string;
  patient_id: string;
  status: string;
  findings: string;
  impression: string;
  recommendation: string;
  urgency: string;
  author_name?: string;
  signed_at?: string;
  signed_by_name?: string;
  preliminary_by_name?: string;
  preliminary_at?: string;
  preliminary_content?: {
    findings: string;
    impression: string;
    recommendation: string;
    backed_up_at: string;
  };
}

export interface Template {
  id: string;
  name: string;
  modality: string;
  normal_template?: string;
  impression_template?: string;
  macros?: Record<string, string>;
}

type Callback = (data: any) => void;

class ReportService {
  public static REGISTRATION = {
    name: 'reportService',
    create: ({ servicesManager }) => new ReportService(servicesManager),
  };

  private servicesManager: any;
  private _token: string | null = null;
  private _currentReport: Report | null = null;
  private _templates: Template[] = [];
  private _studyUID: string | null = null;
  private _loading = false;
  private _listeners: Record<string, Callback[]> = {};

  constructor(servicesManager: any) {
    this.servicesManager = servicesManager;
    this._token = typeof localStorage !== 'undefined' ? localStorage.getItem('pacs_token') : null;
  }

  // --- Event system (simple, no PubSubService dependency) ---
  subscribe(event: string, callback: Callback) {
    if (!this._listeners[event]) this._listeners[event] = [];
    this._listeners[event].push(callback);
    return {
      unsubscribe: () => {
        this._listeners[event] = (this._listeners[event] || []).filter(cb => cb !== callback);
      },
    };
  }

  private _emit(event: string, data?: any) {
    (this._listeners[event] || []).forEach(cb => {
      try { cb(data); } catch (e) { console.error('[ReportService] event error:', e); }
    });
  }

  // --- Getters ---
  get token() { return this._token; }
  get currentReport() { return this._currentReport; }
  get templates() { return this._templates; }
  get studyUID() { return this._studyUID; }
  get loading() { return this._loading; }
  get isAuthenticated() { return !!this._token; }

  // --- Auth ---
  async login(username: string, password: string): Promise<boolean> {
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) return false;
      const data = await res.json();
      this._token = data.access_token;
      localStorage.setItem('pacs_token', this._token);
      this._emit('authChanged', { authenticated: true });
      return true;
    } catch {
      return false;
    }
  }

  logout() {
    this._token = null;
    localStorage.removeItem('pacs_token');
    this._emit('authChanged', { authenticated: false });
  }

  // --- API Helper ---
  private async api<T>(path: string, opts: RequestInit = {}): Promise<T | null> {
    // A10 fix: re-read the token from localStorage per request (same pattern as
    // AiService). Previously _token was only set in the constructor/login, so a
    // token rotated/refreshed in the admin tab after the viewer loaded made every
    // report save/sign/finalize 401 → silent loss of the physician's edits.
    this._token = localStorage.getItem('pacs_token');
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (this._token) headers['Authorization'] = `Bearer ${this._token}`;
    try {
      const res = await fetch(`${API_BASE}${path}`, { ...opts, headers: { ...headers, ...opts.headers } });
      if (res.status === 401) {
        this._token = null;
        localStorage.removeItem('pacs_token');
        this._emit('authChanged', { authenticated: false });
        return null;
      }
      if (!res.ok) return null;
      return res.json();
    } catch {
      return null;
    }
  }

  // --- Report CRUD ---
  async loadReport(studyUID: string): Promise<void> {
    if (studyUID === this._studyUID && this._currentReport) return;
    this._studyUID = studyUID;
    this._setLoading(true);
    const data = await this.api<{ results: Report[] }>(`/reports?study_uid=${studyUID}`);
    this._currentReport = data?.results?.length ? data.results[0] : null;
    this._emit('reportLoaded', { report: this._currentReport, studyUID });
    this._setLoading(false);
  }

  async save(fields: Partial<Report>): Promise<Report | null> {
    this._setLoading(true);
    let result: Report | null = null;
    if (this._currentReport) {
      result = await this.api<Report>(`/reports/${this._currentReport.id}`, {
        method: 'PATCH', body: JSON.stringify(fields),
      });
    } else if (this._studyUID) {
      result = await this.api<Report>('/reports', {
        method: 'POST',
        body: JSON.stringify({ study_instance_uid: this._studyUID, patient_id: '-', ...fields }),
      });
    }
    if (result) {
      this._currentReport = result;
      this._emit('reportSaved', { report: result });
      this._emit('reportLoaded', { report: result, studyUID: this._studyUID });
    }
    this._setLoading(false);
    return result;
  }

  async sign(asPreliminary = false): Promise<Report | null> {
    if (!this._currentReport) return null;
    this._setLoading(true);
    const qs = asPreliminary ? '?as_preliminary=true' : '';
    const result = await this.api<Report>(`/reports/${this._currentReport.id}/sign${qs}`, { method: 'POST' });
    if (result) {
      this._currentReport = result;
      this._emit('reportSigned', { report: result });
    }
    this._setLoading(false);
    return result;
  }

  async finalize(updates?: Partial<Report>): Promise<Report | null> {
    if (!this._currentReport) return null;
    this._setLoading(true);
    const result = await this.api<Report>(`/reports/${this._currentReport.id}/finalize`, {
      method: 'POST',
      body: updates ? JSON.stringify(updates) : undefined,
    });
    if (result) {
      this._currentReport = result;
      this._emit('reportSigned', { report: result });
    }
    this._setLoading(false);
    return result;
  }

  async addendum(): Promise<Report | null> {
    if (!this._currentReport) return null;
    const result = await this.api<Report>(`/reports/${this._currentReport.id}/addendum`, {
      method: 'POST', body: JSON.stringify({ findings: '', impression: '' }),
    });
    if (result) { this._currentReport = result; this._emit('reportLoaded', { report: result }); }
    return result;
  }

  // --- Key Images (KOS) ---
  async saveKeyImages(
    sopUIDs: string[],
    description?: string
  ): Promise<{ orthanc_id: string; key_image_count: number; missing: string[] } | null> {
    if (!sopUIDs.length) return null;
    this._setLoading(true);
    const result = await this.api<{ orthanc_id: string; key_image_count: number; missing: string[] }>(
      '/reports/key-images',
      { method: 'POST', body: JSON.stringify({ sop_instance_uids: sopUIDs, description }) }
    );
    this._setLoading(false);
    if (result) this._emit('keyImagesSaved', result);
    return result;
  }

  // --- Annotations (measurements + key images persistence) ---
  async loadAnnotations(
    studyUID: string
  ): Promise<{ measurements: any[]; key_images: any[]; notes: string | null } | null> {
    return this.api(`/studies/${studyUID}/annotations`);
  }

  async saveAnnotations(
    studyUID: string,
    payload: { measurements?: any[]; key_images?: any[]; notes?: string | null }
  ): Promise<any> {
    const result = await this.api(`/studies/${studyUID}/annotations`, {
      method: 'POST',
      body: JSON.stringify({
        measurements: payload.measurements || [],
        key_images: payload.key_images || [],
        notes: payload.notes ?? null,
      }),
    });
    if (result) this._emit('annotationsSaved', result);
    return result;
  }

  async loadTemplates(): Promise<void> {
    if (this._templates.length > 0) return;
    const data = await this.api<{ templates: Template[] }>('/templates');
    if (data?.templates) {
      this._templates = data.templates;
      this._emit('templatesLoaded', { templates: this._templates });
    }
  }

  private _setLoading(val: boolean) {
    this._loading = val;
    this._emit('loadingChanged', { loading: val });
  }

  resetForStudy(studyUID: string) {
    this._studyUID = null;
    this._currentReport = null;
    this.loadReport(studyUID);
  }
}

export { ReportService };
