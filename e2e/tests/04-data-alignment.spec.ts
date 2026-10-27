import { test, expect } from '@playwright/test';
import { apiLogin, injectSession } from '../helpers/session';

// 체크리스트 §4 — 데이터 정렬: 판독 큐에 실제 한글 환자명 표시
test.describe('데이터 정렬 시각 확인', () => {
  test('판독 큐에 실제 한글 환자명 표시 + P2026-0006 검색', async ({ browser, request }) => {
    const session = await apiLogin(request, 'radiologist');
    const context = await browser.newContext();
    await injectSession(context, session);
    const page = await context.newPage();

    await page.goto('/pacs-admin/reading');
    await expect(page.locator('table')).toBeVisible({ timeout: 30_000 });

    // v11.2 정렬 환자 중 한 명 이상이 한글명으로 표시 (샘플 PatientID 아님)
    // formatPatientName이 DICOM '^'를 공백으로 렌더 → '한 지영' 형태 허용
    await expect(page.getByText(/한\s?지영|임\s?하늘|김\s?영수/).first()).toBeVisible({ timeout: 30_000 });

    // P2026-0006(한지영) 검색 → 1건 이상 표시
    await page.getByPlaceholder(/환자명, 환자번호/).fill('P2026-0006');
    await expect(page.locator('tbody tr', { hasText: '지영' }).first()).toBeVisible({ timeout: 15_000 });

    await context.close();
  });
});
