'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

type ViewToken = {
  id: string;
  patient_id: string;
  patient_name: string | null;
  memo: string | null;
  expires_at: string;
  revoked: boolean;
  expired: boolean;
  use_count: number;
  last_used_at: string | null;
  created_at: string;
};

export default function PatientLinksPage() {
  const [tokens, setTokens] = useState<ViewToken[]>([]);
  const [patientId, setPatientId] = useState('');
  const [patientName, setPatientName] = useState('');
  const [memo, setMemo] = useState('');
  const [expiresHours, setExpiresHours] = useState(72);
  const [busy, setBusy] = useState(false);
  const [issued, setIssued] = useState<{ url: string; expires_at: string } | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: 'ok' | 'err' } | null>(null);
  const [disabled, setDisabled] = useState(false);

  const showToast = (msg: string, type: 'ok' | 'err' = 'ok') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };

  const load = async () => {
    try {
      const data = await apiFetch<{ tokens: ViewToken[] }>('/api/v1/patient-view/tokens');
      setTokens(data.tokens);
    } catch (e: any) {
      showToast(e.message || '목록 조회 실패', 'err');
    }
  };

  useEffect(() => { load(); }, []);

  const issue = async () => {
    if (!patientId.trim()) { showToast('환자번호(MRN)를 입력하세요.', 'err'); return; }
    setBusy(true);
    setIssued(null);
    try {
      const res = await apiFetch<{ ok: boolean; url: string; expires_at: string }>(
        '/api/v1/patient-view/token',
        {
          method: 'POST',
          body: JSON.stringify({
            patient_id: patientId.trim(),
            patient_name: patientName.trim() || null,
            memo: memo.trim() || null,
            expires_hours: expiresHours,
          }),
        });
      setIssued({ url: res.url, expires_at: res.expires_at });
      setPatientId(''); setPatientName(''); setMemo('');
      showToast('열람 링크가 발급되었습니다. 아래 URL은 지금만 표시됩니다.');
      load();
    } catch (e: any) {
      if (String(e.message).includes('PATIENT_VIEW_DISABLED') || String(e.message).includes('503')) {
        setDisabled(true);
        showToast('환자 열람 포털이 비활성화 상태입니다 (PATIENT_VIEW_ENABLED).', 'err');
      } else {
        showToast(e.message || '발급 실패', 'err');
      }
    }
    setBusy(false);
  };

  const revoke = async (id: string) => {
    if (!confirm('이 링크를 폐기할까요? 환자는 더 이상 열람할 수 없습니다.')) return;
    try {
      await apiFetch(`/api/v1/patient-view/tokens/${id}/revoke`, { method: 'POST' });
      showToast('폐기되었습니다.');
      load();
    } catch (e: any) {
      showToast(e.message || '폐기 실패', 'err');
    }
  };

  const copyUrl = async () => {
    if (!issued) return;
    const full = `${window.location.origin}${issued.url}`;
    await navigator.clipboard.writeText(full);
    showToast('URL이 복사되었습니다.');
  };

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <h1 className="text-xl font-bold mb-1">환자 결과 열람 링크</h1>
      <p className="text-sm text-gray-500 mb-5">
        환자 본인이 웹에서 자기 검사·확정 판독문을 열람하는 링크를 발급합니다.
        링크는 만료 시각까지 유효하며 언제든 폐기할 수 있습니다.
      </p>

      {toast && (
        <div className={`mb-4 p-3 rounded-xl text-sm ${toast.type === 'ok' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
          {toast.msg}
        </div>
      )}
      {disabled && (
        <div className="mb-4 p-3 rounded-xl text-sm bg-amber-50 text-amber-700">
          서버 설정 <code>PATIENT_VIEW_ENABLED=true</code> 후 사용 가능합니다 (default-off — PHI 열람 표면).
        </div>
      )}

      {/* 발급 폼 */}
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow p-4 mb-4">
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
          <input value={patientId} onChange={e => setPatientId(e.target.value)}
            placeholder="환자번호(MRN) *" className="border rounded-xl px-3 py-2 text-sm dark:bg-gray-700" />
          <input value={patientName} onChange={e => setPatientName(e.target.value)}
            placeholder="환자명 (표시용)" className="border rounded-xl px-3 py-2 text-sm dark:bg-gray-700" />
          <input value={memo} onChange={e => setMemo(e.target.value)}
            placeholder="메모 (발급 사유)" className="border rounded-xl px-3 py-2 text-sm dark:bg-gray-700" />
          <div className="flex gap-2">
            <select value={expiresHours} onChange={e => setExpiresHours(Number(e.target.value))}
              className="border rounded-xl px-2 py-2 text-sm flex-1 dark:bg-gray-700">
              <option value={24}>24시간</option>
              <option value={72}>3일</option>
              <option value={168}>7일</option>
              <option value={720}>30일</option>
            </select>
            <button onClick={issue} disabled={busy}
              className="px-4 py-2 bg-teal-600 text-white rounded-xl text-sm font-medium hover:bg-teal-700 disabled:opacity-50 whitespace-nowrap">
              {busy ? '발급 중…' : '발급'}
            </button>
          </div>
        </div>

        {issued && (
          <div className="mt-3 p-3 bg-teal-50 rounded-xl">
            <div className="text-xs font-bold text-teal-700 mb-1">발급된 링크 (지금만 표시 — 환자에게 안전한 채널로 전달)</div>
            <div className="flex gap-2 items-center">
              <code className="text-xs break-all flex-1">{typeof window !== 'undefined' ? window.location.origin : ''}{issued.url}</code>
              <button onClick={copyUrl}
                className="px-3 py-1.5 bg-teal-600 text-white rounded-lg text-xs shrink-0">복사</button>
            </div>
            <div className="text-[11px] text-gray-500 mt-1">만료: {new Date(issued.expires_at).toLocaleString('ko-KR')}</div>
          </div>
        )}
      </div>

      {/* 목록 */}
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 dark:bg-gray-700 text-gray-500 text-xs">
            <tr>
              <th className="px-4 py-3 text-left">환자</th>
              <th className="px-4 py-3 text-left">메모</th>
              <th className="px-4 py-3 text-left">만료</th>
              <th className="px-4 py-3 text-center">사용</th>
              <th className="px-4 py-3 text-center">상태</th>
              <th className="px-4 py-3 text-center">작업</th>
            </tr>
          </thead>
          <tbody>
            {tokens.map(t => (
              <tr key={t.id} className="border-t dark:border-gray-700">
                <td className="px-4 py-2.5">
                  <div className="font-medium">{t.patient_name || '-'}</div>
                  <div className="text-xs text-gray-400">{t.patient_id}</div>
                </td>
                <td className="px-4 py-2.5 text-xs text-gray-500">{t.memo || '-'}</td>
                <td className="px-4 py-2.5 text-xs">{new Date(t.expires_at).toLocaleString('ko-KR')}</td>
                <td className="px-4 py-2.5 text-center text-xs">
                  {t.use_count}회
                  {t.last_used_at && <div className="text-[10px] text-gray-400">{new Date(t.last_used_at).toLocaleDateString('ko-KR')}</div>}
                </td>
                <td className="px-4 py-2.5 text-center">
                  {t.revoked ? <span className="text-xs px-2 py-0.5 rounded bg-red-100 text-red-600">폐기</span> :
                   t.expired ? <span className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-500">만료</span> :
                   <span className="text-xs px-2 py-0.5 rounded bg-green-100 text-green-700">유효</span>}
                </td>
                <td className="px-4 py-2.5 text-center">
                  {!t.revoked && !t.expired && (
                    <button onClick={() => revoke(t.id)}
                      className="text-xs text-red-500 hover:text-red-700">폐기</button>
                  )}
                </td>
              </tr>
            ))}
            {tokens.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400 text-sm">발급된 링크가 없습니다.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
