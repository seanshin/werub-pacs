import { APIRequestContext, BrowserContext, expect } from '@playwright/test';

export const BASE = process.env.PACS_BASE_URL || 'https://his.example.org';
export const API = `${BASE}/pacs-api/api/v1`;

// 시드 테스트 계정 (backend /auth/seed-test-accounts, docs/pilot-test-checklist.md)
export const ACCOUNTS = {
  admin: { username: 'admin', password: process.env.PACS_ADMIN_PW || 'CHANGE_ME' },
  radiologist: { username: 'dr.kim', password: process.env.PACS_RADIOLOGIST_PW || 'CHANGE_ME' },
  researcher: { username: 'res.choi', password: process.env.PACS_RESEARCHER_PW || 'CHANGE_ME' },
} as const;

export type Role = keyof typeof ACCOUNTS;
export type Session = { access_token: string; role: string; username: string };

// 로그인 rate limit(5/min/계정) 회피 — worker 프로세스 내 토큰 캐시
const cache = new Map<Role, Session>();

export async function apiLogin(request: APIRequestContext, role: Role): Promise<Session> {
  const hit = cache.get(role);
  if (hit) return hit;
  const { username, password } = ACCOUNTS[role];
  const res = await request.post(`${API}/auth/login`, { data: { username, password } });
  expect(res.ok(), `${role} 로그인 실패 (${res.status()})`).toBeTruthy();
  const body = (await res.json()) as Session;
  cache.set(role, body);
  return body;
}

// admin/뷰어 공통: localStorage pacs_token 주입 (admin/src/lib/api.ts, AiService.ts와 동일 키)
export async function injectSession(context: BrowserContext, s: Session) {
  await context.addInitScript(
    ([t, r, u]) => {
      localStorage.setItem('pacs_token', t);
      localStorage.setItem('pacs_role', r);
      localStorage.setItem('pacs_user', u);
    },
    [s.access_token, s.role, s.username],
  );
}

export function authHeaders(s: Session) {
  return { Authorization: `Bearer ${s.access_token}` };
}
