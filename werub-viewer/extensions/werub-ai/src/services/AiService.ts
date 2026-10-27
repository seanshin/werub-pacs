const API_BASE = '/pacs-api/api/v1';

export interface AiAnalysisResult {
  findings?: string;
  impression?: string;
  recommendations?: string;
  duration_ms?: number;
}

export interface ComparisonResult {
  text?: string;
  progression?: string;
  message?: string;
}

export interface SoapResult {
  summary?: { subjective: string; objective: string; assessment: string; plan: string };
  icd_codes?: string[];
  duration_ms?: number;
  error?: string;
}

export interface DdxResult {
  differential_diagnosis?: Array<{
    condition?: string; name?: string; diagnosis?: string;
    icd_code?: string; icd10?: string;
    probability?: string; confidence?: string;
  }>;
  duration_ms?: number;
  error?: string;
}

export interface ServerStatus {
  ollama?: string;
  models?: string[];
  status?: string;
}

type Callback = (data: any) => void;

class AiService {
  public static REGISTRATION = {
    name: 'aiService',
    create: ({ servicesManager }) => new AiService(servicesManager),
  };

  private servicesManager: any;
  private _listeners: Record<string, Callback[]> = {};
  private _token: string | null = null;
  private _lastResult: AiAnalysisResult | null = null;
  private _loading = false;

  constructor(servicesManager: any) {
    this.servicesManager = servicesManager;
    this._token = typeof localStorage !== 'undefined' ? localStorage.getItem('pacs_token') : null;
  }

  // --- Event system ---
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
      try { cb(data); } catch (e) { console.error('[AiService]', e); }
    });
  }

  // --- Getters ---
  get loading() { return this._loading; }
  get lastResult() { return this._lastResult; }

  // --- API helper ---
  private async api<T>(path: string, opts: RequestInit = {}): Promise<T | null> {
    this._token = typeof localStorage !== 'undefined' ? localStorage.getItem('pacs_token') : null;
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (this._token) headers['Authorization'] = `Bearer ${this._token}`;
    try {
      const res = await fetch(`${API_BASE}${path}`, { ...opts, headers: { ...headers, ...opts.headers } });
      if (res.status === 401) {
        // K9: 토큰 만료 시 ReportService와 동일하게 재인증 유도(무한 "분석 실패" 방지)
        try {
          localStorage.removeItem('pacs_token');
          this._emit('authChanged', { authenticated: false });
        } catch {}
        return null;
      }
      if (!res.ok) return null;
      return res.json();
    } catch {
      return null;
    }
  }

  private _setLoading(val: boolean) {
    this._loading = val;
    this._emit('loadingChanged', { loading: val });
  }

  // --- AI API Methods ---

  // Available active AI models (for the model picker).
  async getModels(): Promise<Array<{ id: string; name: string; clinical_use?: string; modalities?: string; avg_inference_time?: number }>> {
    const res = await this.api<any>('/ai/models?active_only=true');
    return res?.models || [];
  }

  async analyzeStudy(studyUID: string, modelName?: string | null): Promise<AiAnalysisResult | null> {
    this._setLoading(true);
    const res = await this.api<any>('/ai/analyze-and-draft', {
      method: 'POST',
      body: JSON.stringify({
        study_instance_uid: studyUID,
        auto_create_report: false,
        ...(modelName ? { model_name: modelName } : {}),
      }),
    });
    this._setLoading(false);
    if (res?.ai_analysis) {
      this._lastResult = res.ai_analysis;
      this._emit('analysisComplete', { result: res.ai_analysis, type: 'analyze' });
      return res.ai_analysis;
    }
    this._emit('analysisError', { error: 'AI 분석 실패', type: 'analyze' });
    return null;
  }

  async compareStudies(studyUID: string): Promise<ComparisonResult | null> {
    this._setLoading(true);
    const res = await this.api<any>('/ai/compare-studies', {
      method: 'POST',
      body: JSON.stringify({ current_study_uid: studyUID }),
    });
    this._setLoading(false);
    if (res?.comparison) {
      this._emit('analysisComplete', { result: res.comparison, type: 'compare' });
      return res.comparison;
    }
    this._emit('analysisComplete', { result: { message: res?.message || '이전 검사 없음' }, type: 'compare' });
    return res;
  }

  async soapSummary(findings: string, impression: string): Promise<SoapResult | null> {
    this._setLoading(true);
    const res = await this.api<SoapResult>('/ai/soap-summary', {
      method: 'POST',
      body: JSON.stringify({ findings, impression, clinical_info: '' }),
    });
    this._setLoading(false);
    if (res) {
      this._emit('analysisComplete', { result: res, type: 'soap' });
    }
    return res;
  }

  async differentialDiagnosis(symptoms: string, findings: string): Promise<DdxResult | null> {
    this._setLoading(true);
    const res = await this.api<DdxResult>('/ai/differential-diagnosis', {
      method: 'POST',
      body: JSON.stringify({ symptoms, findings }),
    });
    this._setLoading(false);
    if (res) {
      this._emit('analysisComplete', { result: res, type: 'ddx' });
    }
    return res;
  }

  async getServerStatus(): Promise<ServerStatus | null> {
    return this.api<ServerStatus>('/ai/server-status');
  }

  // --- 저장된 표준 추론 결과 (TID 1500 SR을 만든 잡) ---
  // OHIF의 측정-SR 뷰포트는 좌표 없는 범주형 AI SR을 렌더하지 못하므로,
  // 패널에서 저장된 추론 결과(소견/신뢰도)를 직접 표시한다.
  async getStudyResult(studyUID: string): Promise<any | null> {
    const res = await this.api<any>(
      `/ai/jobs?study_uid=${encodeURIComponent(studyUID)}&status=completed&limit=1`
    );
    return res?.results?.length ? res.results[0] : null;
  }

  // --- Orchestration Pipeline ---
  async getProductionPipeline(): Promise<{ pipeline: string } | null> {
    const res = await this.api<Record<string, any>>('/ai/orchestration/production');
    return res?.reading || null;
  }

  async runPipeline(pipeline: string, studyUID: string): Promise<any> {
    this._setLoading(true);
    const res = await this.api<any>('/ai/orchestration/run', {
      method: 'POST',
      body: JSON.stringify({ pipeline, study_instance_uid: studyUID, debug: false }),
    });
    this._setLoading(false);
    if (res && !res.error) {
      this._emit('analysisComplete', { result: res, type: 'pipeline' });
      return res;
    }
    this._emit('analysisError', { error: res?.error || '파이프라인 실행 실패', type: 'pipeline' });
    return null;
  }

  // --- DICOM SR 저장 ---
  async saveAsSR(studyUID: string, findings: string, impression: string): Promise<any> {
    return this.api<any>('/reports/structured', {
      method: 'POST',
      body: JSON.stringify({
        study_instance_uid: studyUID,
        schema_type: 'basic_diagnostic',
        structured_data: { findings, impression },
        source: 'ai_analysis',
      }),
    });
  }

  // --- Report Panel 연동 ---
  async applyToReport(data: { findings?: string; impression?: string; recommendation?: string }, studyUID?: string) {
    // 1. OHIF internal report service (non-blocking)
    try {
      const { reportService } = this.servicesManager.services;
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
          recommendation: data.recommendation || '',
        }),
      });
      console.log('[AiService] apply-to-report result:', res);
    }

    // 3. Broadcast to reading view for real-time sync
    try {
      const ch = new BroadcastChannel('pacs-ai-result');
      ch.postMessage({ type: 'ai_applied', studyUID, data });
      ch.close();
    } catch {}
    // Fallback: localStorage event (cross-tab)
    try {
      localStorage.setItem('pacs-ai-applied', JSON.stringify({ studyUID, data, ts: Date.now() }));
    } catch {}

  }
}

export { AiService };
