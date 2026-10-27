'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch, getUser } from '@/lib/api';

type Irb = {
  id: string;
  protocol_number: string;
  title: string;
  principal_investigator: string | null;
  institution: string | null;
  approved_at: string | null;
  expires_at: string | null;
  status: string;
  effective_status: string;
  days_left: number | null;
  scope_note: string | null;
};

type IrbResp = {
  summary: { total: number; active: number; expiring_soon: number; expired: number };
  items: Irb[];
};

const blankForm = {
  protocol_number: '', title: '', principal_investigator: '', institution: '',
  approved_at: '', expires_at: '', scope_note: '',
};

const statusBadge: Record<string, { label: string; cls: string }> = {
  active: { label: '유효', cls: 'bg-emerald-100 text-emerald-700' },
  suspended: { label: '중단', cls: 'bg-slate-200 text-slate-600' },
  expired: { label: '만료', cls: 'bg-red-100 text-red-700' },
};

export default function IrbPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [data, setData] = useState<IrbResp | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState<any>(blankForm);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const isAdmin = user?.role === 'admin';

  useEffect(() => {
    const u = getUser();
    if (!u || !['admin', 'radiologist', 'researcher'].includes(u.role)) { router.replace('/'); return; }
    setUser(u);
  }, []);

  const load = useCallback(() => {
    apiFetch<IrbResp>('/api/v1/irb').then(setData).catch(() => {});
  }, []);

  useEffect(() => { if (user) load(); }, [user, load]);

  const openNew = () => { setEditId(null); setForm(blankForm); setError(''); setShowForm(true); };
  const openEdit = (i: Irb) => {
    setEditId(i.id);
    setForm({
      protocol_number: i.protocol_number, title: i.title,
      principal_investigator: i.principal_investigator || '', institution: i.institution || '',
      approved_at: i.approved_at || '', expires_at: i.expires_at || '',
      scope_note: i.scope_note || '', status: i.status,
    });
    setError('');
    setShowForm(true);
  };

  const submit = async () => {
    if (!form.protocol_number || !form.title) { setError('프로토콜 번호와 제목은 필수입니다.'); return; }
    setBusy(true); setError('');
    const body: any = { ...form };
    Object.keys(body).forEach(k => { if (body[k] === '') body[k] = null; });
    try {
      if (editId) {
        await apiFetch(`/api/v1/irb/${editId}`, { method: 'PUT', body: JSON.stringify(body) });
      } else {
        await apiFetch('/api/v1/irb', { method: 'POST', body: JSON.stringify(body) });
      }
      setShowForm(false); load();
    } catch (e: any) {
      setError(e?.message || '저장에 실패했습니다 (중복 프로토콜 번호일 수 있습니다).');
    } finally {
      setBusy(false);
    }
  };

  const remove = async (i: Irb) => {
    if (!confirm(`IRB ${i.protocol_number} 를 삭제할까요?`)) return;
    try { await apiFetch(`/api/v1/irb/${i.id}`, { method: 'DELETE' }); load(); } catch {}
  };

  if (!user || !data) return <div className="text-center py-20 text-slate-400">로딩 중...</div>;

  const s = data.summary;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold">IRB 승인</h1>
          <p className="text-sm text-slate-500 mt-1">연구용 데이터 활용 근거 — IRB 승인 프로토콜 레지스트리</p>
        </div>
        {isAdmin && (
          <button onClick={openNew} className="px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700">
            + 승인 등록
          </button>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: '전체', value: s.total, color: 'text-slate-800' },
          { label: '유효', value: s.active, color: 'text-emerald-600' },
          { label: '30일 내 만료', value: s.expiring_soon, color: 'text-amber-600' },
          { label: '만료', value: s.expired, color: 'text-red-600' },
        ].map(c => (
          <div key={c.label} className="bg-white rounded-xl border p-4 text-center">
            <div className="text-xs text-slate-400">{c.label}</div>
            <div className={`text-2xl font-bold mt-1 ${c.color}`}>{c.value}</div>
          </div>
        ))}
      </div>

      {showForm && (
        <div className="bg-white rounded-xl border shadow-sm p-5 space-y-3">
          <h2 className="font-semibold">{editId ? 'IRB 승인 수정' : 'IRB 승인 등록'}</h2>
          {error && <div className="text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</div>}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
            <Field label="프로토콜 번호 *" value={form.protocol_number} onChange={v => setForm({ ...form, protocol_number: v })} disabled={!!editId} />
            <Field label="제목 *" value={form.title} onChange={v => setForm({ ...form, title: v })} />
            <Field label="책임연구자(PI)" value={form.principal_investigator} onChange={v => setForm({ ...form, principal_investigator: v })} />
            <Field label="기관" value={form.institution} onChange={v => setForm({ ...form, institution: v })} />
            <Field label="승인일" type="date" value={form.approved_at} onChange={v => setForm({ ...form, approved_at: v })} />
            <Field label="만료일" type="date" value={form.expires_at} onChange={v => setForm({ ...form, expires_at: v })} />
            {editId && (
              <label className="flex flex-col gap-1">
                <span className="text-slate-500">상태</span>
                <select value={form.status} onChange={e => setForm({ ...form, status: e.target.value })}
                  className="border rounded-lg px-3 py-2">
                  <option value="active">유효</option>
                  <option value="suspended">중단</option>
                </select>
              </label>
            )}
          </div>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-slate-500">범위/메모</span>
            <textarea value={form.scope_note} onChange={e => setForm({ ...form, scope_note: e.target.value })}
              rows={2} className="border rounded-lg px-3 py-2" />
          </label>
          <div className="flex gap-2">
            <button onClick={submit} disabled={busy}
              className="px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 disabled:opacity-50">
              {busy ? '저장 중…' : '저장'}
            </button>
            <button onClick={() => setShowForm(false)} className="px-4 py-2 rounded-xl border text-sm">취소</button>
          </div>
        </div>
      )}

      <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left">프로토콜</th>
                <th className="px-4 py-3 text-left">제목</th>
                <th className="px-4 py-3 text-left">책임연구자</th>
                <th className="px-4 py-3 text-left">승인일</th>
                <th className="px-4 py-3 text-left">만료일</th>
                <th className="px-3 py-3 text-center">상태</th>
                {isAdmin && <th className="px-3 py-3 text-center">관리</th>}
              </tr>
            </thead>
            <tbody>
              {data.items.length === 0 ? (
                <tr><td colSpan={isAdmin ? 7 : 6} className="text-center py-12 text-slate-400">등록된 IRB 승인 없음</td></tr>
              ) : data.items.map(i => {
                const b = statusBadge[i.effective_status] || statusBadge.active;
                const warn = i.days_left !== null && i.days_left >= 0 && i.days_left <= 30;
                return (
                  <tr key={i.id} className="border-t hover:bg-slate-50">
                    <td className="px-4 py-3 font-mono text-xs font-semibold">{i.protocol_number}</td>
                    <td className="px-4 py-3 max-w-[260px] truncate">{i.title}</td>
                    <td className="px-4 py-3 text-slate-600">{i.principal_investigator || '-'}</td>
                    <td className="px-4 py-3 text-slate-500">{i.approved_at || '-'}</td>
                    <td className="px-4 py-3 text-slate-500">
                      {i.expires_at || '-'}
                      {warn && <span className="ml-1 text-[10px] text-amber-600">D-{i.days_left}</span>}
                    </td>
                    <td className="px-3 py-3 text-center">
                      <span className={`text-[11px] font-medium px-2 py-0.5 rounded ${b.cls}`}>{b.label}</span>
                    </td>
                    {isAdmin && (
                      <td className="px-3 py-3 text-center whitespace-nowrap">
                        <button onClick={() => openEdit(i)} className="text-blue-600 hover:underline text-xs mr-2">수정</button>
                        <button onClick={() => remove(i)} className="text-red-500 hover:underline text-xs">삭제</button>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, type = 'text', disabled = false }:
  { label: string; value: string; onChange: (v: string) => void; type?: string; disabled?: boolean }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-slate-500">{label}</span>
      <input type={type} value={value} disabled={disabled} onChange={e => onChange(e.target.value)}
        className="border rounded-lg px-3 py-2 disabled:bg-slate-100" />
    </label>
  );
}
