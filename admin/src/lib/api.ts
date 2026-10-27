const API_BASE = '/pacs-api';

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('pacs_token') : null;
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
  });
  if (!res.ok) {
    if (res.status === 401 && typeof window !== 'undefined') {
      // Token expired or invalid — auto logout
      localStorage.removeItem('pacs_token');
      localStorage.removeItem('pacs_role');
      localStorage.removeItem('pacs_user');
      window.location.href = '/pacs-admin';
      throw new Error('세션이 만료되었습니다. 다시 로그인하세요.');
    }
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `API Error ${res.status}`);
  }
  return res.json();
}

export async function login(username: string, password: string) {
  const res = await apiFetch<{ access_token: string; role: string; username: string }>(
    '/api/v1/auth/login',
    { method: 'POST', body: JSON.stringify({ username, password }) }
  );
  localStorage.setItem('pacs_token', res.access_token);
  localStorage.setItem('pacs_role', res.role);
  localStorage.setItem('pacs_user', res.username);
  return res;
}

export function logout() {
  localStorage.removeItem('pacs_token');
  localStorage.removeItem('pacs_role');
  localStorage.removeItem('pacs_user');
}

export function getUser() {
  if (typeof window === 'undefined') return null;
  const token = localStorage.getItem('pacs_token');
  if (!token) return null;

  let username = localStorage.getItem('pacs_user') || '';
  let role = localStorage.getItem('pacs_role') || '';

  // SSO token: extract user info from JWT payload if not stored
  if (!username && token.includes('.')) {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      username = payload.username || payload.email || payload.sub || '';
      role = payload.role || '';
      if (username) localStorage.setItem('pacs_user', username);
      if (role) localStorage.setItem('pacs_role', role);
    } catch {}
  }

  return { username, role };
}
