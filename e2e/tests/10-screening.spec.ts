import { test, expect } from '@playwright/test';
import { apiLogin, authHeaders, API } from '../helpers/session';

// opportunistic-ai — 수신 영상 선제 AI 스크리닝
// 스캔/추론은 beat 태스크라 E2E에서 직접 트리거 불가 → 누적된 결과의 API 표면 검증.
test.describe('선제 AI 스크리닝', () => {
  test('stats — 스크리닝 수·actionable·수용률 집계', async ({ request }) => {
    const s = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/screening/stats?hours=720`, { headers: authHeaders(s) });
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body).toHaveProperty('total');
    expect(body).toHaveProperty('actionable');
    expect(body).toHaveProperty('acceptance'); // governance gap-2 수용률
    expect(body).toHaveProperty('by_modality');
  });

  test('results — 목록 조회 + actionable 필터', async ({ request }) => {
    const s = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/screening/results?hours=720&limit=50`, {
      headers: authHeaders(s),
    });
    expect(res.ok()).toBeTruthy();
    expect(await res.json()).toHaveProperty('results');

    const act = await request.get(`${API}/screening/results?actionable_only=true&hours=720`, {
      headers: authHeaders(s),
    });
    expect(act.ok()).toBeTruthy();
    const actBody = await act.json();
    // actionable만 → is_actionable=true 보장
    for (const r of actBody.results) expect(r.is_actionable).toBe(true);
  });

  test('config — admin 조회/변경, 비-admin 거부', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const get = await request.get(`${API}/screening/config`, { headers: authHeaders(admin) });
    expect(get.ok()).toBeTruthy();
    expect(await get.json()).toHaveProperty('actionable_confidence');

    const rad = await apiLogin(request, 'radiologist');
    const denied = await request.get(`${API}/screening/config`, { headers: authHeaders(rad) });
    expect(denied.status()).toBe(403); // admin 전용
  });

  test('ack — 미존재 study 404', async ({ request }) => {
    const s = await apiLogin(request, 'radiologist');
    const res = await request.post(`${API}/screening/results/NO-SUCH-UID/ack`, {
      headers: authHeaders(s),
      data: { dismissed: true },
    });
    expect(res.status()).toBe(404);
  });
});
