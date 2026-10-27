import { test, expect } from '@playwright/test';
import { apiLogin, authHeaders, API } from '../helpers/session';

// teaching-file-library v2 — 익명화 사본 export.
// 게시(승인)된 케이스만, 전문의(ADMIN/RAD)만 익명화 DICOM ZIP 다운로드. anonymize.py 재사용(KeepSource=True 원본 불변).
// 주의: resident 미시드라 "RESIDENT export→403"은 코드(_assert_attending) 보장, E2E 미검증.
test.describe.serial('티칭파일 익명화 export', () => {
  let studyUid = '';
  let publishedId = '';
  let draftId = '';

  test.beforeAll(async ({ request }) => {
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/patients/P2026-0006/studies`, { headers: authHeaders(rad) });
    if (res.ok()) studyUid = (await res.json()).studies?.[0]?.study_instance_uid || '';
    if (studyUid) {
      const pub = await request.post(`${API}/teaching/cases`, {
        headers: authHeaders(rad),
        data: { study_instance_uid: studyUid, title: 'E2E export 게시본', difficulty: 'beginner', is_published: true },
      });
      if (pub.status() === 201) publishedId = (await pub.json()).id;
      const dr = await request.post(`${API}/teaching/cases`, {
        headers: authHeaders(rad),
        data: { study_instance_uid: studyUid, title: 'E2E export 초안', difficulty: 'beginner' },
      });
      if (dr.status() === 201) draftId = (await dr.json()).id;
    }
  });

  test('비인증 export → 401', async ({ request }) => {
    test.skip(!publishedId, 'no case');
    const res = await request.get(`${API}/teaching/cases/${publishedId}/export`);
    expect(res.status()).toBe(401);
  });

  test('researcher(미허용) export → 403', async ({ request }) => {
    test.skip(!publishedId, 'no case');
    const researcher = await apiLogin(request, 'researcher');
    const res = await request.get(`${API}/teaching/cases/${publishedId}/export`, { headers: authHeaders(researcher) });
    expect(res.status()).toBe(403);
  });

  test('초안 케이스 export → 409(게시본만)', async ({ request }) => {
    test.skip(!draftId, 'no draft');
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/teaching/cases/${draftId}/export`, { headers: authHeaders(rad) });
    expect(res.status()).toBe(409);
  });

  test('미존재 케이스 export → 404', async ({ request }) => {
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/teaching/cases/00000000-0000-0000-0000-000000000000/export`, { headers: authHeaders(rad) });
    expect(res.status()).toBe(404);
  });

  test('게시본 익명화 export → 200, ZIP 다운로드', async ({ request }) => {
    test.skip(!publishedId, 'no case');
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/teaching/cases/${publishedId}/export`, { headers: authHeaders(rad) });
    expect(res.ok()).toBeTruthy();
    expect(res.headers()['content-type']).toContain('application/zip');
    const buf = await res.body();
    expect(buf.length).toBeGreaterThan(0);
    expect(buf.slice(0, 2).toString('latin1')).toBe('PK'); // ZIP 매직바이트
  });

  test.afterAll(async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    if (publishedId) await request.delete(`${API}/teaching/cases/${publishedId}`, { headers: authHeaders(admin) });
    if (draftId) await request.delete(`${API}/teaching/cases/${draftId}`, { headers: authHeaders(admin) });
  });
});
