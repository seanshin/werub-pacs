'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch, getUser } from '@/lib/api';
import { formatDate, formatPatientName } from '@/lib/format';

type RetakeItem = {
  id: string; study_instance_uid: string; reason: string;
  category: string; urgency: string; status: string; notes: string | null;
  requested_by: string; requested_at: string;
  reviewed_by: string | null; reviewed_at: string | null;
  reviewer_notes: string | null; scheduled_at: string | null;
  completed_at: string | null;
  patient_id: string; patient_name: string;
  modality: string; study_description: string;
};

type Stats = { total: number; by_status: Record<string, number>; pending: number; categories_30d: { category: string; count: number }[] };

const STATUS_CONFIG: Record<string, { label: string; bg: string }> = {
  requested: { label: '요청됨', bg: 'bg-amber-100 text-amber-800' },
  approved: { label: '승인됨', bg: 'bg-blue-100 text-blue-800' },
  rejected: { label: '거부됨', bg: 'bg-red-100 text-red-800' },
  scheduled: { label: '스케줄', bg: 'bg-violet-100 text-violet-800' },
  completed: { label: '완료', bg: 'bg-emerald-100 text-emerald-800' },
  cancelled: { label: '취소', bg: 'bg-slate-100 text-slate-600' },
};

const CATEGORY_LABEL: Record<string, string> = {
  quality: '화질 불량', positioning: '위치 오류', motion: '움직임 아티팩트',
  incomplete: '불완전 촬영', other: '기타',
};

const URGENCY_LABEL: Record<string, string> = { routine: '일반', urgent: '긴급', stat: 'STAT' };

export default function RetakePage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [items, setItems] = useState<RetakeItem[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [filter, setFilter] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ study_uid: '', reason: '', category: 'quality', urgency: 'routine', notes: '' });
  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState('');
  const [actionModal, setActionModal] = useState<{ item: RetakeItem; action: string } | null>(null);
  const [actionNotes, setActionNotes] = useState('');

  useEffect(() => {
    const u = getUser();
    if (!u) { router.replace('/'); return; }
    setUser(u);
    load(); loadStats();
  }, []);

  const load = (status?: string) => {
    const url = status ? `/api/v1/retake?status=${status}` : '/api/v1/retake';
    apiFetch<{ items: RetakeItem[] }>(url).then(d => setItems(d.items || [])).catch(() => {});
  };

  const loadStats = () => {
    apiFetch<Stats>('/api/v1/retake/stats').then(d => setStats(d)).catch(() => {});
  };

  const showToastMsg = (msg: string) => { setToast(msg); setTimeout(() => setToast(''), 3000); };

  const handleCreate = async () => {
    if (!form.study_uid || !form.reason) { showToastMsg('Study UID와 사유를 입력하세요'); return; }
    setSubmitting(true);
    try {
      await apiFetch('/api/v1/retake', {
        method: 'POST',
        body: JSON.stringify({ study_instance_uid: form.study_uid, reason: form.reason, category: form.category, urgency: form.urgency, notes: form.notes || null }),
      });
      showToastMsg('재촬영 요청이 등록되었습니다');
      setShowCreate(false);
      setForm({ study_uid: '', reason: '', category: 'quality', urgency: 'routine', notes: '' });
      load(); loadStats();
    } catch (e: any) { showToastMsg(e.message); }
    setSubmitting(false);
  };

  const handleAction = async () => {
    if (!actionModal) return;
    setSubmitting(true);
    try {
      await apiFetch(`/api/v1/retake/${actionModal.item.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: actionModal.action, reviewer_notes: actionNotes || null }),
      });
      showToastMsg(`재촬영 요청이 ${STATUS_CONFIG[actionModal.action]?.label || actionModal.action}되었습니다`);
      setActionModal(null); setActionNotes('');
      load(); loadStats();
    } catch (e: any) { showToastMsg(e.message); }
    setSubmitting(false);
  };

  const handleFilter = (s: string) => { setFilter(s); load(s || undefined); };

  if (!user) return null;

  const canApprove = ['admin', 'technologist'].includes(user.role);
  const canRequest = ['admin', 'radiologist', 'resident', 'physician'].includes(user.role);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">재촬영 요청</h1>
          <p className="text-sm text-slate-500 mt-1">판독의/의사 → 방사선사 재촬영 요청 관리</p>
        </div>
        {canRequest && (
          <button onClick={() => setShowCreate(true)}
            className="px-4 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700 transition">
            + 재촬영 요청
          </button>
        )}
      </div>

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-white rounded-xl border shadow-sm p-4">
            <div className="text-xs text-slate-500">총 요청</div>
            <div className="text-2xl font-bold text-slate-800">{stats.total}</div>
          </div>
          <div className="bg-white rounded-xl border shadow-sm p-4">
            <div className="text-xs text-slate-500">처리 대기</div>
            <div className="text-2xl font-bold text-amber-600">{stats.pending}</div>
          </div>
          <div className="bg-white rounded-xl border shadow-sm p-4">
            <div className="text-xs text-slate-500">완료</div>
            <div className="text-2xl font-bold text-emerald-600">{stats.by_status?.completed || 0}</div>
          </div>
          <div className="bg-white rounded-xl border shadow-sm p-4">
            <div className="text-xs text-slate-500">30일 주요 사유</div>
            <div className="text-sm font-medium text-slate-700 mt-1">
              {stats.categories_30d?.[0]?.category ? CATEGORY_LABEL[stats.categories_30d[0].category] || stats.categories_30d[0].category : '-'}
            </div>
          </div>
        </div>
      )}

      {/* Filter */}
      <div className="flex gap-2">
        {[
          { key: '', label: '전체' },
          { key: 'requested', label: '요청됨' },
          { key: 'approved', label: '승인됨' },
          { key: 'scheduled', label: '스케줄' },
          { key: 'completed', label: '완료' },
          { key: 'rejected', label: '거부' },
        ].map(f => (
          <button key={f.key} onClick={() => handleFilter(f.key)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition ${
              filter === f.key ? 'bg-blue-600 text-white' : 'bg-white border text-slate-600 hover:bg-slate-50'
            }`}>{f.label}</button>
        ))}
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left">상태</th>
              <th className="px-4 py-3 text-left">환자</th>
              <th className="px-4 py-3 text-left">사유</th>
              <th className="px-4 py-3 text-left">카테고리</th>
              <th className="px-4 py-3 text-left">긴급도</th>
              <th className="px-4 py-3 text-left">요청자</th>
              <th className="px-4 py-3 text-left">요청일</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-slate-400">재촬영 요청이 없습니다</td></tr>
            )}
            {items.map(item => (
              <tr key={item.id} className={`border-t hover:bg-slate-50 ${item.urgency === 'stat' ? 'bg-red-50' : ''}`}>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_CONFIG[item.status]?.bg || 'bg-slate-100'}`}>
                    {STATUS_CONFIG[item.status]?.label || item.status}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="font-medium">{formatPatientName(item.patient_name)}</div>
                  <div className="text-xs text-slate-400">{item.patient_id}</div>
                </td>
                <td className="px-4 py-3 max-w-[200px] truncate">{item.reason}</td>
                <td className="px-4 py-3 text-slate-600">{CATEGORY_LABEL[item.category] || item.category}</td>
                <td className="px-4 py-3">
                  <span className={`text-xs font-semibold ${item.urgency === 'stat' ? 'text-red-600' : item.urgency === 'urgent' ? 'text-amber-600' : 'text-slate-500'}`}>
                    {URGENCY_LABEL[item.urgency] || item.urgency}
                  </span>
                </td>
                <td className="px-4 py-3 text-slate-500">{item.requested_by}</td>
                <td className="px-4 py-3 text-slate-500 whitespace-nowrap">
                  {item.requested_at ? new Date(item.requested_at).toLocaleDateString('ko-KR') : '-'}
                </td>
                <td className="px-4 py-3">
                  <div className="flex gap-1 justify-end">
                    {item.status === 'requested' && canApprove && (
                      <>
                        <button onClick={() => setActionModal({ item, action: 'approved' })}
                          className="px-2.5 py-1 bg-emerald-600 text-white rounded text-xs font-medium hover:bg-emerald-700">승인</button>
                        <button onClick={() => setActionModal({ item, action: 'rejected' })}
                          className="px-2.5 py-1 bg-red-500 text-white rounded text-xs font-medium hover:bg-red-600">거부</button>
                      </>
                    )}
                    {item.status === 'approved' && canApprove && (
                      <button onClick={() => setActionModal({ item, action: 'scheduled' })}
                        className="px-2.5 py-1 bg-violet-600 text-white rounded text-xs font-medium hover:bg-violet-700">스케줄</button>
                    )}
                    {item.status === 'scheduled' && canApprove && (
                      <button onClick={() => setActionModal({ item, action: 'completed' })}
                        className="px-2.5 py-1 bg-blue-600 text-white rounded text-xs font-medium hover:bg-blue-700">완료</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Create Modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={() => setShowCreate(false)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg p-6" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-4">재촬영 요청</h2>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-600 block mb-1">Study Instance UID</label>
                <input type="text" className="w-full border rounded-xl px-4 py-2.5 text-sm focus:border-blue-400 outline-none"
                  placeholder="1.2.840..." value={form.study_uid} onChange={e => setForm({ ...form, study_uid: e.target.value })} />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-600 block mb-1">재촬영 사유</label>
                <textarea rows={3} className="w-full border rounded-xl px-4 py-2.5 text-sm focus:border-blue-400 outline-none"
                  placeholder="재촬영이 필요한 이유를 입력하세요" value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-xs font-semibold text-slate-600 block mb-1">카테고리</label>
                  <select className="w-full border rounded-xl px-3 py-2.5 text-sm" value={form.category}
                    onChange={e => setForm({ ...form, category: e.target.value })}>
                    {Object.entries(CATEGORY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-600 block mb-1">긴급도</label>
                  <select className="w-full border rounded-xl px-3 py-2.5 text-sm" value={form.urgency}
                    onChange={e => setForm({ ...form, urgency: e.target.value })}>
                    {Object.entries(URGENCY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-600 block mb-1">비고 (선택)</label>
                <input type="text" className="w-full border rounded-xl px-4 py-2.5 text-sm outline-none"
                  value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setShowCreate(false)} className="px-4 py-2.5 border rounded-xl text-sm font-medium hover:bg-slate-50">취소</button>
              <button onClick={handleCreate} disabled={submitting}
                className="px-6 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700 disabled:opacity-50">
                {submitting ? '등록 중...' : '요청 등록'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Action Modal */}
      {actionModal && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={() => setActionModal(null)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-2">
              재촬영 {STATUS_CONFIG[actionModal.action]?.label}
            </h2>
            <p className="text-sm text-slate-500 mb-4">
              {formatPatientName(actionModal.item.patient_name)} — {actionModal.item.reason}
            </p>
            <div>
              <label className="text-xs font-semibold text-slate-600 block mb-1">코멘트 (선택)</label>
              <textarea rows={3} className="w-full border rounded-xl px-4 py-2.5 text-sm outline-none"
                placeholder="코멘트를 입력하세요..."
                value={actionNotes} onChange={e => setActionNotes(e.target.value)} />
            </div>
            <div className="flex justify-end gap-3 mt-4">
              <button onClick={() => setActionModal(null)} className="px-4 py-2.5 border rounded-xl text-sm font-medium hover:bg-slate-50">취소</button>
              <button onClick={handleAction} disabled={submitting}
                className="px-6 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700 disabled:opacity-50">
                {submitting ? '처리 중...' : '확인'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-slate-900 text-white px-6 py-3 rounded-xl shadow-2xl text-sm font-medium z-50">
          {toast}
        </div>
      )}
    </div>
  );
}
