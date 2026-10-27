import { test, expect } from '@playwright/test';
import { apiLogin, injectSession } from '../helpers/session';

// viewer-ux (v13.17) — ① 모달리티 자동 MPR(werubAutoMPR) ② prior 원클릭 비교(hpCompare)
// 자동 HP는 mode hangingProtocol이 배열이라 매칭 엔진이 동작; 재구성 불가면 default 폴백.
test.describe('뷰어 UX — 자동 HP + 이전검사 비교', () => {
  async function openViewer(context, uid: string) {
    const page = await context.newPage();
    await page.goto(`/werub-viewer/viewer?StudyInstanceUIDs=${uid}`);
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 60_000 });
    const skipAll = page.getByRole('button', { name: /Skip all/i });
    if (await skipAll.isVisible().catch(() => false)) await skipAll.click();
    await page.waitForTimeout(6_000);
    return page;
  }

  test('재구성 가능 CT → 자동 MPR(3뷰) + 이전검사 버튼 노출', async ({ browser, request }) => {
    const session = await apiLogin(request, 'radiologist');
    // v13.19 P1: /dicom-web는 토큰 게이트 — QIDO에 Bearer 필수
    const auth = { Authorization: `Bearer ${session.access_token}` };
    // 08-vrt와 동일: 다중 슬라이스 CT/MR 선택
    const qido = await request.get(
      'https://his.example.org/dicom-web/studies?limit=50&includefield=00080061',
      { headers: auth },
    );
    let uid = '';
    for (const s of await qido.json()) {
      const mods: string[] = s['00080061']?.Value || [];
      if (!mods.some(m => m === 'CT' || m === 'MR')) continue;
      const sUid = s['0020000D'].Value[0];
      const series = await (
        await request.get(`https://his.example.org/dicom-web/studies/${sUid}/series`, {
          headers: auth,
        })
      ).json();
      const maxInstances = Math.max(
        ...series.map((x: any) => parseInt(x['00201209']?.Value?.[0] || '0', 10)),
      );
      if (maxInstances >= 20) { uid = sUid; break; }
    }
    test.skip(!uid, '운영에 볼륨 CT/MR 없음');

    const context = await browser.newContext();
    await injectSession(context, session);
    const page = await openViewer(context, uid);

    // 자동 MPR: 클릭 없이 3 뷰포트
    await expect(async () => {
      expect(await page.locator('canvas').count()).toBeGreaterThanOrEqual(3);
    }).toPass({ timeout: 30_000 });
    const hp = await page.evaluate(
      () => (window as any).services?.hangingProtocolService?.getActiveProtocol?.()?.protocol?.id,
    );
    expect(hp).toBe('werubAutoMPR');
    // 툴바 이전검사 버튼
    expect(await page.locator('[data-cy="werubPriorCompare"]').count()).toBe(1);
    await context.close();
  });

  test('이전검사 원클릭 비교 → hpCompare + 두 study 로드', async ({ browser, request }) => {
    const session = await apiLogin(request, 'radiologist');
    // 같은 환자 2+ study를 dicomweb에서 탐색 (v13.19 P1 토큰 게이트 — Bearer 필수)
    const studies = await (
      await request.get('https://his.example.org/dicom-web/studies?limit=100', {
        headers: { Authorization: `Bearer ${session.access_token}` },
      })
    ).json();
    const byPatient: Record<string, { uid: string; date: string }[]> = {};
    for (const s of studies) {
      const pid = s['00100020']?.Value?.[0];
      if (!pid) continue;
      (byPatient[pid] ||= []).push({
        uid: s['0020000D'].Value[0],
        date: s['00080020']?.Value?.[0] || '',
      });
    }
    const pair = Object.values(byPatient).find(list => list.length >= 2);
    test.skip(!pair, '2개 이상 study를 가진 환자 없음');
    const current = pair!.sort((a, b) => b.date.localeCompare(a.date))[0].uid;

    const context = await browser.newContext();
    await injectSession(context, session);
    const page = await openViewer(context, current);

    await page.locator('[data-cy="werubPriorCompare"]').click({ force: true });
    await page.waitForURL(/hangingprotocolid/i, { timeout: 20_000 });
    expect(page.url()).toContain(encodeURIComponent('@ohif/hpCompare'));
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 60_000 });
    await expect(async () => {
      expect(await page.locator('canvas').count()).toBeGreaterThanOrEqual(2);
      const hp = await page.evaluate(
        () => (window as any).services?.hangingProtocolService?.getActiveProtocol?.()?.protocol?.id,
      );
      expect(hp).toBe('@ohif/hpCompare');
    }).toPass({ timeout: 30_000 });
    await context.close();
  });

  // v13.24 SM 리다이렉트 + v13.26 this-binding 회귀 가드(운영에 SM 없으면 skip —
  // 합성 WSI로 돌리려면 scripts/server/it-pathology-ann.sh의 생성 블록 참조)
  test('SM study를 /viewer로 열면 /microscopy 리다이렉트 + ANN 버튼', async ({ browser, request }) => {
    const session = await apiLogin(request, 'radiologist');
    const qido = await request.get(
      'https://his.example.org/dicom-web/studies?limit=100&includefield=00080061',
      { headers: { Authorization: `Bearer ${session.access_token}` } },
    );
    let uid = '';
    for (const s of await qido.json()) {
      const mods: string[] = s['00080061']?.Value || [];
      if (mods.includes('SM')) { uid = s['0020000D'].Value[0]; break; }
    }
    test.skip(!uid, '운영에 SM study 없음');
    const context = await browser.newContext();
    await injectSession(context, session);
    const page = await context.newPage();
    await page.goto(`/werub-viewer/viewer?StudyInstanceUIDs=${uid}`);
    await page.waitForURL(/\/microscopy\?/, { timeout: 30_000 });
    await expect(page.locator('[data-cy="save-microscopy-ann"]')).toBeVisible({ timeout: 60_000 });
    await context.close();
  });
});
