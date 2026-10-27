'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch, getUser } from '@/lib/api';

type Assignment = {
  id: string; study_instance_uid: string; patient_id: string | null;
  patient_name: string | null; modality: string | null;
  assigned_to_username: string; assigned_to_name: string | null;
  assignment_type: string; status: string; assigned_by: string | null;
  assigned_at: string | null; completed_at: string | null; viewer_url: string;
};
type Reader = { username: string; name: string; open_assignments: number; is_primary: boolean; oncall_id: string | null };

const STATUS: Record<string, { label: string; color: string }> = {
  pending: { label: '대기', color: 'bg-amber-100 text-amber-700' },
  in_progress: { label: '판독중', color: 'bg-blue-100 text-blue-700' },
  completed: { label: '완료', color: 'bg-emerald-100 text-emerald-700' },
};
const TYPE: Record<string, string> = { shift: '시프트', manual: '수동', escalation: '에스컬레이션' };

export default function AssignmentsPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [items, setItems] = useState<Assignment[]>([]);
  const [readers, setReaders] = useState<Reader[]>([]);
  const [onCall, setOnCall] = useState(false);
  const [statusFilter, setStatusFilter] = useState('');
  const [currentOnly, setCurrentOnly] = useState(true);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);

  useEffect(() => {
    const u = getUser();
    if (!u || !['admin', 'radiologist', 'technologist'].includes(u.role)) { router.replace('/'); return; }
    setUser(u);
  }, []);

  const load = () => {
    let url = `/api/v1/reading-assignments?current_only=${currentOnly}&limit=300`;
    if (statusFilter) url += `&status=${statusFilter}`;
    apiFetch<{ assignments: Assignment[] }>(url).then(d => setItems(d.assignments || [])).catch(() => {});
    apiFetch<{ on_call: boolean; readers: Reader[] }>('/api/v1/reading-assignments/on-duty')
      .then(d => { setReaders(d.readers || []); setOnCall(d.on_call); }).catch(() => {});
  };

  useEffect(() => { if (user) load(); }, [user, statusFilter, currentOnly]);

  const runAuto = async () => {
    setBusy('auto'); setMsg(null);
    try {
      const r = await apiFetch<any>('/api/v1/reading-assignments/auto', { method: 'POST' });
      setMsg({ text: `자동 배정 완료 — 신규 ${r.assigned}건 / 근무 판독의 ${r.readers}명${r.on_call ? '' : ' (온콜 없음 → 활성 판독의 폴백)'}`, ok: true });
      load();
    } catch (e: any) { setMsg({ text: e?.message || '실패', ok: false }); }
    finally { setBusy(''); }
  };

  const changeStatus = async (id: string, status: string) => {
    setBusy(id);
    try { await apiFetch(`/api/v1/reading-assignments/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }); load(); }
    catch (e: any) { setMsg({ text: e?.message || '실패', ok: false }); }
    finally { setBusy(''); }
  };

  const reassign = async (a: Assignment, username: string) => {
    if (!username) return;
    const reader = readers.find(r => r.username === username);
    setBusy(a.id);
    try {
      await apiFetch('/api/v1/reading-assignments', {
        method: 'POST',
        body: JSON.stringify({
          study_instance_uid: a.study_instance_uid, assigned_to_username: username,
          assigned_to_name: reader?.name, patient_id: a.patient_id,
          patient_name: a.patient_name, modality: a.modality,
        }),
      });
      load();
    } catch (e: any) { setMsg({ text: e?.message || '실패', ok: false }); }
    finally { setBusy(''); }
  };

  if (!user) return null;
  const isAdmin = user.role === 'admin';

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">판독 배정</h1>
        <p className="text-sm text-slate-500 mt-1">근무 시간대(온콜) 기준 미판독 검사 자동 배정 및 부하 분산 관리</p>
      </div>

      {/* 근무 판독의 + 자동배정 */}
      <div className="bg-white rounded-xl border shadow-sm p-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3 flex-wrap">
            <h2 className="font-semibold text-slate-800">현재 근무 판독의</h2>
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${onCall ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
              {onCall ? '온콜 스케줄 적용' : '온콜 없음 → 활성 판독의 폴백'}
            </span>
            {readers.map(r => (
              <span key={r.username} className="inline-flex items-center gap-1.5 text-xs bg-slate-50 border rounded-lg px-2.5 py-1">
                {r.is_primary && <span className="text-amber-500">★</span>}
                <span className="font-medium text-slate-700">{r.name}</span>
                <span className="text-slate-400">진행 {r.open_assignments}건</span>
              </span>
            ))}
            {readers.length === 0 && <span className="text-xs text-slate-400">근무 판독의 없음</span>}
          </div>
          {isAdmin && (
            <button onClick={runAuto} disabled={!!busy}
              className="px-4 py-2 bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700 disabled:opacity-50">
              {busy === 'auto' ? '배정 중…' : '⚙️ 미배정 자동 배정'}
            </button>
          )}
        </div>
        {msg && (
          <div className={`mt-3 text-sm rounded-lg px-3 py-2 ${msg.ok ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>{msg.text}</div>
        )}
      </div>

      {/* 필터 */}
      <div className="flex gap-2 items-center flex-wrap">
        <div className="flex bg-slate-100 rounded-lg p-0.5">
          {[{ k: '', l: '전체' }, { k: 'pending', l: '대기' }, { k: 'in_progress', l: '판독중' }, { k: 'completed', l: '완료' }].map(f => (
            <button key={f.k} onClick={() => setStatusFilter(f.k)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition ${statusFilter === f.k ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'}`}>{f.l}</button>
          ))}
        </div>
        <label className="flex items-center gap-1.5 text-xs text-slate-500 ml-2">
          <input type="checkbox" checked={currentOnly} onChange={e => setCurrentOnly(e.target.checked)} />
          현재 배정만
        </label>
        <div className="flex-1" />
        <span className="text-xs text-slate-400">{items.length}건</span>
      </div>

      {/* 테이블 */}
      <div className="bg-white rounded-xl border shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left">환자</th>
              <th className="px-4 py-3 text-left">모달리티</th>
              <th className="px-4 py-3 text-left">배정 판독의</th>
              <th className="px-4 py-3 text-left">유형</th>
              <th className="px-4 py-3 text-left">상태</th>
              <th className="px-4 py-3 text-left">배정일시</th>
              <th className="px-4 py-3 text-right">작업</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-12 text-center text-slate-400">배정 내역이 없습니다</td></tr>
            )}
            {items.map(a => (
              <tr key={a.id} className="border-t hover:bg-slate-50">
                <td className="px-4 py-3">
                  <div className="font-medium text-slate-800">{a.patient_name || '-'}</div>
                  <div className="text-xs text-slate-400">{a.patient_id || ''}</div>
                </td>
                <td className="px-4 py-3 text-slate-600">{a.modality || '-'}</td>
                <td className="px-4 py-3 font-medium text-slate-700">{a.assigned_to_name || a.assigned_to_username}</td>
                <td className="px-4 py-3 text-slate-500 text-xs">{TYPE[a.assignment_type] || a.assignment_type}</td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS[a.status]?.color || 'bg-slate-100 text-slate-600'}`}>
                    {STATUS[a.status]?.label || a.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-slate-500 text-xs whitespace-nowrap">
                  {a.assigned_at ? new Date(a.assigned_at).toLocaleString('ko-KR') : '-'}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1.5">
                    <a href={a.viewer_url} className="text-blue-600 hover:underline text-xs">판독</a>
                    {a.status !== 'completed' && (
                      <button onClick={() => changeStatus(a.id, 'completed')} disabled={busy === a.id}
                        className="text-xs px-2 py-1 border rounded-lg hover:bg-slate-100 disabled:opacity-40">완료</button>
                    )}
                    {isAdmin && (
                      <select defaultValue="" onChange={e => { reassign(a, e.target.value); e.target.value = ''; }}
                        disabled={busy === a.id}
                        className="text-xs border rounded-lg px-1.5 py-1 text-slate-600">
                        <option value="">재배정…</option>
                        {readers.map(r => <option key={r.username} value={r.username}>{r.name}</option>)}
                      </select>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
