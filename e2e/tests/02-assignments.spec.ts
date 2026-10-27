import { test, expect } from '@playwright/test';
import { apiLogin, injectSession } from '../helpers/session';

// 체크리스트 §2 — 판독 배정 (Admin) /pacs-admin/assignments
test.describe('판독 배정', () => {
  test('근무 판독의 패널 + 자동 배정 + 상태 필터 + 완료/재배정', async ({ browser, request }) => {
    const session = await apiLogin(request, 'admin');
    const context = await browser.newContext();
    await injectSession(context, session);
    const page = await context.newPage();

    await page.goto('/pacs-admin/assignments');

    // 현재 근무 판독의 패널 + 온콜 배지 (온콜 유무 모두 허용)
    await expect(page.getByRole('heading', { name: '판독 배정' })).toBeVisible();
    await expect(page.getByText('현재 근무 판독의')).toBeVisible();
    await expect(page.getByText(/온콜 스케줄 적용|온콜 없음 → 활성 판독의 폴백/)).toBeVisible();

    // ⚙️ 미배정 자동 배정 (멱등 — 신규 0건도 정상)
    await page.getByRole('button', { name: /미배정 자동 배정/ }).click();
    await expect(page.getByText(/자동 배정 완료 — 신규 \d+건 \/ 근무 판독의 \d+명/)).toBeVisible({ timeout: 30_000 });

    // 상태 필터 동작 (전체/대기/판독중/완료) — 각 클릭 후 목록 영역 렌더 유지
    for (const label of ['대기', '판독중', '완료', '전체']) {
      await page.locator('div.flex.bg-slate-100 button', { hasText: label }).first().click();
      await expect(page.locator('table')).toBeVisible();
      await page.waitForLoadState('networkidle');
    }

    // 완료 버튼: 미완료 행 하나를 완료 처리 → 행이 '완료' 배지로 변경
    const firstDone = page.locator('tbody tr').filter({ has: page.getByRole('button', { name: '완료', exact: true }) }).first();
    if (await firstDone.count()) {
      const patient = await firstDone.locator('td').first().innerText();
      await firstDone.getByRole('button', { name: '완료', exact: true }).click();
      await page.waitForLoadState('networkidle');
      // "현재 배정만" 해제 후에도 조회되는지 (완료 행 포함 확인)
      const currentOnly = page.getByLabel('현재 배정만').or(page.locator('label:has-text("현재 배정만") input'));
      await currentOnly.first().uncheck();
      await page.locator('div.flex.bg-slate-100 button', { hasText: '완료' }).first().click();
      await page.waitForLoadState('networkidle');
      await expect(page.locator('tbody tr', { hasText: patient.split('\n')[0] }).first()).toBeVisible();
    } else {
      test.info().annotations.push({ type: 'note', description: '미완료 배정 없음 — 완료 버튼 검증 생략' });
    }

    // 재배정 드롭다운: 첫 행에서 판독의 선택 → 배정 판독의 갱신
    await page.locator('div.flex.bg-slate-100 button', { hasText: '전체' }).first().click();
    await page.waitForLoadState('networkidle');
    const row = page.locator('tbody tr').filter({ has: page.locator('select') }).first();
    if (await row.count()) {
      const select = row.locator('select');
      const options = select.locator('option:not([value=""])');
      if (await options.count()) {
        const name = (await options.first().innerText()).trim();
        await select.selectOption({ index: 1 });
        await page.waitForLoadState('networkidle');
        await expect(page.locator('tbody tr', { hasText: name }).first()).toBeVisible();
      }
    }

    await context.close();
  });
});
