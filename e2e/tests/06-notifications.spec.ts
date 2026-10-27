import { test, expect } from '@playwright/test';
import { apiLogin, authHeaders, injectSession, API } from '../helpers/session';

// 알림 전체보기 페이지 (/pacs-admin/notifications) — 벨 드롭다운 → 전체 보기 진입 포함
test.describe('알림 전체보기', () => {
  test('벨 → 전체 알림 보기 → 목록/필터/읽음 처리', async ({ browser, request }) => {
    const session = await apiLogin(request, 'radiologist');
    const context = await browser.newContext();
    await injectSession(context, session);
    const page = await context.newPage();

    // 벨 드롭다운에서 진입
    await page.goto('/pacs-admin/reading');
    await page.getByRole('button', { name: '알림' }).click();
    await page.getByRole('link', { name: '전체 알림 보기' }).click();
    await expect(page).toHaveURL(/\/pacs-admin\/notifications/);
    await expect(page.getByRole('heading', { name: '알림' })).toBeVisible();
    await expect(page.getByText(/미읽음 [\d,]+건/)).toBeVisible();

    // 필터: 안 읽음 / 긴급도
    await page.getByRole('button', { name: '안 읽음', exact: true }).click();
    await expect(page.getByText(/건$/).last()).toBeVisible();
    await page.getByRole('button', { name: '전체 긴급도' }).click();

    // 읽음 처리: 미읽음 총계가 감소해야 함.
    // (보이는 '읽음' 버튼 수는 페이지당 20행 고정이라 미읽음이 20+면 줄지 않음 — 총계로 검증)
    const unreadTotal = async () => {
      const text = await page.getByText(/미읽음 [\d,]+건/).innerText();
      return parseInt(text.replace(/[^\d]/g, ''), 10);
    };
    const readBtns = page.getByRole('button', { name: '읽음', exact: true });
    if ((await readBtns.count()) > 0) {
      const before = await unreadTotal();
      await readBtns.first().click();
      await expect(async () => {
        expect(await unreadTotal()).toBeLessThan(before);
      }).toPass({ timeout: 10_000 });
    }

    await context.close();
  });

  // 운영 가시성 회귀(v13.36): AI 서버가 2주+ 다운인데 알림·health 어디에도 신호가
  // 없던 갭. health-detail의 ai_server 항목이 사라지면 같은 침묵이 재발한다.
  // (감시 로직 자체는 IT scripts/server/it-ai-health.sh가 결정적으로 검증)
  test('health-detail — ai_server 감시 항목 노출', async ({ request }) => {
    const s = await apiLogin(request, 'admin');
    const res = await request.get(`${API}/system/health-detail`, { headers: authHeaders(s) });
    expect(res.ok()).toBeTruthy();
    const body = await res.json();

    expect(body.services, 'health-detail에 services 없음').toBeTruthy();
    const ai = body.services.ai_server;
    expect(ai, 'ai_server 감시 항목이 사라짐').toBeTruthy();
    expect(['ok', 'down', 'degraded', 'stale', 'unknown', 'not_configured']).toContain(ai.status);

    // 이상 상태면 alerts에도 반드시 올라와야 한다(대시보드 침묵 방지)
    if (['down', 'degraded', 'stale'].includes(ai.status)) {
      const msgs = (body.alerts ?? []).map((a: { message: string }) => a.message).join(' ');
      expect(msgs, 'ai_server 이상인데 alerts에 없음').toContain('AI 서버');
    }
  });
});
