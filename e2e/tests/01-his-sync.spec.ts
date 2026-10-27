import { test, expect } from '@playwright/test';
import { apiLogin, injectSession } from '../helpers/session';

// 체크리스트 §1 — HIS 동기화 (Admin)
test.describe('HIS 동기화', () => {
  test('admin: 동기화 패널 표시 + 오더 동기화 + 병합 재조정', async ({ browser, request }) => {
    const session = await apiLogin(request, 'admin');
    const context = await browser.newContext();
    await injectSession(context, session);
    const page = await context.newPage();

    await page.goto('/pacs-admin/his');
    await expect(page.getByText('HospitalRun 동기화')).toBeVisible();

    // 오더 동기화 (멱등 — 재실행 시 신규 0건도 정상)
    await page.getByRole('button', { name: /오더 동기화/ }).click();
    await expect(page.getByText(/오더 동기화 완료 — 조회 \d+건 \/ 워크리스트 신규 \d+건 \/ 매핑 \d+건/)).toBeVisible({ timeout: 30_000 });

    // 환자 병합 재조정
    await page.getByRole('button', { name: /환자 병합 재조정/ }).click();
    await expect(page.getByText(/병합 재조정 완료 — 병합 \d+건 \/ 영상 재태깅 \d+건/)).toBeVisible({ timeout: 30_000 });

    await context.close();
  });

  test('radiologist(비-admin): 동기화 패널 미표시', async ({ browser, request }) => {
    const session = await apiLogin(request, 'radiologist');
    const context = await browser.newContext();
    await injectSession(context, session);
    const page = await context.newPage();

    await page.goto('/pacs-admin/his');
    // 페이지 본문은 접근 가능(radiologist 허용)하되 admin 전용 패널은 없어야 함
    await page.waitForLoadState('networkidle');
    await expect(page.getByText('HospitalRun 동기화')).toHaveCount(0);
    await expect(page.getByRole('button', { name: /오더 동기화/ })).toHaveCount(0);

    await context.close();
  });
});
