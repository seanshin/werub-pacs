import { test, expect } from '@playwright/test';
import { apiLogin, API, authHeaders } from '../helpers/session';

// 체크리스트 §5 — PHI 접근제어 음성 케이스 (연구자 403)
test.describe('PHI 접근제어', () => {
  test('researcher → /patients/{mrn}/studies = 403, radiologist = 200', async ({ request }) => {
    const researcher = await apiLogin(request, 'researcher');
    const denied = await request.get(`${API}/patients/P2026-0006/studies`, { headers: authHeaders(researcher) });
    expect(denied.status(), '연구자는 임상역할이 아니므로 403이어야 함').toBe(403);

    // 양성 대조: 임상역할(radiologist)은 200 + 매핑 해석
    const radiologist = await apiLogin(request, 'radiologist');
    const allowed = await request.get(`${API}/patients/P2026-0006/studies`, { headers: authHeaders(radiologist) });
    expect(allowed.status()).toBe(200);
    const body = await allowed.json();
    expect(body.total_studies).toBeGreaterThanOrEqual(1);
  });
});
