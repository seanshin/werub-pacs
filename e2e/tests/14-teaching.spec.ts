import { test, expect } from '@playwright/test';
import { apiLogin, authHeaders, API } from '../helpers/session';

// teaching-file-library — 판독 교육용 티칭파일 라이브러리 API 표면 + RBAC.
// 라이브 study 참조 + RBAC(조회 ADMIN/RAD/RESIDENT, 쓰기 ADMIN/RAD, 삭제 ADMIN).
test.describe.serial('티칭파일 라이브러리', () => {
  let studyUid = '';
  let caseId = '';
  let collectionId = '';

  test.beforeAll(async ({ request }) => {
    // 실 study UID 확보(05-phi-access·03-viewer-ai와 동일 환자)
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/patients/P2026-0006/studies`, { headers: authHeaders(rad) });
    if (res.ok()) {
      const body = await res.json();
      studyUid = body.studies?.[0]?.study_instance_uid || '';
    }
  });

  test('비인증 → 401', async ({ request }) => {
    const res = await request.get(`${API}/teaching/cases`);
    expect(res.status()).toBe(401);
  });

  test('researcher(미허용 역할) 조회 → 403', async ({ request }) => {
    const r = await apiLogin(request, 'researcher');
    const res = await request.get(`${API}/teaching/cases`, { headers: authHeaders(r) });
    expect(res.status()).toBe(403);
  });

  test('RADIOLOGIST 케이스 등록 → modality 자동 캡처', async ({ request }) => {
    test.skip(!studyUid, 'no study UID available');
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.post(`${API}/teaching/cases`, {
      headers: authHeaders(rad),
      data: {
        study_instance_uid: studyUid,
        title: 'E2E 티칭 케이스',
        diagnosis: '교육용 정답 진단',
        organ: '흉부',
        difficulty: 'beginner',
        tags: ['e2e', 'Chest', 'e2e'], // 중복/대문자 정규화 확인
        is_published: true,
      },
    });
    expect(res.status()).toBe(201);
    const b = await res.json();
    caseId = b.id;
    expect(b).toHaveProperty('modality'); // Orthanc에서 캡처(없을 수도 있으나 키는 존재)
    expect(b.study_available).toBe(true);
    expect(b.tags.sort()).toEqual(['chest', 'e2e']); // 정규화(소문자·dedup)
    expect(b.difficulty).toBe('beginner');
  });

  test('등록할 study 미존재 → 400', async ({ request }) => {
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.post(`${API}/teaching/cases`, {
      headers: authHeaders(rad),
      data: { study_instance_uid: '1.2.3.nonexistent.999', title: 'dangling' },
    });
    expect(res.status()).toBe(400);
  });

  test('검색 — modality·difficulty·tag 필터', async ({ request }) => {
    test.skip(!caseId, 'no case created');
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/teaching/cases?difficulty=beginner&tag=e2e`, { headers: authHeaders(rad) });
    expect(res.ok()).toBeTruthy();
    const b = await res.json();
    expect(b).toHaveProperty('total');
    expect(b.items.some((i: any) => i.id === caseId)).toBeTruthy();
  });

  test('상세 — view_count 원자 증가', async ({ request }) => {
    test.skip(!caseId, 'no case created');
    const rad = await apiLogin(request, 'radiologist');
    const r1 = await (await request.get(`${API}/teaching/cases/${caseId}`, { headers: authHeaders(rad) })).json();
    const r2 = await (await request.get(`${API}/teaching/cases/${caseId}`, { headers: authHeaders(rad) })).json();
    expect(r2.view_count).toBeGreaterThan(r1.view_count);
    expect(r1).toHaveProperty('study_available');
  });

  test('태그 클라우드 — 빈도 배열', async ({ request }) => {
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/teaching/tags`, { headers: authHeaders(rad) });
    expect(res.ok()).toBeTruthy();
    expect(Array.isArray(await res.json())).toBeTruthy();
  });

  test('페이지네이션 — page_size 클램프(>100→100), 범위초과 page 빈 목록', async ({ request }) => {
    const rad = await apiLogin(request, 'radiologist');
    const clamp = await (await request.get(`${API}/teaching/cases?page_size=500`, { headers: authHeaders(rad) })).json();
    expect(clamp.page_size).toBe(100);
    const oob = await (await request.get(`${API}/teaching/cases?page=9999`, { headers: authHeaders(rad) })).json();
    expect(oob.items).toEqual([]);
    expect(oob).toHaveProperty('total');
  });

  test('컬렉션 — 생성→항목 추가→reorder→상세 순서', async ({ request }) => {
    test.skip(!caseId, 'no case created');
    const rad = await apiLogin(request, 'radiologist');
    const created = await request.post(`${API}/teaching/collections`, {
      headers: authHeaders(rad), data: { title: 'E2E 컬렉션' },
    });
    expect(created.status()).toBe(201);
    collectionId = (await created.json()).id;

    const add = await request.post(`${API}/teaching/collections/${collectionId}/items`, {
      headers: authHeaders(rad), data: { case_id: caseId },
    });
    expect(add.ok()).toBeTruthy();

    const reorder = await request.put(`${API}/teaching/collections/${collectionId}/reorder`, {
      headers: authHeaders(rad), data: { case_ids: [caseId] },
    });
    expect(reorder.ok()).toBeTruthy();

    const detail = await (await request.get(`${API}/teaching/collections/${collectionId}`, { headers: authHeaders(rad) })).json();
    expect(detail.items[0].id).toBe(caseId);
  });

  test('컬렉션에 미존재 case 추가 → 404', async ({ request }) => {
    test.skip(!collectionId, 'no collection');
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.post(`${API}/teaching/collections/${collectionId}/items`, {
      headers: authHeaders(rad),
      data: { case_id: '00000000-0000-0000-0000-000000000000' },
    });
    expect(res.status()).toBe(404);
  });

  test('미존재 case 조회 → 404', async ({ request }) => {
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/teaching/cases/00000000-0000-0000-0000-000000000000`, { headers: authHeaders(rad) });
    expect(res.status()).toBe(404);
  });

  test('삭제 — RAD가 Break-the-Glass 헤더로도 거부(allow_btg=False)', async ({ request }) => {
    test.skip(!caseId, 'no case created');
    const rad = await apiLogin(request, 'radiologist');
    // BTG 우회 시도 — 민감 삭제는 allow_btg=False라 헤더가 있어도 차단되어야 함.
    const res = await request.delete(`${API}/teaching/cases/${caseId}`, {
      headers: { ...authHeaders(rad), 'X-Break-The-Glass': 'true', 'X-Break-The-Glass-Reason': 'e2e' },
    });
    expect(res.status()).toBe(403);
  });

  test('삭제 RBAC — RADIOLOGIST 403(AdminOnly), ADMIN 200', async ({ request }) => {
    test.skip(!caseId, 'no case created');
    const rad = await apiLogin(request, 'radiologist');
    const denied = await request.delete(`${API}/teaching/cases/${caseId}`, { headers: authHeaders(rad) });
    expect(denied.status()).toBe(403);

    const admin = await apiLogin(request, 'admin');
    const ok = await request.delete(`${API}/teaching/cases/${caseId}`, { headers: authHeaders(admin) });
    expect(ok.ok()).toBeTruthy();
    caseId = '';
  });

  test.afterAll(async ({ request }) => {
    // 정리 — 생성된 컬렉션/케이스 삭제(admin)
    const admin = await apiLogin(request, 'admin');
    if (collectionId) await request.delete(`${API}/teaching/collections/${collectionId}`, { headers: authHeaders(admin) });
    if (caseId) await request.delete(`${API}/teaching/cases/${caseId}`, { headers: authHeaders(admin) });
  });
});
