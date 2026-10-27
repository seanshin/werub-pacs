import { test, expect } from '@playwright/test';
import { apiLogin, authHeaders, API } from '../helpers/session';

// ai-governance — AI 모델 거버넌스/모니터링 API 표면 + RBAC.
test.describe('AI 거버넌스', () => {
  test('summary — 모델 수·드리프트·수용률·위반', async ({ request }) => {
    const s = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/governance/summary`, { headers: authHeaders(s) });
    expect(res.ok()).toBeTruthy();
    const b = await res.json();
    expect(b).toHaveProperty('total_models');
    expect(b).toHaveProperty('drift_alerts');
    expect(b).toHaveProperty('compliance_violations');
  });

  test('drift — 경보 목록', async ({ request }) => {
    const s = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/governance/drift`, { headers: authHeaders(s) });
    expect(res.ok()).toBeTruthy();
    expect(await res.json()).toHaveProperty('models');
  });

  test('trend — 모델 시계열', async ({ request }) => {
    const s = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/governance/models/medgemma-4b/trend?days=30`, {
      headers: authHeaders(s),
    });
    expect(res.ok()).toBeTruthy();
    expect(await res.json()).toHaveProperty('series');
  });

  test('compliance — admin 전용, 비-admin 403', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const ok = await request.get(`${API}/governance/compliance`, { headers: authHeaders(admin) });
    expect(ok.ok()).toBeTruthy();

    const rad = await apiLogin(request, 'radiologist');
    const denied = await request.get(`${API}/governance/compliance`, { headers: authHeaders(rad) });
    expect(denied.status()).toBe(403);
  });

  // SaMD 위반 판정 창 회귀(v13.37): 창이 없으면 과거 1건이 영구히 매일 재알림된다
  // (2026-06-12자 1건 때문에 30일간 19회 동일 알림 → 알림 피로가 새 위반을 묻음).
  // 진행 중 위반은 최근 창 기준, 이력은 별도 키로 계속 노출되어야 한다.
  test('compliance — SaMD 위반은 최근 창 기준, 이력은 별도 보존', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const res = await request.get(`${API}/governance/compliance`, { headers: authHeaders(admin) });
    expect(res.ok()).toBeTruthy();
    const c = await res.json();

    expect(typeof c.compliance_window_days, '판정 창이 노출되어야 함').toBe('number');
    expect(c.compliance_window_days).toBeGreaterThan(0);
    expect(Array.isArray(c.research_used_clinically)).toBeTruthy();
    expect(Array.isArray(c.research_used_clinically_all_time), '이력 키 누락').toBeTruthy();

    // 진행 중 위반은 이력의 부분집합 — 창을 넓히는 방향으로만 늘어난다
    for (const name of c.research_used_clinically) {
      expect(c.research_used_clinically_all_time, `${name}이 이력에 없음`).toContain(name);
    }

    // summary도 둘을 구분해 노출(대시보드에서 이력이 사라진 것처럼 보이지 않게)
    const sum = await request.get(`${API}/governance/summary`, { headers: authHeaders(admin) });
    const s = await sum.json();
    expect(s).toHaveProperty('compliance_violations_all_time');
    expect(s.compliance_violations).toBeLessThanOrEqual(s.compliance_violations_all_time);
  });

  // 거버넌스 확장 — on-demand 수용률 + 드리프트 서킷브레이커.
  test('summary — on-demand 수용률·자동격리 상태 필드', async ({ request }) => {
    const s = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/governance/summary`, { headers: authHeaders(s) });
    expect(res.ok()).toBeTruthy();
    const b = await res.json();
    expect(b).toHaveProperty('avg_ondemand_acceptance_rate_30d');
    expect(b).toHaveProperty('auto_quarantine_enabled');
    expect(typeof b.auto_quarantine_enabled).toBe('boolean');
  });

  test('actions — 거버넌스 액션 로그 배열', async ({ request }) => {
    const s = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/governance/actions?limit=20`, { headers: authHeaders(s) });
    expect(res.ok()).toBeTruthy();
    expect(Array.isArray((await res.json()).actions)).toBeTruthy();
  });

  test('reactivate — 비존재 모델 404, RBAC(rad 403)', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const notfound = await request.post(`${API}/governance/models/__nope__/reactivate`, {
      headers: authHeaders(admin),
    });
    expect(notfound.status()).toBe(404);

    const rad = await apiLogin(request, 'radiologist');
    const denied = await request.post(`${API}/governance/models/__nope__/reactivate`, {
      headers: authHeaders(rad),
    });
    expect(denied.status()).toBe(403);
  });

  test('inference feedback — 잘못된 decision 400, 무토큰 401', async ({ request }) => {
    const s = await apiLogin(request, 'radiologist');
    const bad = await request.post(`${API}/ai/inference/00000000-0000-0000-0000-000000000000/feedback`, {
      headers: authHeaders(s),
      data: { decision: 'maybe' },
    });
    expect(bad.status()).toBe(400);

    const noauth = await request.post(`${API}/ai/inference/00000000-0000-0000-0000-000000000000/feedback`, {
      data: { decision: 'accepted' },
    });
    expect(noauth.status()).toBe(401);
  });
});
