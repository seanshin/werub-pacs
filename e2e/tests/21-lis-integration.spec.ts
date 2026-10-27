import { test, expect } from '@playwright/test';
import { API, BASE, apiLogin, authHeaders } from '../helpers/session';

// LIS 연계 (2026-07-13): ① P4 AccessionNumber 뷰어 런처 ② SERVICE 서비스계정 최소권한.
// R3 테스트 스터디 ACC-TEST-0001 존재 전제(가명 pilot 데이터). svc-lis RBAC은
// PACS_SVC_LIS_PW 있을 때만 — 비번은 repo에 두지 않음.
test.describe('LIS 연계 — 런처 + SERVICE 최소권한', () => {
  const ACC = 'ACC-TEST-0001';

  test('P4 런처: AccessionNumber → 302 뷰어 리다이렉트', async ({ request }) => {
    const res = await request.get(`${API}/viewer/launch?AccessionNumber=${ACC}`, {
      maxRedirects: 0,
    });
    test.skip(res.status() === 404, `${ACC} 테스트 스터디 부재(R3 데이터 없음)`);
    expect(res.status()).toBe(302);
    const loc = res.headers()['location'] || '';
    expect(loc).toContain('/werub-viewer/viewer?StudyInstanceUIDs='); // 비-SM → longitudinal
    expect(loc.startsWith(BASE)).toBeTruthy(); // open-redirect 아님(고정 origin)
  });

  test('P4 런처: SM(병리 WSI) → microscopy 모드 라우팅', async ({ request }) => {
    const res = await request.get(`${API}/viewer/launch?AccessionNumber=ACC-TEST-SM-01`, {
      maxRedirects: 0,
    });
    test.skip(res.status() === 404, 'ACC-TEST-SM-01(합성 WSI) 부재');
    expect(res.status()).toBe(302);
    // WSI는 /viewer(cornerstone)로는 렌더 안 됨 → microscopy 모드로 자동 라우팅
    expect(res.headers()['location'] || '').toContain('/werub-viewer/microscopy?StudyInstanceUIDs=');
  });

  test('P4 런처: 미매칭 accession → 404', async ({ request }) => {
    const res = await request.get(`${API}/viewer/launch?AccessionNumber=NOPE-DOES-NOT-EXIST`, {
      maxRedirects: 0,
    });
    expect(res.status()).toBe(404);
  });

  test('P4 런처: 파라미터 누락 → 400', async ({ request }) => {
    const res = await request.get(`${API}/viewer/launch`, { maxRedirects: 0 });
    expect(res.status()).toBe(400);
  });

  test('P1 게이트: 무인증 /dicom-web·/wado → 401 (PHI 노출 차단)', async ({ request }) => {
    const base = BASE;
    // 무토큰 edge → 401 (예전엔 200, PHI 열람 가능했음)
    expect((await request.get(`${base}/dicom-web/studies?limit=1`)).status()).toBe(401);
    expect(
      (await request.get(`${base}/wado?requestType=WADO&studyUID=x&seriesUID=y&objectUID=z`)).status(),
    ).toBe(401);
    // 잘못된 토큰 → 401
    expect(
      (await request.get(`${base}/dicom-web/studies?limit=1`, {
        headers: { Authorization: 'Bearer garbage.token.xx' },
      })).status(),
    ).toBe(401);
  });

  test('P1 게이트: 유효 토큰 → /dicom-web 200 (뷰어/LIS 정상)', async ({ request }) => {
    const s = await apiLogin(request, 'radiologist');
    expect(
      (await request.get(`${BASE}/dicom-web/studies?limit=1`, {
        headers: { Authorization: `Bearer ${s.access_token}` },
      })).status(),
    ).toBe(200);
  });

  test('M3: RESEARCHER는 QIDO PHI 열람 차단 (edge 401 · backend 403)', async ({ request }) => {
    const r = await apiLogin(request, 'researcher');
    const h = { Authorization: `Bearer ${r.access_token}` };
    expect((await request.get(`${BASE}/dicom-web/studies?limit=1`, { headers: h })).status()).toBe(401);
    expect((await request.get(`${API}/dicomweb/studies?limit=1`, { headers: h })).status()).toBe(403);
    expect((await request.get(`${API}/dicomweb/rs/studies?limit=1`, { headers: h })).status()).toBe(403);
  });

  test('SERVICE 최소권한: QIDO 200 · 게이트 EP 403', async ({ request }) => {
    const pw = process.env.PACS_SVC_LIS_PW;
    test.skip(!pw, 'PACS_SVC_LIS_PW 미설정 — svc-lis RBAC 검증 생략');

    const login = await request.post(`${API}/auth/login`, {
      data: { username: 'svc-lis', password: pw },
    });
    expect(login.ok(), `svc-lis 로그인 실패 (${login.status()})`).toBeTruthy();
    const token: string = (await login.json()).access_token;
    const h = { Authorization: `Bearer ${token}` };

    // QIDO 읽기 허용 (커스텀 {count,results})
    expect((await request.get(`${API}/dicomweb/studies?limit=1`, { headers: h })).status()).toBe(200);
    // QIDO-RS 표준(태그키 배열) passthrough — 인증 200, 무인증 401
    const rs = await request.get(`${API}/dicomweb/rs/studies?AccessionNumber=ACC-TEST-0001`, { headers: h });
    expect(rs.status()).toBe(200);
    const arr = await rs.json();
    if (Array.isArray(arr) && arr.length) {
      expect(arr[0]['0020000D']?.Value?.[0]).toBeTruthy();      // StudyInstanceUID 태그키
      expect(arr[0]['00080050']?.Value?.[0]).toBe('ACC-TEST-0001');
    }
    expect((await request.get(`${API}/dicomweb/rs/studies?AccessionNumber=ACC-TEST-0001`)).status()).toBe(401);
    // 게이트 엔드포인트는 deny-by-default로 차단
    expect((await request.get(`${API}/users`, { headers: h })).status()).toBe(403);
    expect((await request.get(`${API}/reports`, { headers: h })).status()).toBe(403);
    expect(
      (await request.post(`${API}/dicomweb/studies`, { headers: h, maxRedirects: 0 })).status(),
    ).toBe(403);
  });

  // 송신측 자기검증 EP(v13.40): LIS가 mwl_status='SENT'로 기록한 3건이 PACS에 도달한 적이
  // 없었고 아무도 몰랐다(2026-08-03). 송신 ACK는 최종 반영을 보장하지 않으므로 사후 확인
  // 수단이 필요하다. ★PHI를 반환하면 안 된다 — 워크리스트 전량 열거로 타 부서 오더의
  // 환자 정보가 새는 경로가 된다.
  test('worklist/verify — 도달 확인, PHI 미반환, RBAC', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const ha = authHeaders(admin);

    // 미도달은 404가 아니라 200 + exists=false (장애와 미도달을 구분할 수 있어야 한다)
    const missing = await request.get(
      `${API}/worklist/verify?accession_number=ACC-NOPE-${Date.now()}`, { headers: ha });
    expect(missing.status()).toBe(200);
    const mb = await missing.json();
    expect(mb.exists).toBe(false);
    expect(Object.keys(mb).sort()).toEqual(['accession_number', 'exists']); // 추가 정보 없음

    const acc = `ACC-E2E-VER-${Date.now()}`;
    const created = await request.post(`${API}/worklist`, {
      headers: ha,
      data: {
        patient_id: 'E2E-VERIFY-1', patient_name: '검증^대상', accession_number: acc,
        requested_procedure_id: 'P1', scheduled_station_ae_title: 'OPENPACS',
        modality: 'CR', scheduled_date: '2026-08-03',
      },
    });
    expect(created.status()).toBe(201);
    const id = (await created.json()).id as string;

    try {
      const res = await request.get(
        `${API}/worklist/verify?accession_number=${encodeURIComponent(acc)}`, { headers: ha });
      expect(res.status()).toBe(200);
      const body = await res.json();
      expect(body.exists).toBe(true);
      expect(body.status).toBe('SCHEDULED');   // enum NAME(대문자)로 노출
      expect(body.modality).toBe('CR');

      // ★PHI 미반환 — 환자명·PatientID가 어떤 키로도 새면 안 된다
      const dump = JSON.stringify(body);
      expect(dump).not.toContain('E2E-VERIFY-1');
      expect(dump).not.toContain('검증');
      expect(body).not.toHaveProperty('patient_id');
      expect(body).not.toHaveProperty('patient_name');
    } finally {
      await request.delete(`${API}/worklist/${id}`, { headers: ha });
    }

    // RBAC: 무토큰 401 / researcher 403 (LIS=SERVICE는 허용 역할에 포함)
    expect((await request.get(`${API}/worklist/verify?accession_number=X`)).status()).toBe(401);
    const researcher = await apiLogin(request, 'researcher');
    expect((await request.get(`${API}/worklist/verify?accession_number=X`, {
      headers: authHeaders(researcher),
    })).status()).toBe(403);
  });
});
