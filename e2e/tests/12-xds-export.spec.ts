import { test, expect } from '@playwright/test';
import AdmZip from 'adm-zip';
import { apiLogin, authHeaders, API } from '../helpers/session';

// xds-i-export — XDM(XDS-I) 표준 패키지 생성·다운로드.
test.describe('XDS-I 패키지 export (XDM)', () => {
  test('요청 → ready → 다운로드 → XDM 레이아웃·METADATA.XML 검증', async ({ request }) => {
    const s = await apiLogin(request, 'radiologist');

    // CT study 선택
    const qido = await request.get(
      'https://his.example.org/dicom-web/studies?limit=50&includefield=00080061',
      { headers: authHeaders(s) },
    );
    const studies = await qido.json();
    const ct = studies.find((x: any) => (x['00080061']?.Value || []).includes('CT'));
    test.skip(!ct, '운영에 CT 없음');
    const uid = ct['0020000D'].Value[0];

    const create = await request.post(`${API}/xds-export/requests`, {
      headers: authHeaders(s),
      data: { study_instance_uids: [uid] },
    });
    expect(create.status()).toBe(202);
    const { request_id } = await create.json();

    let status = 'processing';
    let token = '';
    for (let i = 0; i < 30 && status === 'processing'; i++) {
      const r = await request.get(`${API}/xds-export/requests/${request_id}`, { headers: authHeaders(s) });
      const j = await r.json();
      status = j.status;
      if (status === 'ready') {
        token = j.download_token;
        expect(j.study_count).toBeGreaterThan(0);
      }
      if (status === 'processing') await new Promise(r => setTimeout(r, 2000));
    }
    expect(status, 'export must be ready').toBe('ready');
    expect(token).toBeTruthy();

    const dl = await request.get(
      `${API}/xds-export/requests/${request_id}/download?token=${token}`,
      { headers: authHeaders(s) },
    );
    expect(dl.status()).toBe(200);
    const zip = new AdmZip(Buffer.from(await dl.body()));
    const names = zip.getEntries().map(e => e.entryName);

    // IHE XDM 레이아웃
    expect(names).toContain('IHE_XDM/SUBSET01/METADATA.XML');
    expect(names.some(n => n.startsWith('IHE_XDM/SUBSET01/DOC') && n.endsWith('.dcm'))).toBeTruthy();
    expect(names.some(n => n.startsWith('DICOM/'))).toBeTruthy();

    // METADATA.XML = ebRIM (SubmissionSet/DocumentEntry/Association)
    const meta = zip.readAsText('IHE_XDM/SUBSET01/METADATA.XML');
    expect(meta).toContain('ExtrinsicObject');
    expect(meta).toContain('RegistryPackage');
    expect(meta).toContain('Association');
    expect(meta).toContain('application/dicom');
    // KOS formatCode (XDS-I)
    expect(meta).toContain('1.2.840.10008.5.1.4.1.1.88.59');
  });

  test('인증 — 비로그인 401', async ({ request }) => {
    const res = await request.post(`${API}/xds-export/requests`, {
      data: { study_instance_uids: ['1.2.3'] },
    });
    expect([401, 403]).toContain(res.status());
  });
});
