import { test, expect } from '@playwright/test';
import { apiLogin, authHeaders, API } from '../helpers/session';

// teaching-file-library v2 — 퀴즈/언노운 모드 + 학습 진도.
// 정답을 가린 케이스 → 답안 제출 시 정답 공개 → 자가평가 → 모달리티/난이도별 진도 집계.
// 핵심 가드: 퀴즈 뷰는 diagnosis/title/summary를 노출하지 않는다(정답 유출 방지).
test.describe.serial('티칭파일 퀴즈/진도', () => {
  let studyUid = '';
  let caseId = '';
  let attemptId = '';
  const DIAGNOSIS = '교육용 정답 진단 v2';

  test.beforeAll(async ({ request }) => {
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/patients/P2026-0006/studies`, { headers: authHeaders(rad) });
    if (res.ok()) {
      const body = await res.json();
      studyUid = body.studies?.[0]?.study_instance_uid || '';
    }
    if (studyUid) {
      const created = await request.post(`${API}/teaching/cases`, {
        headers: authHeaders(rad),
        data: {
          study_instance_uid: studyUid,
          title: 'E2E 퀴즈 케이스(정답 노출 금지)',
          summary: '정답 요약 — 노출되면 안 됨',
          diagnosis: DIAGNOSIS,
          organ: '흉부',
          difficulty: 'beginner',
          tags: ['quiz-e2e'],
          is_published: true,
        },
      });
      if (created.status() === 201) caseId = (await created.json()).id;
    }
  });

  test('비인증 퀴즈 뷰 → 401', async ({ request }) => {
    test.skip(!caseId, 'no case');
    const res = await request.get(`${API}/teaching/cases/${caseId}/quiz`);
    expect(res.status()).toBe(401);
  });

  test('퀴즈 뷰 — 정답(diagnosis/title/summary/organ/tags) 미노출', async ({ request }) => {
    test.skip(!caseId, 'no case');
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/teaching/cases/${caseId}/quiz`, { headers: authHeaders(rad) });
    expect(res.ok()).toBeTruthy();
    const b = await res.json();
    // 영상 판독에 필요한 메타만 노출
    expect(b).toHaveProperty('modality');
    expect(b).toHaveProperty('study_instance_uid');
    expect(b).toHaveProperty('study_available');
    // 정답 유출 키는 존재하지 않아야 함
    expect(b.diagnosis).toBeUndefined();
    expect(b.title).toBeUndefined();
    expect(b.summary).toBeUndefined();
    expect(b.organ).toBeUndefined();
    expect(b.tags).toBeUndefined();
  });

  test('미존재 케이스 퀴즈 뷰 → 404', async ({ request }) => {
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.get(`${API}/teaching/cases/00000000-0000-0000-0000-000000000000/quiz`, { headers: authHeaders(rad) });
    expect(res.status()).toBe(404);
  });

  test('답안 제출 → attempt 생성 + 정답 공개', async ({ request }) => {
    test.skip(!caseId, 'no case');
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.post(`${API}/teaching/cases/${caseId}/quiz/submit`, {
      headers: authHeaders(rad),
      data: { answer: '나의 진단 소견', time_spent_ms: 4200 },
    });
    expect(res.ok()).toBeTruthy();
    const b = await res.json();
    attemptId = b.attempt_id;
    expect(attemptId).toBeTruthy();
    expect(b.submitted_answer).toBe('나의 진단 소견');
    // 제출 후에는 정답이 공개됨
    expect(b.diagnosis).toBe(DIAGNOSIS);
    expect(b.title).toBeTruthy();
    expect(Array.isArray(b.tags)).toBeTruthy();
  });

  test('빈 답안 제출 → 422', async ({ request }) => {
    test.skip(!caseId, 'no case');
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.post(`${API}/teaching/cases/${caseId}/quiz/submit`, {
      headers: authHeaders(rad), data: { answer: '' },
    });
    expect(res.status()).toBe(422);
  });

  test('자가평가 — 비소유자(admin)는 거부(403)', async ({ request }) => {
    test.skip(!attemptId, 'no attempt');
    const admin = await apiLogin(request, 'admin');
    const res = await request.put(`${API}/teaching/quiz/attempts/${attemptId}`, {
      headers: authHeaders(admin), data: { self_assessment: 'correct' },
    });
    expect(res.status()).toBe(403);
  });

  test('자가평가 — 잘못된 값 → 422', async ({ request }) => {
    test.skip(!attemptId, 'no attempt');
    const rad = await apiLogin(request, 'radiologist');
    const res = await request.put(`${API}/teaching/quiz/attempts/${attemptId}`, {
      headers: authHeaders(rad), data: { self_assessment: 'maybe' },
    });
    expect(res.status()).toBe(422);
  });

  test('자가평가 본인 → 200, 진도에 정답률 반영', async ({ request }) => {
    test.skip(!attemptId, 'no attempt');
    const rad = await apiLogin(request, 'radiologist');
    const assess = await request.put(`${API}/teaching/quiz/attempts/${attemptId}`, {
      headers: authHeaders(rad), data: { self_assessment: 'correct' },
    });
    expect(assess.ok()).toBeTruthy();
    expect((await assess.json()).self_assessment).toBe('correct');

    const prog = await (await request.get(`${API}/teaching/quiz/progress`, { headers: authHeaders(rad) })).json();
    expect(prog.total_attempts).toBeGreaterThanOrEqual(1);
    expect(prog.correct).toBeGreaterThanOrEqual(1);
    expect(prog.accuracy).not.toBeNull();
    expect(Array.isArray(prog.by_modality)).toBeTruthy();
    expect(Array.isArray(prog.by_difficulty)).toBeTruthy();
    // 방금 평가한 시도가 최근 목록 맨 위
    expect(prog.recent[0].self_assessment).toBe('correct');
  });

  test('학습자 진도 조회(/progress/{id}) — RBAC: researcher 403, admin 200', async ({ request }) => {
    const dummy = '00000000-0000-0000-0000-000000000000';
    const researcher = await apiLogin(request, 'researcher');
    const denied = await request.get(`${API}/teaching/quiz/progress/${dummy}`, { headers: authHeaders(researcher) });
    expect(denied.status()).toBe(403);

    const admin = await apiLogin(request, 'admin');
    const ok = await request.get(`${API}/teaching/quiz/progress/${dummy}`, { headers: authHeaders(admin) });
    expect(ok.ok()).toBeTruthy();
    expect(await ok.json()).toHaveProperty('total_attempts');
  });

  test('케이스별 퀴즈 통계 — RBAC: researcher 403, RAD 200', async ({ request }) => {
    test.skip(!caseId, 'no case');
    const researcher = await apiLogin(request, 'researcher');
    const denied = await request.get(`${API}/teaching/cases/${caseId}/quiz/stats`, { headers: authHeaders(researcher) });
    expect(denied.status()).toBe(403);

    const rad = await apiLogin(request, 'radiologist');
    const ok = await request.get(`${API}/teaching/cases/${caseId}/quiz/stats`, { headers: authHeaders(rad) });
    expect(ok.ok()).toBeTruthy();
    const b = await ok.json();
    expect(b.total_attempts).toBeGreaterThanOrEqual(1);
    expect(b.distinct_learners).toBeGreaterThanOrEqual(1);
    expect(b.correct).toBeGreaterThanOrEqual(1);
  });

  test.afterAll(async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    if (caseId) await request.delete(`${API}/teaching/cases/${caseId}`, { headers: authHeaders(admin) });
  });
});
