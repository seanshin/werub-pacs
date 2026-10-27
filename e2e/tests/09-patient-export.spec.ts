import { test, expect } from '@playwright/test';
import { createHmac } from 'crypto';

// patient-portal — 외부 포털 → PACS 결과 추출 인프라
// 서비스 토큰(HIS 공유 시크릿, scope=patient-export, mrn 봉인) 흐름과 부정 케이스.
// 기능은 기본 비활성(patient_export_enabled=false) — 인증 가드는 항상 검증되고,
// 해피패스는 EXPORT_DISABLED(503)이면 skip(운영 무영향 철학).
const BASE = process.env.PACS_BASE_URL || 'https://his.example.org';
const API = `${BASE}/pacs-api/api/v1/patient-export`;
const SECRET =
  process.env.HOSPITALRUN_AUTH_SECRET || 'change-me-to-a-random-string-at-least-32-chars';
const MRN = process.env.PEXPORT_MRN || 'P2026-0005';

function b64url(buf: Buffer | string): string {
  return Buffer.from(buf).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function signToken(claims: Record<string, unknown>): string {
  const header = b64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const payload = b64url(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 600, ...claims }));
  const sig = b64url(createHmac('sha256', SECRET).update(`${header}.${payload}`).digest());
  return `${header}.${payload}.${sig}`;
}
const exportToken = (mrn: string) =>
  signToken({ scope: 'patient-export', mrn, iss: 'patient-portal' });

test.describe('환자 결과 추출 (patient-portal)', () => {
  test('요청 → 폴링 ready → 게이트웨이 수령 → 1회용(410) [활성 시]', async ({ request }) => {
    const create = await request.post(`${API}/requests`, {
      headers: { Authorization: `Bearer ${exportToken(MRN)}` },
      data: { mrn: MRN, purpose: 'patient_view' },
    });
    // 503=기능 비활성 / 401·403=전용 시크릿(PATIENT_EXPORT_SECRET, v11.8 SSO 분리) 미주입.
    // 해피패스는 운영자 시크릿이 주입된 환경에서만 가능 — 그 외엔 skip(운영 무영향 철학).
    test.skip([401, 403, 503].includes(create.status()),
      '기능 비활성 또는 전용 시크릿(PATIENT_EXPORT_SECRET) 미주입 — 해피패스 skip');
    expect(create.status()).toBe(202);
    const { request_id } = await create.json();

    let status = 'processing';
    let dtok = '';
    let key = '';
    for (let i = 0; i < 30 && status === 'processing'; i++) {
      const res = await request.get(`${API}/requests/${request_id}`, {
        headers: { Authorization: `Bearer ${exportToken(MRN)}` },
      });
      const j = await res.json();
      status = j.status;
      if (status === 'ready') {
        dtok = j.download_token;
        key = j.package_key;
        expect(j.study_count).toBeGreaterThan(0);
      }
      if (status === 'processing') await new Promise(r => setTimeout(r, 2000));
    }
    expect(status, 'export must become ready').toBe('ready');
    expect(dtok).toBeTruthy();
    expect(key).toBeTruthy();

    const dl = await request.get(`${BASE}/portal-export/${dtok}`);
    expect(dl.status()).toBe(200);
    expect((await dl.body()).length).toBeGreaterThan(1000);

    const again = await request.get(`${BASE}/portal-export/${dtok}`);
    expect(again.status()).toBe(410);
  });

  test('mrn 봉인 — 토큰 mrn ≠ body mrn 이면 403 (활성 무관)', async ({ request }) => {
    const res = await request.post(`${API}/requests`, {
      headers: { Authorization: `Bearer ${exportToken('OTHER-MRN')}` },
      data: { mrn: MRN },
    });
    expect(res.status()).toBe(403); // mrn 불일치는 enable 게이트보다 먼저
  });

  test('인증 가드 — 토큰 없음 401, scope 누락 403 (활성 무관)', async ({ request }) => {
    const noTok = await request.post(`${API}/requests`, { data: { mrn: MRN } });
    expect(noTok.status()).toBe(401);

    const wrongScope = signToken({ mrn: MRN, iss: 'x' });
    const bad = await request.post(`${API}/requests`, {
      headers: { Authorization: `Bearer ${wrongScope}` },
      data: { mrn: MRN },
    });
    expect(bad.status()).toBe(403);
  });

  test('게이트웨이 — 무효 토큰 410', async ({ request }) => {
    const res = await request.get(`${BASE}/portal-export/deadbeefdeadbeef`);
    expect(res.status()).toBe(410);
  });
});
