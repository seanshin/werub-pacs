import { test, expect } from '@playwright/test';
import { apiLogin, authHeaders, API } from '../helpers/session';

// teaching-file-library v2 — 게시 승인 워크플로.
// draft → submit → pending → approve→published / reject→rejected → (재submit). is_published는 published와 동기.
// RESIDENT는 draft 작성·submit만, 승인/반려는 전문의(ADMIN/RAD). 게시 취소는 ADMIN.
// 주의: 시드에 resident 계정이 없어 "RESIDENT가 approve 시도→403"은 E2E 미검증(코드 _assert_attending 보장).
test.describe.serial('티칭파일 게시 승인 워크플로', () => {
  let studyUid = '';
  let caseId = '';
  let caseB = '';

  test.beforeAll(async ({ request }) => {
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/patients/P2026-0006/studies`, { headers: authHeaders(rad) });
    if (res.ok()) studyUid = (await res.json()).studies?.[0]?.study_instance_uid || '';
  });

  test('생성 — is_published 미지정 → draft(미게시)', async ({ request }) => {
    test.skip(!studyUid, 'no study');
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.post(`${API}/teaching/cases`, {
      headers: authHeaders(rad),
      data: { study_instance_uid: studyUid, title: 'E2E 게시워크플로', diagnosis: '정답', difficulty: 'beginner', tags: ['pub-e2e'] },
    });
    expect(res.status()).toBe(201);
    const b = await res.json();
    caseId = b.id;
    expect(b.publish_status).toBe('draft');
    expect(b.is_published).toBe(false);
  });

  test('검토 대기 아님인데 승인 → 409', async ({ request }) => {
    test.skip(!caseId, 'no case');
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.post(`${API}/teaching/cases/${caseId}/approve`, { headers: authHeaders(rad) });
    expect(res.status()).toBe(409);
  });

  test('검토 요청 — draft → pending', async ({ request }) => {
    test.skip(!caseId, 'no case');
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.post(`${API}/teaching/cases/${caseId}/submit`, { headers: authHeaders(rad) });
    expect(res.ok()).toBeTruthy();
    const b = await res.json();
    expect(b.publish_status).toBe('pending');
    expect(b.submitted_at).toBeTruthy();
  });

  test('검토 대기 큐 + status 필터 — RBAC(researcher 403)', async ({ request }) => {
    test.skip(!caseId, 'no case');
    const researcher = await apiLogin(request, 'researcher');
    expect((await request.get(`${API}/teaching/review-queue`, { headers: authHeaders(researcher) })).status()).toBe(403);

    const rad = await apiLogin(request, 'radiologist');
    const q = await (await request.get(`${API}/teaching/review-queue`, { headers: authHeaders(rad) })).json();
    expect(q.some((c: any) => c.id === caseId)).toBeTruthy();
    const f = await (await request.get(`${API}/teaching/cases?status=pending`, { headers: authHeaders(rad) })).json();
    expect(f.items.some((c: any) => c.id === caseId)).toBeTruthy();
  });

  test('반려 — pending → rejected(+사유), is_published=false', async ({ request }) => {
    test.skip(!caseId, 'no case');
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.post(`${API}/teaching/cases/${caseId}/reject`, {
      headers: authHeaders(rad), data: { comment: 'E2E 반려 사유' },
    });
    expect(res.ok()).toBeTruthy();
    const b = await res.json();
    expect(b.publish_status).toBe('rejected');
    expect(b.is_published).toBe(false);
    expect(b.review_comment).toBe('E2E 반려 사유');
    expect(b.reviewed_by_name).toBeTruthy();
  });

  test('반려 후 재요청 — rejected → pending', async ({ request }) => {
    test.skip(!caseId, 'no case');
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.post(`${API}/teaching/cases/${caseId}/submit`, { headers: authHeaders(rad) });
    expect(res.ok()).toBeTruthy();
    expect((await res.json()).publish_status).toBe('pending');
  });

  test('승인 — pending → published, is_published=true', async ({ request }) => {
    test.skip(!caseId, 'no case');
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.post(`${API}/teaching/cases/${caseId}/approve`, { headers: authHeaders(rad) });
    expect(res.ok()).toBeTruthy();
    const b = await res.json();
    expect(b.publish_status).toBe('published');
    expect(b.is_published).toBe(true);
    expect(b.reviewed_by_name).toBeTruthy();
  });

  test('이미 게시본 재승인 → 409', async ({ request }) => {
    test.skip(!caseId, 'no case');
    const rad = await apiLogin(request, 'radiologist');
    expect((await request.post(`${API}/teaching/cases/${caseId}/approve`, { headers: authHeaders(rad) })).status()).toBe(409);
  });

  test('게시 취소 — RAD 403(AdminOnly), ADMIN 200 → draft', async ({ request }) => {
    test.skip(!caseId, 'no case');
    const rad = await apiLogin(request, 'radiologist');
    expect((await request.post(`${API}/teaching/cases/${caseId}/unpublish`, { headers: authHeaders(rad) })).status()).toBe(403);

    const admin = await apiLogin(request, 'admin');
    const ok = await request.post(`${API}/teaching/cases/${caseId}/unpublish`, { headers: authHeaders(admin) });
    expect(ok.ok()).toBeTruthy();
    const b = await ok.json();
    expect(b.publish_status).toBe('draft');
    expect(b.is_published).toBe(false);
  });

  test('초안 게시 취소 → 409', async ({ request }) => {
    test.skip(!caseId, 'no case');
    const admin = await apiLogin(request, 'admin');
    expect((await request.post(`${API}/teaching/cases/${caseId}/unpublish`, { headers: authHeaders(admin) })).status()).toBe(409);
  });

  test('RBAC — researcher는 submit 거부(403)', async ({ request }) => {
    test.skip(!caseId, 'no case');
    const researcher = await apiLogin(request, 'researcher');
    expect((await request.post(`${API}/teaching/cases/${caseId}/submit`, { headers: authHeaders(researcher) })).status()).toBe(403);
  });

  test('전문의 즉시 게시 — create is_published=true → published(self-approve)', async ({ request }) => {
    test.skip(!studyUid, 'no study');
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.post(`${API}/teaching/cases`, {
      headers: authHeaders(rad),
      data: { study_instance_uid: studyUid, title: 'E2E 즉시게시', difficulty: 'beginner', is_published: true },
    });
    expect(res.status()).toBe(201);
    const b = await res.json();
    caseB = b.id;
    expect(b.publish_status).toBe('published');
    expect(b.is_published).toBe(true);
    expect(b.reviewed_by_name).toBeTruthy();
  });

  test.afterAll(async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    if (caseId) await request.delete(`${API}/teaching/cases/${caseId}`, { headers: authHeaders(admin) });
    if (caseB) await request.delete(`${API}/teaching/cases/${caseB}`, { headers: authHeaders(admin) });
  });
});
