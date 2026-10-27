'use client';

import { useCallback, useEffect, useState } from 'react';
import { ShieldCheck, PenLine, Loader2, AlertTriangle, Cpu } from 'lucide-react';

// 외부 PKI 전자서명(sign.example.org, flow A STAFF). FINAL 보고서에만 노출.
// 토큰 획득(Q1 ⓐ-단축): pacs-admin은 HIS와 동일 origin(https://his.example.org)이라
// HIS 세션 JWT를 localStorage['accessToken']에서 직접 읽어 staff-token EP 호출.
const HIS_STAFF_TOKEN_URL = 'https://his.example.org/api/v1/sign-integration/staff-token';

type EsignState = {
  overall_valid?: boolean;
  assurance_level?: string | null;
  hsm_anchored?: boolean;
  signed_at?: string | null;
  request_status?: string | null;
  live_assurance_level?: string | null;
};

const pacsToken = () => (typeof window !== 'undefined' ? localStorage.getItem('pacs_token') : null);

export default function ExternalEsign({ reportId }: { reportId: string }) {
  const [state, setState] = useState<EsignState | null>(null);
  const [signing, setSigning] = useState(false);
  const [err, setErr] = useState('');
  const [hidden, setHidden] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      const res = await fetch(`/pacs-api/api/v1/reports/${reportId}/esign`, {
        headers: { Authorization: `Bearer ${pacsToken()}` },
      });
      if (res.ok) setState(await res.json());
      else setState(null); // 404 = 미서명
    } catch { /* 무시 */ }
  }, [reportId]);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  const sign = useCallback(async () => {
    setSigning(true); setErr('');
    try {
      // 1) HIS 세션 JWT (동일 origin localStorage)
      const hisToken = localStorage.getItem('accessToken');
      if (!hisToken) { setErr('HIS 세션이 없습니다 — HIS 로그인 후 다시 시도하세요.'); return; }
      // 2) aud=sign staff-token 발급 (aud 미지정 → 기본 sign)
      const tokRes = await fetch(HIS_STAFF_TOKEN_URL, { headers: { Authorization: `Bearer ${hisToken}` } });
      if (!tokRes.ok) { setErr(`서명 토큰 발급 실패 (${tokRes.status})`); return; }
      const signToken = (await tokRes.json())?.data?.token;
      if (!signToken) { setErr('서명 토큰을 받지 못했습니다.'); return; }
      // 3) 최종 보고서 PDF (서명자가 본 바이트)
      const pdfRes = await fetch(`/pacs-api/api/v1/reports/${reportId}/pdf`, {
        headers: { Authorization: `Bearer ${pacsToken()}` },
      });
      if (!pdfRes.ok) { setErr(`보고서 PDF 로드 실패 (${pdfRes.status})`); return; }
      const pdf = await pdfRes.blob();
      // 4) STAFF 전자서명 (멀티파트 + X-Sign-Token)
      const fd = new FormData();
      fd.append('file', pdf, `report-${reportId}.pdf`);
      const res = await fetch(`/pacs-api/api/v1/reports/${reportId}/esign`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${pacsToken()}`, 'X-Sign-Token': signToken },
        body: fd,
      });
      if (res.status === 503) { setHidden(true); return; } // 기능 비활성
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        setErr(typeof e.detail === 'string' ? e.detail : `서명 실패 (${res.status})`);
        return;
      }
      setState(await res.json());
    } catch (e: any) {
      setErr(e?.message || '서명 처리 중 오류');
    } finally { setSigning(false); }
  }, [reportId]);

  if (hidden) return null;

  const assurance = state?.assurance_level || state?.live_assurance_level;
  const isHsm = state?.hsm_anchored || assurance === 'HSM_ANCHORED';
  const signed = !!state && (state.overall_valid || !!state.signed_at);

  return (
    <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-slate-100 bg-white p-3 text-sm">
      <span className="flex items-center gap-1.5 font-medium text-slate-600">
        <ShieldCheck size={16} className="text-indigo-500" /> 외부 전자서명 (PKI)
      </span>
      {signed ? (
        <>
          <span className="flex items-center gap-1 rounded-lg bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">
            <ShieldCheck size={13} /> 서명 완료
          </span>
          {assurance && (
            <span className={`flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium ${
              isHsm ? 'bg-violet-100 text-violet-700' : 'bg-slate-100 text-slate-600'
            }`}>
              <Cpu size={12} /> {isHsm ? 'HSM 앵커' : '소프트웨어 보증'} ({assurance})
            </span>
          )}
          {state?.signed_at && (
            <span className="text-xs text-slate-400">{new Date(state.signed_at).toLocaleString('ko-KR')}</span>
          )}
        </>
      ) : (
        <button onClick={sign} disabled={signing}
          className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-1.5 text-xs font-bold text-white transition hover:bg-indigo-700 disabled:opacity-50">
          {signing ? <><Loader2 size={13} className="animate-spin" /> 서명 중…</> : <><PenLine size={13} /> 전자서명</>}
        </button>
      )}
      {err && (
        <span className="flex items-center gap-1 text-xs text-red-600">
          <AlertTriangle size={13} /> {err}
        </span>
      )}
    </div>
  );
}
