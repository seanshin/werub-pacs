import { test, expect } from '@playwright/test';
import { apiLogin, authHeaders, API } from '../helpers/session';

// patient-view — 환자 결과 열람 포털 (staff 발급 토큰 → 환자 본인 열람)
// 게이트: PATIENT_VIEW_ENABLED (운영 활성). RBAC: 발급=ADMIN 전용.
// IDOR: 토큰에 봉인된 patient_id 스코프 밖 study는 404.
test.describe('환자 결과 열람 포털', () => {
  const PATIENT = 'P2026-0005'; // final 리포트 보유 (Abdomen CT)
  const OTHER_STUDY = '1.2.276.0.7230010.3.1.2.1698116196.1.1780980106.243277'; // P2026-0022 소유

  async function issueToken(request: any): Promise<string> {
    const admin = await apiLogin(request, 'admin');
    const res = await request.post(`${API}/patient-view/token`, {
      headers: authHeaders(admin),
      data: { patient_id: PATIENT, memo: 'e2e', expires_hours: 24 },
    });
    expect(res.ok(), `token issue failed (${res.status()})`).toBeTruthy();
    const body = await res.json();
    expect(body.token).toBeTruthy();
    return body.token as string;
  }

  test('발급(ADMIN) → 포털 검사 목록 + final 리포트 열람', async ({ request }) => {
    const token = await issueToken(request);

    const studies = await request.get(
      `${API}/patient-view/portal/studies?token=${encodeURIComponent(token)}`);
    expect(studies.ok()).toBeTruthy();
    const list = await studies.json();
    expect(list.patient_id).toBe(PATIENT);
    expect(list.studies.length).toBeGreaterThan(0);

    const withFinal = list.studies.find((s: any) => s.has_final_report);
    expect(withFinal, 'final 리포트 보유 study가 목록에 있어야 함').toBeTruthy();

    const report = await request.get(
      `${API}/patient-view/portal/report?token=${encodeURIComponent(token)}&study_uid=${withFinal.study_instance_uid}`);
    expect(report.ok()).toBeTruthy();
    const r = await report.json();
    expect(['final', 'addendum']).toContain(r.status);
    expect(r.impression || r.findings).toBeTruthy();
  });

  test('IDOR 가드 — 타 환자 study는 404', async ({ request }) => {
    const token = await issueToken(request);
    const res = await request.get(
      `${API}/patient-view/portal/report?token=${encodeURIComponent(token)}&study_uid=${OTHER_STUDY}`);
    expect(res.status()).toBe(404);
    const prev = await request.get(
      `${API}/patient-view/portal/preview?token=${encodeURIComponent(token)}&study_uid=${OTHER_STUDY}`);
    expect(prev.status()).toBe(404);
  });

  test('무효/폐기 토큰 → 401', async ({ request }) => {
    const bad = await request.get(`${API}/patient-view/portal/studies?token=INVALID`);
    expect(bad.status()).toBe(401);

    // 발급 → 폐기 → 401
    const admin = await apiLogin(request, 'admin');
    const issued = await request.post(`${API}/patient-view/token`, {
      headers: authHeaders(admin),
      data: { patient_id: PATIENT, memo: 'e2e-revoke', expires_hours: 1 },
    });
    const { token } = await issued.json();
    const listRes = await request.get(`${API}/patient-view/tokens`, { headers: authHeaders(admin) });
    const tokens = (await listRes.json()).tokens as any[];
    const mine = tokens.find(t => t.memo === 'e2e-revoke' && !t.revoked);
    expect(mine).toBeTruthy();
    const rev = await request.post(`${API}/patient-view/tokens/${mine.id}/revoke`, {
      headers: authHeaders(admin) });
    expect(rev.ok()).toBeTruthy();
    const after = await request.get(
      `${API}/patient-view/portal/studies?token=${encodeURIComponent(token)}`);
    expect(after.status()).toBe(401);
  });

  test('발급 RBAC — radiologist/researcher 403', async ({ request }) => {
    for (const role of ['radiologist', 'researcher'] as const) {
      const s = await apiLogin(request, role);
      const res = await request.post(`${API}/patient-view/token`, {
        headers: authHeaders(s),
        data: { patient_id: PATIENT, expires_hours: 1 },
      });
      expect(res.status(), `${role}는 발급 불가여야 함`).toBe(403);
    }
  });

  test('포털 페이지 렌더 — 검사 목록 표시', async ({ browser, request }) => {
    const token = await issueToken(request);
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto(`/pacs-admin/patient-view?token=${encodeURIComponent(token)}`);
    await expect(page.getByText('검사 결과 열람')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/님의 검사 결과|검사 결과$/).first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('button', { name: '결과 보기' }).first()).toBeVisible();
    // 결과 상세 진입
    await page.getByRole('button', { name: '결과 보기' }).first().click();
    await expect(page.getByText('판독 결론')).toBeVisible({ timeout: 10_000 });
    await context.close();
  });
});
