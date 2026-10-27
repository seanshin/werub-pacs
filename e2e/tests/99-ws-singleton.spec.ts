import { test, expect } from '@playwright/test';
import { apiLogin, injectSession } from '../helpers/session';

test('판독 페이지: 알림 WS 연결 수 = 1 (Bell+useRealtimeRefresh 공유)', async ({ browser, request }) => {
  const session = await apiLogin(request, 'radiologist');
  const context = await browser.newContext();
  await injectSession(context, session);
  const page = await context.newPage();
  const wsUrls: string[] = [];
  page.on('websocket', ws => wsUrls.push(ws.url()));
  await page.goto('/pacs-admin/reading');
  await expect(page.locator('table')).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(3000);
  const notif = wsUrls.filter(u => u.includes('/ws/notifications'));
  console.log('notifications WS connections:', notif.length, '| total WS:', wsUrls.length);
  expect(notif.length).toBe(1);
  // 클라이언트 네비게이션 확인: 네비 '배정' 클릭 시 풀 리로드 없이 전환
  await page.getByRole('link', { name: '배정', exact: true }).click();
  await expect(page.getByRole('heading', { name: '판독 배정' })).toBeVisible();
  expect(notif.length, '네비게이션 후에도 재연결 없음(Bell 유지)').toBe(wsUrls.filter(u => u.includes('/ws/notifications')).length);
  await context.close();
});
