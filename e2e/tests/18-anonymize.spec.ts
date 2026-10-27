import { test, expect } from '@playwright/test';
import { apiLogin, authHeaders, API } from '../helpers/session';

// DICOM 익명화 회귀 가드.
// 2026-06-28 발견: anonymize 3개 엔드포인트가 모두 500이었음 — Orthanc /anonymize "Remove"에 사전外
// 키워드(MedicalRecordLocator)를 넘겨 "Unknown DICOM tag". 커스텀 Remove 제거→기본 Supp142 위임으로 수정.
// download 엔드포인트는 임시본 self-cleanup(원본 KeepSource=True 불변)이라 E2E가 잔여물을 남기지 않음.
test.describe.serial('DICOM 익명화', () => {
  let orthancId = '';

  test.beforeAll(async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const res = await request.get(`${API}/patients/P2026-0006/studies`, { headers: authHeaders(admin) });
    if (res.ok()) orthancId = (await res.json()).studies?.[0]?.orthanc_id || '';
  });

  test('비인증 → 401', async ({ request }) => {
    test.skip(!orthancId, 'no study');
    const res = await request.get(`${API}/anonymize/study/${orthancId}/download`);
    expect(res.status()).toBe(401);
  });

  test('RBAC — radiologist(미허용)는 403', async ({ request }) => {
    test.skip(!orthancId, 'no study');
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/anonymize/study/${orthancId}/download`, { headers: authHeaders(rad) });
    expect(res.status()).toBe(403);
  });

  test('익명화 다운로드 — ADMIN 200 + ZIP (회귀 가드: 이전 500)', async ({ request }) => {
    test.skip(!orthancId, 'no study');
    const admin = await apiLogin(request, 'admin');
    const res = await request.get(`${API}/anonymize/study/${orthancId}/download`, { headers: authHeaders(admin) });
    expect(res.ok()).toBeTruthy();
    expect(res.headers()['content-type']).toContain('application/zip');
    const buf = await res.body();
    expect(buf.length).toBeGreaterThan(0);
    expect(buf.slice(0, 2).toString('latin1')).toBe('PK');
  });
});
