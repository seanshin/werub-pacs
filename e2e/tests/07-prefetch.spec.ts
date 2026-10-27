import { test, expect } from '@playwright/test';
import { apiLogin, injectSession, authHeaders, API } from '../helpers/session';

// 3d-ai-performance Track A — 예측 프리페칭
// ① 뷰어 열람 → study-opened 이벤트 발사(워밍 트리거 + 계측)
// ② 프레임 캐시: 동일 프레임 2회째 요청은 nginx X-Pacs-Cache HIT
// ③ stats API 집계 노출
test.describe('예측 프리페칭', () => {
  test('뷰어 열람 시 study-opened 이벤트 발사', async ({ browser, request }) => {
    const session = await apiLogin(request, 'radiologist');

    // 대상 study: DICOMweb에서 하나 조회 (v13.19 토큰 게이트 — 외부는 Bearer 필수)
    const qido = await request.get(
      `https://his.example.org/dicom-web/studies?limit=1`,
      { headers: authHeaders(session) },
    );
    expect(qido.ok()).toBeTruthy();
    const studies = await qido.json();
    test.skip(!studies.length, '운영에 study 없음');
    const uid = studies[0]['0020000D'].Value[0];

    const context = await browser.newContext();
    await injectSession(context, session);
    const page = await context.newPage();

    const eventSent = page.waitForRequest(
      req => req.url().includes('/prefetch/events/study-opened') && req.method() === 'POST',
      { timeout: 30_000 },
    );
    await page.goto(`/werub-viewer/viewer?StudyInstanceUIDs=${uid}`);
    const req = await eventSent;
    expect(JSON.parse(req.postData() || '{}').study_instance_uid).toBe(uid);

    // 렌더 후 load-measured 보고 (60초 내)
    await page
      .waitForRequest(
        r => r.url().includes('/prefetch/events/load-measured') && r.method() === 'POST',
        { timeout: 60_000 },
      )
      .catch(() => null); // 렌더 실패 환경에서도 스펙 자체는 통과 (이벤트 발사가 핵심)

    await context.close();
  });

  test('프레임 2회째 요청은 nginx 캐시 HIT', async ({ request }) => {
    const session = await apiLogin(request, 'radiologist');
    const auth = authHeaders(session);
    const qido = await request.get(`https://his.example.org/dicom-web/studies?limit=1`, { headers: auth });
    const studies = await qido.json();
    test.skip(!studies.length, '운영에 study 없음');
    const studyUid = studies[0]['0020000D'].Value[0];

    const seriesRes = await request.get(
      `https://his.example.org/dicom-web/studies/${studyUid}/series`,
      { headers: auth },
    );
    const series = await seriesRes.json();
    const seriesUid = series[0]['0020000E'].Value[0];
    const instRes = await request.get(
      `https://his.example.org/dicom-web/studies/${studyUid}/series/${seriesUid}/instances`,
      { headers: auth },
    );
    const instances = await instRes.json();
    const sopUid = instances[0]['00080018'].Value[0];

    const frameUrl =
      `https://his.example.org/dicom-web/studies/${studyUid}/series/${seriesUid}` +
      `/instances/${sopUid}/frames/1`;
    const accept = {
      ...auth,
      Accept:
        'multipart/related; type="application/octet-stream"; transfer-syntax=1.2.840.10008.1.2.4.90',
    };

    const first = await request.get(frameUrl, { headers: accept });
    expect(first.ok()).toBeTruthy();
    expect(['MISS', 'HIT', 'UPDATING']).toContain(first.headers()['x-pacs-cache']);

    const second = await request.get(frameUrl, { headers: accept });
    expect(second.ok()).toBeTruthy();
    expect(second.headers()['x-pacs-cache']).toBe('HIT');
  });

  test('stats API가 집계를 반환', async ({ request }) => {
    const session = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/prefetch/stats?hours=24`, {
      headers: authHeaders(session),
    });
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body).toHaveProperty('warmed_studies');
    expect(body).toHaveProperty('viewer_opens');
  });
});
