import { test, expect } from '@playwright/test';
import { apiLogin, authHeaders, API } from '../helpers/session';

// 2026-06-29 전체 감사에서 발견·수정한 "조용히 500이던" 엔드포인트 회귀 가드.
// 근본 원인: 이 기능들에 E2E가 없어 운영 비동작이 장기 미발견(anonymize와 동일 교훈).
// - audit_logs 컬럼명 오류(user_name→username): anonymize/history, system-health audit stats
// - text() SQL의 :param::date 캐스트 오파싱 + str→timestamptz: reports/peer-review statistics, followups
// - ORM str→DateTime: archive 날짜 필터
// + export.py RBAC(비익명 PHI 반출이 누구나 가능하던 것).
test.describe('전체 감사 회귀 가드', () => {
  test('anonymize/history — ADMIN 200 (이전 user_name 컬럼 500)', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const res = await request.get(`${API}/anonymize/history`, { headers: authHeaders(admin) });
    expect(res.ok()).toBeTruthy();
  });

  test('reports/statistics — ADMIN 200 (이전 date 캐스트 500)', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const res = await request.get(`${API}/reports/statistics`, { headers: authHeaders(admin) });
    expect(res.ok()).toBeTruthy();
  });

  test('peer-review/statistics — ADMIN 200 (이전 date 캐스트 500)', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const res = await request.get(`${API}/peer-review/statistics`, { headers: authHeaders(admin) });
    expect(res.ok()).toBeTruthy();
  });

  test('followups 날짜 필터 — ADMIN 200 (이전 str→date 500)', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const res = await request.get(`${API}/followups?from_date=2026-01-01&to_date=2026-12-31`, { headers: authHeaders(admin) });
    expect(res.ok()).toBeTruthy();
  });

  test('archive 날짜 필터 — ADMIN 200 (이전 str→DateTime 500)', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const res = await request.get(`${API}/archive?from_date=2026-01-01&to_date=2026-12-31`, { headers: authHeaders(admin) });
    expect(res.ok()).toBeTruthy();
  });

  // 그룹2 P2 — IDOR/PHI 스코프(researcher는 식별 리포트·매핑·공유 접근 불가). PHYSICIAN 본인-의뢰 스코프는 코드 가드(시드 한계).
  test('P2 reports list — researcher 403 (이전 누구나 PHI findings 열람)', async ({ request }) => {
    const r = await apiLogin(request, 'researcher');
    expect((await request.get(`${API}/reports`, { headers: authHeaders(r) })).status()).toBe(403);
  });
  test('P2 patient-mappings — researcher 403 (이름↔MRN 연계표)', async ({ request }) => {
    const r = await apiLogin(request, 'researcher');
    expect((await request.get(`${API}/patient-mappings`, { headers: authHeaders(r) })).status()).toBe(403);
  });
  test('P2 share 생성 — researcher 403', async ({ request }) => {
    const r = await apiLogin(request, 'researcher');
    const res = await request.post(`${API}/share`, { headers: authHeaders(r), data: { study_instance_uid: '1.2.3.test' } });
    expect(res.status()).toBe(403);
  });

  // 그룹2 P3 — HIS inbound 파괴적 쓰기. 서비스키 + default-off 게이트(이전엔 아무 PACS 사용자 JWT로 호출 가능).
  test('P3 his/cancel-order — 사용자 JWT로는 차단(default-off 503/401)', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const res = await request.post(`${API}/his/cancel-order`, { headers: authHeaders(admin), data: {} });
    expect([503, 401]).toContain(res.status()); // 서비스키 필요 — 사용자 JWT 무력
  });
  test('P3 his/requests(PACS운영) — researcher 403', async ({ request }) => {
    const r = await apiLogin(request, 'researcher');
    expect((await request.get(`${API}/his/requests`, { headers: authHeaders(r) })).status()).toBe(403);
  });

  // 그룹2 P5 — normalization 검토 큐 backend 신설(이전 프론트가 없는 /batches/reviews 호출 404).
  test('P5 batch/reviews — admin 200(Paginated) / researcher 403', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const res = await request.get(`${API}/batch/reviews`, { headers: authHeaders(admin) });
    expect(res.ok()).toBeTruthy();
    const d = await res.json();
    expect(d).toHaveProperty('items'); expect(d).toHaveProperty('total_pages');
    const r = await apiLogin(request, 'researcher');
    expect((await request.get(`${API}/batch/reviews`, { headers: authHeaders(r) })).status()).toBe(403);
  });
  test('P5 batch/reviews 결정 — 미존재 404 / 잘못된 값 422', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const nf = await request.post(`${API}/batch/reviews/00000000-0000-0000-0000-000000000000`, { headers: authHeaders(admin), data: { decision: 'approve' } });
    expect(nf.status()).toBe(404);
    const bad = await request.post(`${API}/batch/reviews/00000000-0000-0000-0000-000000000000`, { headers: authHeaders(admin), data: { decision: 'maybe' } });
    expect(bad.status()).toBe(422);
  });

  // 그룹2 P4 — 기능 버그 회귀 가드.
  test('F1 hospitalrun/orders/pending — ADMIN 200 (이전 깨진 join+RADIOLOGY→503 위장)', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const res = await request.get(`${API}/hospitalrun/orders/pending`, { headers: authHeaders(admin) });
    expect(res.ok()).toBeTruthy(); // 503 'DB연결실패' 위장이던 것 복구(encounters join+department=IMAGING)
  });

  test('F4 dicomweb/studies — modalities 채워짐 (이전 항상 빈문자)', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const res = await request.get(`${API}/dicomweb/studies?limit=10`, { headers: authHeaders(admin) });
    expect(res.ok()).toBeTruthy();
    const results = (await res.json()).results || [];
    test.skip(results.length === 0, 'no studies');
    // RequestedTags 적용으로 최소 1건은 modality가 채워져야(이전엔 전부 "")
    expect(results.some((r: any) => (r.modalities || '').length > 0)).toBeTruthy();
  });

  // 그룹2 P1 — 파괴적/외부반출 EP의 BTG 우회 차단(allow_btg=False). researcher+BTG 헤더로도 거부.
  const btg = (s: any) => ({ ...authHeaders(s), 'X-Break-The-Glass': 'true', 'X-Break-The-Glass-Reason': 'e2e' });

  test('BTG 우회 차단 — qc/merge-studies (researcher+BTG 403)', async ({ request }) => {
    const r = await apiLogin(request, 'researcher');
    const res = await request.post(`${API}/qc/merge-studies`, { headers: btg(r), data: {} });
    expect(res.status()).toBe(403);
  });

  test('BTG 우회 차단 — external-consult 생성 (researcher+BTG 403)', async ({ request }) => {
    const r = await apiLogin(request, 'researcher');
    const res = await request.post(`${API}/external-consult`, { headers: btg(r), data: {} });
    expect(res.status()).toBe(403);
  });

  // batch WS 토큰 인증(decode_token fail-closed)은 HTTP GET이 WS 라우트에서 404라 request로 검증 불가 →
  // 코드 가드(decode_token→sub 신원, 토큰 무효 시 close 1008)로 보장. WS 핸드셰이크 E2E는 별도.

  test('export RBAC — researcher 403 / admin 비-403 (이전 누구나 PHI 반출)', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const studies = await request.get(`${API}/patients/P2026-0006/studies`, { headers: authHeaders(admin) });
    const orthancId = studies.ok() ? (await studies.json()).studies?.[0]?.orthanc_id : '';
    test.skip(!orthancId, 'no study');

    const researcher = await apiLogin(request, 'researcher');
    const denied = await request.get(`${API}/export/study/${orthancId}/dicom`, { headers: authHeaders(researcher) });
    expect(denied.status()).toBe(403);

    const ok = await request.get(`${API}/export/study/${orthancId}/dicom`, { headers: authHeaders(admin) });
    expect(ok.status()).not.toBe(403); // 임상 staff는 허용(200 또는 데이터 의존 404, 인가 차단 아님)
  });

  // 워크리스트 변경 감사(v13.38): 검사 오더의 생성/수정/삭제가 audit_logs에 전혀
  // 남지 않던 갭. 관리자가 오더 상태를 바꾸거나 지워도 기록이 없었다(LIS 고아
  // 워크리스트 정리 중 발견). 전후 변경값까지 남아야 사후 추적이 성립한다.
  test('워크리스트 변경 감사 — 생성/수정/삭제 + 상태 전후 기록', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const acc = `ACC-E2E-AUD-${Date.now()}`;

    const created = await request.post(`${API}/worklist`, {
      headers: authHeaders(admin),
      data: {
        patient_id: 'E2E-AUD-1', patient_name: '감사^회귀', accession_number: acc,
        requested_procedure_id: 'P1', scheduled_station_ae_title: 'OPENPACS',
        modality: 'CR', scheduled_date: '2026-08-03',
      },
    });
    expect(created.status()).toBe(201);
    const id = (await created.json()).id as string;

    try {
      const patched = await request.patch(`${API}/worklist/${id}`, {
        headers: authHeaders(admin),
        data: { status: 'cancelled' },
      });
      expect(patched.ok()).toBeTruthy();
    } finally {
      const del = await request.delete(`${API}/worklist/${id}`, { headers: authHeaders(admin) });
      expect(del.status()).toBe(204);
    }

    // 감사 로그에 3종이 모두 남아야 한다 (감사는 비동기가 아니라 동일 요청 내 기록)
    const logs = await request.get(`${API}/audit?resource_type=WorklistItem&limit=50`, {
      headers: authHeaders(admin),
    });
    expect(logs.ok()).toBeTruthy();
    const rows = ((await logs.json()).results ?? []) as any[];
    const mine = rows.filter(r => JSON.stringify(r.details ?? {}).includes(acc));
    const actions = mine.map(r => r.action);
    for (const a of ['WORKLIST_CREATED', 'WORKLIST_UPDATED', 'WORKLIST_DELETED']) {
      expect(actions, `${a} 감사 누락`).toContain(a);
    }

    // 수정 감사는 전후 값을 담아야 한다 — "무엇이 무엇으로" 없으면 추적 불가
    const upd = mine.find(r => r.action === 'WORKLIST_UPDATED');
    expect(upd.details.changes?.status).toEqual({ from: 'SCHEDULED', to: 'CANCELLED' });
  });

  // 워크리스트 PHI 열거 차단(v13.41): 워크리스트 응답은 환자명·PatientID·생년월일을
  // 그대로 담는데 조회 3종이 get_current_user였다 → RESEARCHER가 전량 열거 200이었다.
  // 리포트(v13.8)·QIDO(v13.19)에 이미 적용한 차단이 워크리스트에만 누락돼 있었다.
  test('워크리스트 PHI 열거 — researcher 403 (list·stats·단건)', async ({ request }) => {
    const researcher = await apiLogin(request, 'researcher');
    const hr = authHeaders(researcher);
    for (const path of ['/worklist?limit=1', '/worklist/stats']) {
      expect((await request.get(`${API}${path}`, { headers: hr })).status(), path).toBe(403);
    }

    // 임상 역할은 유지되어야 한다(과차단 방지)
    const rad = await apiLogin(request, 'radiologist');
    expect((await request.get(`${API}/worklist?limit=1`, { headers: authHeaders(rad) })).status())
      .toBe(200);

    // 단건 조회도 동일 — 실제 항목으로 확인
    const admin = await apiLogin(request, 'admin');
    const ha = authHeaders(admin);
    const list = await request.get(`${API}/worklist?limit=1`, { headers: ha });
    const items = (await list.json()).results ?? [];
    if (items.length) {
      expect((await request.get(`${API}/worklist/${items[0].id}`, { headers: hr })).status())
        .toBe(403);
    }
  });

  // PHI 열거 표면 전수(v13.41): 워크리스트 수정 후 161개 GET을 RESEARCHER 토큰으로
  // 훑었더니 6개가 더 나왔다(ai/jobs·reading-queue·hospitalrun orders·emergency board·
  // retake·dicom-issues). 원인은 역할 집합이 파일마다 흩어져 새 EP가 조용히
  // get_current_user로 열린 것 → 공용 ClinicalPHIReadRoles로 통일했다.
  // 이 가드는 "그 표면이 다시 열리지 않는지"를 지킨다.
  test('PHI 열거 표면 — researcher 403 / 임상 역할 200 (과차단 방지)', async ({ request }) => {
    const PHI_PATHS = [
      '/ai/jobs',
      '/dashboard/reading-queue',
      '/hospitalrun/orders/pending',
      '/emergency/board',
      '/retake',
      '/dicom-issues',
      '/worklist?limit=1',
    ];
    const researcher = await apiLogin(request, 'researcher');
    const hr = authHeaders(researcher);
    for (const p of PHI_PATHS) {
      expect((await request.get(`${API}${p}`, { headers: hr })).status(), `researcher ${p}`).toBe(403);
    }

    // 임상 역할은 그대로 열려 있어야 한다 — 과차단이면 운영이 멈춘다
    const rad = await apiLogin(request, 'radiologist');
    const hd = authHeaders(rad);
    for (const p of PHI_PATHS) {
      expect((await request.get(`${API}${p}`, { headers: hd })).status(), `radiologist ${p}`).toBe(200);
    }
  });

  // 쓰기 표면(v13.42): 쓰기 EP 중 get_current_user(역할 무검사)만 걸려 있던 8건을
  // 기존 동종 패턴에 맞춰 가드했다(업로드=stow_rs와 동일, 리포트 작성=create_report와 동일).
  // 403이면 가드 통과 전 차단, 422면 가드는 통과하고 본문 검증에서 막힌 것 — 둘을 구분해야
  // "인가가 실제로 걸렸는지"를 확인할 수 있다.
  test('쓰기 표면 — researcher 403 / 임상 역할은 인가 통과(422)', async ({ request }) => {
    const WRITE_PATHS = [
      '/ai/inference',
      '/ai/apply-to-report',
      '/normalization/ai-analyze',
      '/validation/validate',
      '/batch/normalize/upload',
    ];
    const researcher = await apiLogin(request, 'researcher');
    const rad = await apiLogin(request, 'radiologist');

    for (const p of WRITE_PATHS) {
      const denied = await request.post(`${API}${p}`, {
        headers: authHeaders(researcher), data: {}, failOnStatusCode: false,
      });
      expect(denied.status(), `researcher ${p}`).toBe(403);

      const allowed = await request.post(`${API}${p}`, {
        headers: authHeaders(rad), data: {}, failOnStatusCode: false,
      });
      expect(allowed.status(), `radiologist ${p} (인가는 통과해야 함)`).not.toBe(403);
    }
  });

  // 죽은 중복 share-link 제거(v13.42): annotations.py에 get_current_user만 걸린 공유링크
  // 생성 EP가 있었다. share_link.py에 제대로 가드된 동일 기능이 있고, 이쪽이 쓰던
  // shared_links 테이블은 읽는 코드가 없어 토큰이 소비 불가였다(동작하지 않는 링크).
  test('죽은 중복 share-link 제거 — /studies/{uid}/share 404', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const res = await request.post(`${API}/studies/1.2.3/share`, {
      headers: authHeaders(admin), failOnStatusCode: false,
    });
    expect(res.status(), '제거된 EP가 되살아나면 무권한 공유 경로가 다시 열린다').toBe(404);

    // 주석 조회/저장은 임상 역할로 유지
    const researcher = await apiLogin(request, 'researcher');
    expect((await request.get(`${API}/studies/1.2.3/annotations`, {
      headers: authHeaders(researcher),
    })).status()).toBe(403);
    expect((await request.get(`${API}/studies/1.2.3/annotations`, {
      headers: authHeaders(admin),
    })).status()).toBe(200);
  });

  // BTG 우회 차단 확장(v13.44): v12.3 정책(BTG=임상 read 한정, 관리/반출/삭제는
  // allow_btg=False)에 해당하는데 지정이 빠져 있던 3건. 확정 리포트 잠금 해제(법적
  // 의무기록 수정)·환자 매핑 생성(데이터 귀속)·HIS 전송(외부 반출).
  test('BTG 우회 차단 — unlock·patient-mapping·HIS sync (researcher+BTG 403)', async ({ request }) => {
    const r = await apiLogin(request, 'researcher');
    const admin = await apiLogin(request, 'admin');
    const list = await request.get(`${API}/reports?limit=1`, { headers: authHeaders(admin) });
    const rid = ((await list.json()).results ?? [])[0]?.id ?? '00000000-0000-0000-0000-000000000000';

    for (const p of [`/reports/${rid}/unlock`, '/patient-mappings', '/hospitalrun/reports/sync']) {
      const res = await request.post(`${API}${p}`, { headers: btg(r), data: {} });
      expect(res.status(), `BTG로 ${p} 통과하면 안 된다`).toBe(403);
    }

    // 정상 경로는 막히지 않아야 한다(과차단 방지) — 403이 아니면 인가는 통과한 것
    for (const p of ['/patient-mappings', '/hospitalrun/reports/sync']) {
      const ok = await request.post(`${API}${p}`, {
        headers: authHeaders(admin), data: {}, failOnStatusCode: false,
      });
      expect(ok.status(), `admin ${p}`).not.toBe(403);
    }
  });

  // 리포트 계열 스코프 일관성(v13.43): v13.8이 /reports·PDF를 ReportReadRoles +
  // PHYSICIAN 본인의뢰 스코프로 막았는데 형제 EP `/{id}/structured-data`가
  // get_current_user뿐이라 그 보호를 우회했다(researcher가 리포트 소견 200).
  test('리포트 스코프 — structured-data가 /reports와 같은 게이트', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');
    const ha = authHeaders(admin);
    const list = await request.get(`${API}/reports?limit=1`, { headers: ha });
    expect(list.ok()).toBeTruthy();
    const body = await list.json();
    const rid = (body.results ?? body.reports ?? [])[0]?.id;
    test.skip(!rid, 'no report');

    // 본문이 막히는데 구조화 데이터가 열리면 보호가 무의미하다
    const researcher = await apiLogin(request, 'researcher');
    const hr = authHeaders(researcher);
    expect((await request.get(`${API}/reports?limit=1`, { headers: hr })).status()).toBe(403);
    expect(
      (await request.get(`${API}/reports/${rid}/structured-data`, { headers: hr })).status(),
      'structured-data가 리포트 보호를 우회하면 안 된다',
    ).toBe(403);

    // 임상 역할은 유지 + 미존재 리포트는 404(존재 여부 노출 없이 일관)
    const rad = await apiLogin(request, 'radiologist');
    expect((await request.get(`${API}/reports/${rid}/structured-data`, {
      headers: authHeaders(rad),
    })).status()).toBe(200);
    expect((await request.get(
      `${API}/reports/00000000-0000-0000-0000-000000000000/structured-data`, { headers: ha },
    )).status()).toBe(404);
  });

  // 감사 식별자 컬럼(v13.39): AuditLog에 resource_id/study_instance_uid/patient_id
  // 전용 컬럼과 검색 필터가 있는데 _log_audit_entry가 한 번도 채우지 않아,
  // study_instance_uid가 전 행 NULL이고 감사 UI의 study 검색이 영구 0건이었다.
  test('감사 식별자 — resource_id·study_instance_uid 기록 + study 검색 동작', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');

    const studies = await request.get(`${API}/patients/P2026-0006/studies`, { headers: authHeaders(admin) });
    const uid = studies.ok() ? (await studies.json()).studies?.[0]?.study_instance_uid : '';
    test.skip(!uid, 'no study');

    // 데코레이터 경로(@AuditLogger.log)를 타는 엔드포인트로 검증
    const created = await request.post(`${API}/teaching/cases`, {
      headers: authHeaders(admin),
      data: {
        study_instance_uid: uid, title: `감사식별자 E2E ${Date.now()}`,
        diagnosis: 'regression', difficulty: 'beginner',
      },
    });
    expect(created.ok()).toBeTruthy();
    const caseId = (await created.json()).id as string;

    try {
      // study_uid 필터로 조회되어야 한다 (컬럼이 NULL이면 영구히 0건)
      const byStudy = await request.get(`${API}/audit?study_uid=${uid}&limit=20`, {
        headers: authHeaders(admin),
      });
      expect(byStudy.ok()).toBeTruthy();
      const rows = ((await byStudy.json()).results ?? []) as any[];
      const hit = rows.find(r => r.action === 'TEACHING_CASE_CREATED' && r.resource_id === caseId);
      expect(hit, 'study_uid 필터로 방금 생성한 감사 항목이 조회되어야 함').toBeTruthy();
      expect(hit.study_instance_uid).toBe(uid);
    } finally {
      await request.delete(`${API}/teaching/cases/${caseId}`, { headers: authHeaders(admin) });
    }
  });

  // v13.46 — 인증 이벤트가 audit_logs에 단 한 건도 없었다(실측). logout에만 기록
  // 코드가 있었고 실사용 0건이라, "누가 언제 들어왔나"·"언제부터 자격증명 공격이
  // 있었나"를 사후에 답할 수 없었다. 실패 로그인이 특히 중요한 신호다.
  test('로그인 감사 — 실패/성공 모두 기록, 비밀번호 미기록', async ({ request }) => {
    const probe = `e2e-audit-probe-${Date.now()}`;

    // 실패 로그인(존재하지 않는 계정) — 401이어야 하고 감사에 남아야 한다
    const bad = await request.post(`${API}/auth/login`, {
      data: { username: probe, password: 'wrong-on-purpose-e2e' },
    });
    expect(bad.status()).toBe(401);

    const admin = await apiLogin(request, 'admin');   // 성공 경로도 함께 발생시킨다
    const res = await request.get(`${API}/audit?action=LOGIN&limit=50`, {
      headers: authHeaders(admin),
    });
    expect(res.ok()).toBeTruthy();
    const rows = ((await res.json()).results ?? []) as any[];

    const failed = rows.find(r => r.username === probe && r.status === 'FAILED');
    expect(failed, '실패 로그인이 감사에 기록되어야 함').toBeTruthy();
    // 계정 열거 방지 — 사용자 부재/비밀번호 불일치를 구분해 남기지 않는다
    expect(failed.details?.reason).toBe('invalid_credentials');

    expect(rows.some(r => r.status === 'SUCCESS'), '성공 로그인도 기록되어야 함').toBeTruthy();

    // 비밀번호가 감사에 실리면 안 된다
    expect(JSON.stringify(rows)).not.toContain('wrong-on-purpose-e2e');
  });

  // v13.46 — 공유 링크는 **무인증 외부 열람 자격**인데 발급/취소가 무기록이었다.
  // 링크 자체는 Redis TTL로 사라지므로 감사 로그가 유일한 영구 기록이 된다.
  // (REPORT_UNLOCKED·PATIENT_MAPPING_CREATED는 서버 IT it-audit-coverage.sh가 가드 —
  //  합성 리포트/매핑 행을 DB에 직접 만들어야 해서 E2E보다 IT가 적합하다.)
  test('공유 링크 감사 — 발급/취소 기록, 토큰 전문 미기록', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');

    const studies = await request.get(`${API}/patients/P2026-0006/studies`, { headers: authHeaders(admin) });
    const uid = studies.ok() ? (await studies.json()).studies?.[0]?.study_instance_uid : '';
    test.skip(!uid, 'no study');

    const created = await request.post(`${API}/share`, {
      headers: authHeaders(admin),
      data: { study_instance_uid: uid, expires_hours: 1, note: 'e2e audit guard' },
    });
    expect(created.ok()).toBeTruthy();
    const token = (await created.json()).token as string;

    const res = await request.get(`${API}/audit?action=SHARE_LINK_CREATED&limit=20`, {
      headers: authHeaders(admin),
    });
    const rows = ((await res.json()).results ?? []) as any[];
    const hit = rows.find(r => r.resource_id === token.slice(0, 8));
    expect(hit, '공유 링크 발급이 감사에 기록되어야 함').toBeTruthy();
    expect(hit.study_instance_uid).toBe(uid);
    // 감사 로그가 자격증명 저장소가 되면 안 된다 — 8자 접두만
    expect(JSON.stringify(rows)).not.toContain(token);

    const revoked = await request.delete(`${API}/share/${token}`, { headers: authHeaders(admin) });
    expect(revoked.ok()).toBeTruthy();
    const res2 = await request.get(`${API}/audit?action=SHARE_LINK_REVOKED&limit=20`, {
      headers: authHeaders(admin),
    });
    const rows2 = ((await res2.json()).results ?? []) as any[];
    expect(rows2.some(r => r.resource_id === token.slice(0, 8)),
      '공유 링크 취소가 감사에 기록되어야 함').toBeTruthy();
  });

  // v13.47 — 라이브 액션 43종 중 2종만 소문자였다(`view` 319행 = 최다 액션,
  // `ai_inference`). 대문자로 조회하면 최다 액션이 통째로 안 잡혔다. 쓰기 측은
  // 대문자로 통일했지만 기존 행은 append-only라 소급 정정할 수 없어, **조회 측이
  // 대소문자 무관**해야 과거·현재가 한 필터로 잡힌다.
  test('감사 action 필터 — 대소문자 무관(소급 정정 불가한 과거 행 포함)', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');

    const count = async (action: string) => {
      const r = await request.get(`${API}/audit?action=${action}&limit=1`, {
        headers: authHeaders(admin),
      });
      expect(r.ok()).toBeTruthy();
      return (await r.json()).total as number;
    };

    // 같은 액션을 대/소문자로 조회하면 같은 건수가 나와야 한다
    const [upper, lower] = [await count('VIEW'), await count('view')];
    expect(upper).toBe(lower);
    expect(upper, 'VIEW 감사 행이 있어야 함(환자 studies 조회 경로)').toBeGreaterThan(0);

    const [lUp, lLow] = [await count('LOGIN'), await count('login')];
    expect(lUp).toBe(lLow);

    // stats의 by_action은 대문자로 정규화돼 같은 액션이 두 버킷으로 갈리지 않아야 한다
    const stats = await request.get(`${API}/audit/stats`, { headers: authHeaders(admin) });
    expect(stats.ok()).toBeTruthy();
    const byAction = (await stats.json()).by_action as Record<string, number>;
    const lowerKeys = Object.keys(byAction).filter(k => k !== k.toUpperCase());
    expect(lowerKeys, `by_action에 소문자 버킷이 남아 있음: ${lowerKeys.join(',')}`).toHaveLength(0);
  });

  // v13.47 — 형제 EP(precheck·analyze·compare·explain)는 모두 @AuditLogger.log를
  // 달고 있는데 이 설정 변경만 빠져 있었다(v13.46 스윕의 캘리브레이션에서 발견).
  // 어느 모달리티가 자동 초안 대상인지를 바꾸므로 임상 동작에 직접 영향이 있다.
  test('AI 자동초안 설정 감사 — 전후 값 기록', async ({ request }) => {
    const admin = await apiLogin(request, 'admin');

    const read = await request.get(`${API}/ai/auto-draft/config`, { headers: authHeaders(admin) });
    const original = read.ok() ? await read.json() : null;

    try {
      const put = await request.put(`${API}/ai/auto-draft/config`, {
        headers: authHeaders(admin),
        data: { enabled: false, modalities: ['CR'], min_series: 1 },
      });
      expect(put.ok()).toBeTruthy();

      const res = await request.get(`${API}/audit?action=AI_AUTO_DRAFT_CONFIG_UPDATED&limit=5`, {
        headers: authHeaders(admin),
      });
      const rows = ((await res.json()).results ?? []) as any[];
      expect(rows.length, '설정 변경이 감사에 기록되어야 함').toBeGreaterThan(0);
      // 설정 감사의 가치는 "무엇이 무엇으로" — after가 비어 있으면 의미가 없다
      expect(rows[0].details?.after).toBeTruthy();
      expect(rows[0].details).toHaveProperty('before');
    } finally {
      if (original) {
        await request.put(`${API}/ai/auto-draft/config`, {
          headers: authHeaders(admin), data: original,
        });
      }
    }
  });
});
