import { test, expect } from '@playwright/test';
import { apiLogin, injectSession, authHeaders, API } from '../helpers/session';

// vrt-rendering Phase 1 — 클라이언트 3D 볼륨 렌더링
// ① 레이아웃 셀렉터에 3D 프리셋(Advanced) 노출 + 3D 전환 시 캔버스 렌더
// ② 3D 전환 텔레메트리 발사 (vrt/events/protocol)
// ③ capability API 조회 가능 (뷰어 UI 분기용)
test.describe('3D 볼륨 렌더링 (VRT)', () => {
  test('CT 열람 → 레이아웃 3D 전환 → 렌더 + 텔레메트리', async ({ browser, request }) => {
    const session = await apiLogin(request, 'radiologist');

    // 볼륨 재구성이 가능한 CT/MR 선택 — 3D HP selector는 다중 슬라이스 시리즈를 요구하므로
    // 최대 시리즈 인스턴스 수 ≥ 20인 study를 고른다 (1장짜리 CT는 프리셋이 비활성됨)
    const qido = await request.get(
      'https://his.example.org/dicom-web/studies?limit=50&includefield=00080061',
      { headers: authHeaders(session) },
    );
    const studies = await qido.json();
    let uid = '';
    for (const s of studies) {
      const mods: string[] = s['00080061']?.Value || [];
      if (!mods.some(m => m === 'CT' || m === 'MR')) continue;
      const sUid = s['0020000D'].Value[0];
      const seriesRes = await request.get(`https://his.example.org/dicom-web/studies/${sUid}/series`,
        { headers: authHeaders(session) });
      const series = await seriesRes.json();
      const maxInstances = Math.max(
        ...series.map((x: any) => parseInt(x['00201209']?.Value?.[0] || '0', 10)),
      );
      if (maxInstances >= 20) {
        uid = sUid;
        break;
      }
    }
    test.skip(!uid, '운영에 볼륨(다중 슬라이스) CT/MR 없음');

    const context = await browser.newContext();
    await injectSession(context, session);
    const page = await context.newPage();

    await page.goto(`/werub-viewer/viewer?StudyInstanceUIDs=${uid}`);
    // 뷰어 렌더 대기 후 온보딩 다이얼로그 정리 (03-viewer-ai와 동일 패턴)
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 60_000 });
    const skipAll = page.getByRole('button', { name: /Skip all/i });
    if (await skipAll.isVisible().catch(() => false)) await skipAll.click();

    // 레이아웃 셀렉터 열기 → Advanced 프리셋에 3D 항목 존재
    const layoutBtn = page.locator('[data-cy="Layout"]').first();
    if (await layoutBtn.isVisible().catch(() => false)) {
      await layoutBtn.click();
    } else {
      await page.getByRole('button', { name: /layout/i }).first().click();
    }
    // C2 임상 튜닝: Advanced 목록은 werub-ai advancedPresetGenerator가 한글로 제공
    const preset3d = page.getByText('3D 메인', { exact: true });
    await expect(preset3d).toBeVisible({ timeout: 10_000 });

    // 3D 전환 → 텔레메트리 요청 발사 확인
    const telemetry = page.waitForRequest(
      req => req.url().includes('/vrt/events/protocol') && req.method() === 'POST',
      { timeout: 30_000 },
    );
    await preset3d.click();
    const req = await telemetry;
    expect(JSON.parse(req.postData() || '{}').protocol_id).toBe('main3D');

    // 참고용 3D 안내 토스트 — 3D HP는 hideOverlays:true라 뷰포트 배지 불가 → 토스트로 안내 (v13.14)
    await expect(page.getByText('참고용 3D 렌더링').first()).toBeVisible({ timeout: 10_000 });

    // 3D 뷰포트 렌더(캔버스 존재) — 볼륨 로딩까지 대기
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 60_000 });

    await context.close();
  });

  test('capability API — 뷰어 분기용 조회', async ({ request }) => {
    const session = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/vrt/capability`, { headers: authHeaders(session) });
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(['tested', 'not_tested']).toContain(body.status);
    expect(typeof body.batch_supported).toBe('boolean');
  });

  test('3D 사용 통계 조회', async ({ request }) => {
    const session = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/vrt/metrics/summary`, { headers: authHeaders(session) });
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body).toHaveProperty('by_protocol');
    expect(body).toHaveProperty('by_preset');
  });

  test('VR 프리셋 텔레메트리 — 이벤트 기록 → by_preset 집계 (C2)', async ({ request }) => {
    const session = await apiLogin(request, 'radiologist');
    const presetName = 'CT-Bone';
    const post = await request.post(`${API}/vrt/events/preset`, {
      headers: authHeaders(session),
      data: {
        study_instance_uid: `1.2.3.e2e.vrt.preset.${Date.now()}`,
        preset_name: presetName,
      },
    });
    expect(post.status()).toBe(202);

    const res = await request.get(`${API}/vrt/metrics/summary`, { headers: authHeaders(session) });
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    const row = (body.by_preset || []).find((r: any) => r.preset_name === presetName);
    expect(row?.uses).toBeGreaterThanOrEqual(1);
    // preset 이벤트가 by_protocol 집계를 오염시키지 않아야 한다
    expect((body.by_protocol || []).some((r: any) => r.protocol_id === 'preset')).toBeFalsy();
  });
});
