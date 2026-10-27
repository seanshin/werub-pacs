import { test, expect } from '@playwright/test';
import { apiLogin, injectSession, API, authHeaders } from '../helpers/session';

// 체크리스트 §3 — 뷰어 AI 모델 선택 (/werub-viewer/) + §4 뷰어 렌더
test.describe('뷰어 AI 모델 선택', () => {
  test('AI 패널 모델 드롭다운 + 분석 실행 + 뷰어 렌더', async ({ browser, request }) => {
    test.setTimeout(360_000); // GPU 추론 대기 포함

    const session = await apiLogin(request, 'radiologist');

    // 검증된 정렬 환자(한지영 P2026-0006)의 study UID 확보
    const res = await request.get(`${API}/patients/P2026-0006/studies`, { headers: authHeaders(session) });
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body.patient_name).toContain('지영'); // 데이터 정렬 (체크리스트 §4)
    const uid = body.studies[0].study_instance_uid as string;

    const context = await browser.newContext();
    await injectSession(context, session);
    const page = await context.newPage();

    await page.goto(`/werub-viewer/viewer?StudyInstanceUIDs=${uid}`);

    // 뷰어 렌더 정상 (cornerstone canvas) — 체크리스트 §4
    // 풀스위트 실행 중 운영 부하로 첫 로드가 60s를 넘는 플레이크 관측 → 120s
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 120_000 });

    // 온보딩/단축키 안내 다이얼로그가 떠 있으면 닫기
    const skipAll = page.getByRole('button', { name: /Skip all/i });
    if (await skipAll.isVisible().catch(() => false)) await skipAll.click();

    // AI 패널 열기: OHIF SidePanel 탭은 data-cy="{panel.name}-btn" (werub-ai → aiPanel)
    const modelSelect = page.locator('select', { has: page.locator('option', { hasText: '기본 (MedGemma)' }) });
    if (!(await modelSelect.isVisible().catch(() => false))) {
      const aiTab = page.locator('[data-cy="aiPanel-btn"]').first();
      await aiTab.click();
    }
    await expect(modelSelect).toBeVisible({ timeout: 30_000 });

    // 모델 목록: 기본 + 28종 (회귀 허용폭: 20+ )
    const optionCount = await modelSelect.locator('option').count();
    expect(optionCount, `모델 옵션 수 = ${optionCount}`).toBeGreaterThanOrEqual(20);

    // ── 여기까지(뷰어 렌더·모델 드롭다운)는 AI 서버와 무관하게 항상 검증한다.
    // 아래 추론 호출만 AI 서버에 의존 — 서버가 죽어 있으면 이 스펙이 상시 red가 되어
    // 위 회귀가드까지 묻힌다(v13.26 교훈). 감시(v13.36)가 보는 상태로 명시 skip.
    const adminSession = await apiLogin(request, 'admin');
    const healthRes = await request.get(`${API}/system/health-detail`, {
      headers: authHeaders(adminSession),
    });
    const aiStatus = healthRes.ok()
      ? (await healthRes.json()).services?.ai_server?.status
      : 'unknown';
    test.skip(
      ['down', 'degraded', 'stale'].includes(aiStatus),
      `AI 서버 ${aiStatus} — 추론 호출 검증 불가(뷰어 렌더·모델 목록은 위에서 검증됨)`,
    );

    // 모델 선택 후 AI 영상 분석 → analyze-and-draft 요청이 선택 모델로 나가는지 + 200 응답
    await modelSelect.selectOption({ index: 1 });
    const selectedModel = await modelSelect.inputValue();

    const [analyzeRes] = await Promise.all([
      page.waitForResponse(
        r => r.url().includes('/ai/analyze-and-draft') && r.request().method() === 'POST',
        { timeout: 300_000 },
      ),
      page.getByText('AI 영상 분석', { exact: true }).first().click(),
    ]);
    const reqBody = analyzeRes.request().postDataJSON() as any;
    expect(reqBody.model_name).toBe(selectedModel);
    expect(analyzeRes.status(), `분석 응답 ${analyzeRes.status()}`).toBe(200);

    await context.close();
  });
});
