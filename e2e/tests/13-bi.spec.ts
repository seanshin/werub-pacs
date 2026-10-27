import { test, expect } from '@playwright/test';
import { apiLogin, authHeaders, injectSession, API, BASE } from '../helpers/session';

// bi-report — 경영/운영 BI API 표면(판독 KPI·수신량·CSV·월간이력) + RBAC + 페이지 스모크.
test.describe('경영/운영 BI', () => {
  test('operational — 판독 KPI·수신·모달리티·판독의 구조', async ({ request }) => {
    const s = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/bi/operational?days=90&months=12`, {
      headers: authHeaders(s),
    });
    expect(res.ok()).toBeTruthy();
    const b = await res.json();
    // 판독 KPI
    expect(b.summary).toHaveProperty('total');
    expect(b.summary).toHaveProperty('completion_rate');
    expect(b.summary).toHaveProperty('p90_tat_h');
    // 수신(접수) 관점 — 미판독 backlog 가시화
    expect(b.reception).toHaveProperty('received');
    expect(b.reception).toHaveProperty('unread');
    expect(b.reception).toHaveProperty('read_rate');
    expect(Array.isArray(b.reception.by_origin)).toBeTruthy();
    // 추이·모달리티·판독의
    expect(Array.isArray(b.volume_trend)).toBeTruthy();
    expect(Array.isArray(b.modality)).toBeTruthy();
    expect(Array.isArray(b.readers)).toBeTruthy();
    // 수신 ≥ 판독완료 (LEFT JOIN 정합 — 미판독은 음수 불가)
    expect(b.reception.received).toBeGreaterThanOrEqual(b.reception.read_done);
    expect(b.reception.unread).toBe(b.reception.received - b.reception.read_done);
  });

  test('export — CSV(UTF-8 BOM·6섹션)', async ({ request }) => {
    const s = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/bi/export?days=90&months=12`, {
      headers: authHeaders(s),
    });
    expect(res.ok()).toBeTruthy();
    expect(res.headers()['content-type']).toContain('text/csv');
    const body = await res.text();
    expect(body.charCodeAt(0)).toBe(0xfeff); // UTF-8 BOM (Excel 한글)
    expect(body).toContain('[수신 요약]');
    expect(body).toContain('[판독 KPI]');
    expect(body).toContain('[모달리티별 판독]');
  });

  test('monthly-history — 이력 배열', async ({ request }) => {
    const s = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/bi/monthly-history?limit=12`, {
      headers: authHeaders(s),
    });
    expect(res.ok()).toBeTruthy();
    expect(Array.isArray((await res.json()).reports)).toBeTruthy();
  });

  test('run-monthly — admin 전용, 비-admin 403', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const ok = await request.post(`${API}/bi/run-monthly`, { headers: authHeaders(admin) });
    expect(ok.ok()).toBeTruthy();
    expect((await ok.json()).status).toBe('queued');

    const rad = await apiLogin(request, 'radiologist');
    const denied = await request.post(`${API}/bi/run-monthly`, { headers: authHeaders(rad) });
    expect(denied.status()).toBe(403);
  });

  // 기간 경계 회귀(v13.35): beat는 KST 06:00에 뜨는데 DB 세션 TZ는 UTC라,
  // SQL CURRENT_DATE에 경계를 맡기면 직전 달이 한 달 더 밀렸다(7월분 영구 누락).
  // 결정적 경계 단언은 IT(scripts/server/it-bi-period.sh)가 담당하고,
  // 여기서는 백필 API 표면(period 인자·형식 검증·이력 반영)을 지킨다.
  test('run-monthly period — 백필 인자 수용·형식 검증·이력 반영', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');

    // 형식 위반은 라우터에서 거부(태스크까지 못 감)
    for (const bad of ['2026-7', '202607', '2026-13-01', 'abcd-ef']) {
      const res = await request.post(`${API}/bi/run-monthly?period=${bad}`, {
        headers: authHeaders(admin),
      });
      expect(res.status(), `period=${bad}`).toBe(422);
    }

    // 유효 period는 큐 등록 + 응답에 그대로 반영
    const target = '2026-07';
    const ok = await request.post(`${API}/bi/run-monthly?period=${target}`, {
      headers: authHeaders(admin),
    });
    expect(ok.ok()).toBeTruthy();
    const body = await ok.json();
    expect(body.status).toBe('queued');
    expect(body.period).toBe(target);

    // 비동기 집계 → 이력에 해당 월이 나타남
    let months: string[] = [];
    for (let i = 0; i < 15; i++) {
      const hist = await request.get(`${API}/bi/monthly-history?limit=60`, {
        headers: authHeaders(admin),
      });
      months = (await hist.json()).reports.map((r: { month: string }) => r.month);
      if (months.includes(target)) break;
      await new Promise((r) => setTimeout(r, 1000));
    }
    expect(months, '백필한 월이 이력에 있어야 함').toContain(target);
  });

  test('volume_trend — 월 버킷이 로컬(KST) 기준·미래 월 없음', async ({ request }) => {
    const s = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/bi/operational?days=90&months=12`, {
      headers: authHeaders(s),
    });
    expect(res.ok()).toBeTruthy();
    const trend: { month: string }[] = (await res.json()).volume_trend;

    // KST 현재 월 — 버킷이 UTC로 계산되면 월초 9시간 동안 전월로 밀린다
    const kstNow = new Date(Date.now() + 9 * 3600 * 1000);
    const curMonth = `${kstNow.getUTCFullYear()}-${String(kstNow.getUTCMonth() + 1).padStart(2, '0')}`;
    for (const t of trend) {
      expect(t.month).toMatch(/^\d{4}-\d{2}$/);
      expect(t.month.localeCompare(curMonth), `미래 월 버킷: ${t.month}`).toBeLessThanOrEqual(0);
    }
  });

  test('RBAC — 무토큰 401, researcher(비 admin/rad) 403', async ({ request }) => {
    const noauth = await request.get(`${API}/bi/operational`);
    expect(noauth.status()).toBe(401);

    const researcher = await apiLogin(request, 'researcher');
    const denied = await request.get(`${API}/bi/operational`, { headers: authHeaders(researcher) });
    expect(denied.status()).toBe(403);
  });

  test('페이지 스모크 — /pacs-admin/bi 렌더', async ({ context, page, request }) => {
    const s = await apiLogin(request, 'admin');
    await injectSession(context, s);
    await page.goto(`${BASE}/pacs-admin/bi`);
    await expect(page.getByRole('heading', { name: /경영\/운영 BI 리포트/ })).toBeVisible();
    // 수신 KPI 섹션 라벨
    await expect(page.getByText('수신 검사', { exact: false }).first()).toBeVisible();
  });
});
