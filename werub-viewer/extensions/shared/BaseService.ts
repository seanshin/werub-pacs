/**
 * BaseService — shared event system and API helper for OHIF extension services.
 * Used by AiService and ReportService to avoid code duplication.
 */
const API_BASE = '/pacs-api/api/v1';

export type Callback = (data: any) => void;

export class BaseService {
  protected _listeners: Record<string, Callback[]> = {};
  protected _token: string | null = null;

  constructor() {
    this._refreshToken();
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

  protected _emit(event: string, data?: any) {
    (this._listeners[event] || []).forEach(cb => {
      try { cb(data); } catch (e) { console.error(`[${this.constructor.name}]`, e); }
    });
  }

  // --- Token management ---
  protected _refreshToken() {
    this._token = typeof localStorage !== 'undefined' ? localStorage.getItem('pacs_token') : null;
  }

  // --- API helper ---
  protected async api<T>(path: string, opts: RequestInit = {}): Promise<T | null> {
    this._refreshToken();
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (this._token) headers['Authorization'] = `Bearer ${this._token}`;
    try {
      const res = await fetch(`${API_BASE}${path}`, { ...opts, headers: { ...headers, ...opts.headers } });
      if (!res.ok) {
        console.warn(`[${this.constructor.name}] API ${opts.method || 'GET'} ${path} returned ${res.status}`);
        return null;
      }
      return res.json();
    } catch (err) {
      console.warn(`[${this.constructor.name}] API ${path} failed:`, err);
      return null;
    }
  }
}

export { API_BASE };
