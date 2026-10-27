'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch, getUser } from '@/lib/api';

type HISRequest = {
  id: string; request_type: string; accession_number: string | null;
  study_instance_uid: string | null; patient_id: string; patient_name: string | null;
  status: string; payload: any; requested_by: string | null;
  requesting_department: string | null; his_order_id: string | null;
  created_at: string; processed_at: string | null; processed_by: string | null;
};

const TYPE_CONFIG: Record<string, { label: string; icon: string; color: string }> = {
  retake: { label: '재촬영', icon: '🔄', color: 'bg-amber-100 text-amber-700' },
  cancel: { label: '검사 취소', icon: '❌', color: 'bg-red-100 text-red-700' },
  additional_view: { label: '추가 촬영', icon: '📷', color: 'bg-blue-100 text-blue-700' },
  urgent_reading: { label: '긴급 판독', icon: '🚨', color: 'bg-red-100 text-red-700' },
  patient_update: { label: '환자정보 수정', icon: '👤', color: 'bg-slate-100 text-slate-700' },
  clinical_info: { label: '임상정보', icon: '📋', color: 'bg-emerald-100 text-emerald-700' },
  schedule_change: { label: '일정 변경', icon: '📅', color: 'bg-violet-100 text-violet-700' },
};

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  received: { label: '접수', color: 'bg-blue-100 text-blue-700' },
  processing: { label: '처리 중', color: 'bg-amber-100 text-amber-700' },
  completed: { label: '완료', color: 'bg-emerald-100 text-emerald-700' },
  failed: { label: '실패', color: 'bg-red-100 text-red-700' },
};

export default function HISPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [items, setItems] = useState<HISRequest[]>([]);
  const [total, setTotal] = useState(0);
  const [typeFilter, setTypeFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<HISRequest | null>(null);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState('');
  const [actionMsg, setActionMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const PAGE_SIZE = 20;

  useEffect(() => {
    const u = getUser();
    if (!u || !['admin', 'technologist', 'radiologist'].includes(u.role)) { router.replace('/'); return; }
    setUser(u);
    load();
  }, []);

  const load = (type?: string, status?: string) => {
    let url = `/api/v1/his/requests?limit=${PAGE_SIZE}&offset=${(page - 1) * PAGE_SIZE}`;
    if (type) url += `&request_type=${type}`;
    if (status) url += `&status=${status}`;
    if (search) url += `&patient_id=${search}`;
    apiFetch<{ items: HISRequest[]; total: number }>(url)
      .then(d => { setItems(d.items || []); setTotal(d.total || 0); })
      .catch(() => {});

    // Load stats
    apiFetch<{ items: HISRequest[]; total: number }>('/api/v1/his/requests?limit=500')
      .then(d => {
        const s: Record<string, number> = {};
        (d.items || []).forEach(i => { s[i.request_type] = (s[i.request_type] || 0) + 1; });
        setStats(s);
      })
      .catch(() => {});
  };

  useEffect(() => { if (user) load(typeFilter || undefined, statusFilter || undefined); }, [page, typeFilter, statusFilter]);

  const handleSearch = () => { setPage(1); load(typeFilter || undefined, statusFilter || undefined); };

  const runAction = async (kind: 'sync-orders' | 'reconcile-merges') => {
    setBusy(kind); setActionMsg(null);
    try {
      const r = await apiFetch<any>(`/api/v1/his/${kind}`, { method: 'POST' });
      const msg = kind === 'sync-orders'
        ? `오더 동기화 완료 — 조회 ${r.orders_seen}건 / 워크리스트 신규 ${r.worklist_created}건 / 매핑 ${r.mappings_created}건`
        : `병합 재조정 완료 — 병합 ${r.merges_found}건 / 영상 재태깅 ${r.studies_retagged}건 / 매핑 ${r.mappings_updated}건`;
      setActionMsg({ text: msg, ok: true });
      load(typeFilter || undefined, statusFilter || undefined);
    } catch (e: any) {
      setActionMsg({ text: e?.message || '실패', ok: false });
    } finally {
      setBusy('');
    }
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  if (!user) return null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">HIS 연동 관리</h1>
        <p className="text-sm text-slate-500 mt-1">HIS/EMR에서 수신된 요청 이력 조회 및 처리</p>
      </div>

      {/* HospitalRun 동기화 액션 (관리자 전용) */}
      {user.role === 'admin' && (
        <div className="bg-white rounded-xl border shadow-sm p-4">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <h2 className="font-semibold text-slate-800">HospitalRun 동기화</h2>
              <p className="text-xs text-slate-500 mt-0.5">
                IMAGING 오더를 워크리스트로 가져오고(환자번호=MRN 매핑), 병합된 환자의 영상을 통합합니다. 멱등 — 반복 실행 안전.
              </p>
            </div>
            <div className="flex gap-2">
              <button onClick={() => runAction('sync-orders')} disabled={!!busy}
                className="px-4 py-2 bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700 disabled:opacity-50">
                {busy === 'sync-orders' ? '동기화 중…' : '🔄 오더 동기화'}
              </button>
              <button onClick={() => runAction('reconcile-merges')} disabled={!!busy}
                className="px-4 py-2 border border-slate-300 rounded-xl text-sm font-semibold hover:bg-slate-50 disabled:opacity-50">
                {busy === 'reconcile-merges' ? '재조정 중…' : '👥 환자 병합 재조정'}
              </button>
            </div>
          </div>
          {actionMsg && (
            <div className={`mt-3 text-sm rounded-lg px-3 py-2 ${actionMsg.ok ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>
              {actionMsg.text}
            </div>
          )}
        </div>
      )}

      {/* Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        {Object.entries(TYPE_CONFIG).map(([key, cfg]) => (
          <button key={key} onClick={() => { setTypeFilter(typeFilter === key ? '' : key); setPage(1); }}
            className={`rounded-xl border p-3 text-center transition hover:shadow-sm ${typeFilter === key ? 'ring-2 ring-blue-400 border-blue-300' : 'border-slate-200'}`}>
            <div className="text-lg">{cfg.icon}</div>
            <div className="text-xs font-medium text-slate-600 mt-1">{cfg.label}</div>
            <div className="text-lg font-bold text-slate-800">{stats[key] || 0}</div>
          </button>
        ))}
      </div>

      {/* Filters */}
      <div className="flex gap-2 items-center flex-wrap">
        <div className="flex bg-slate-100 rounded-lg p-0.5">
          {[
            { key: '', label: '전체' },
            { key: 'received', label: '접수' },
            { key: 'completed', label: '완료' },
          ].map(f => (
            <button key={f.key} onClick={() => { setStatusFilter(f.key); setPage(1); }}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition ${
                statusFilter === f.key ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'
              }`}>{f.label}</button>
          ))}
        </div>
        <div className="flex-1" />
        <div className="flex gap-2">
          <input type="text" placeholder="환자번호 검색..." value={search}
            onChange={e => setSearch(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
            className="border border-slate-200 rounded-xl px-3 py-1.5 text-sm w-48 focus:border-blue-400 outline-none" />
          <button onClick={handleSearch} className="px-3 py-1.5 bg-blue-600 text-white rounded-xl text-xs font-medium hover:bg-blue-700">검색</button>
        </div>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left">유형</th>
              <th className="px-4 py-3 text-left">상태</th>
              <th className="px-4 py-3 text-left">환자</th>
              <th className="px-4 py-3 text-left">접수번호</th>
              <th className="px-4 py-3 text-left">요청자</th>
              <th className="px-4 py-3 text-left">부서</th>
              <th className="px-4 py-3 text-left">접수일시</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-slate-400">HIS 요청 이력이 없습니다</td></tr>
            )}
            {items.map(item => {
              const tc = TYPE_CONFIG[item.request_type] || { label: item.request_type, icon: '📌', color: 'bg-slate-100 text-slate-600' };
              const sc = STATUS_CONFIG[item.status] || { label: item.status, color: 'bg-slate-100 text-slate-600' };
              return (
                <tr key={item.id} className="border-t hover:bg-slate-50 cursor-pointer" onClick={() => setSelected(item)}>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${tc.color}`}>
                      {tc.icon} {tc.label}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${sc.color}`}>{sc.label}</span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-800">{item.patient_name || '-'}</div>
                    <div className="text-xs text-slate-400">{item.patient_id}</div>
                  </td>
                  <td className="px-4 py-3 text-slate-600 font-mono text-xs">{item.accession_number || '-'}</td>
                  <td className="px-4 py-3 text-slate-600">{item.requested_by || '-'}</td>
                  <td className="px-4 py-3 text-slate-500 text-xs">{item.requesting_department || '-'}</td>
                  <td className="px-4 py-3 text-slate-500 whitespace-nowrap text-xs">
                    {item.created_at ? new Date(item.created_at).toLocaleString('ko-KR') : '-'}
                  </td>
                  <td className="px-4 py-3">
                    <button onClick={e => { e.stopPropagation(); setSelected(item); }}
                      className="text-blue-600 hover:underline text-xs">상세</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-slate-500">총 {total}건</span>
          <div className="flex gap-1">
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
              className="px-3 py-1.5 border rounded-lg hover:bg-slate-50 disabled:opacity-30">← 이전</button>
            <span className="px-3 py-1.5 text-slate-600">{page} / {totalPages}</span>
            <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages}
              className="px-3 py-1.5 border rounded-lg hover:bg-slate-50 disabled:opacity-30">다음 →</button>
          </div>
        </div>
      )}

      {/* Detail Modal */}
      {selected && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={() => setSelected(null)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="px-6 py-4 border-b bg-slate-50 flex items-center justify-between rounded-t-2xl">
              <div className="flex items-center gap-2">
                <span className="text-xl">{TYPE_CONFIG[selected.request_type]?.icon || '📌'}</span>
                <h2 className="font-bold text-lg">{TYPE_CONFIG[selected.request_type]?.label || selected.request_type}</h2>
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_CONFIG[selected.status]?.color || 'bg-slate-100'}`}>
                  {STATUS_CONFIG[selected.status]?.label || selected.status}
                </span>
              </div>
              <button onClick={() => setSelected(null)} className="text-slate-400 hover:text-slate-600 text-xl">&times;</button>
            </div>
            <div className="p-6 space-y-4">
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-xs text-slate-400">환자</span>
                  <p className="font-medium">{selected.patient_name || '-'} ({selected.patient_id})</p>
                </div>
                <div>
                  <span className="text-xs text-slate-400">접수번호</span>
                  <p className="font-mono">{selected.accession_number || '-'}</p>
                </div>
                <div>
                  <span className="text-xs text-slate-400">요청자</span>
                  <p className="font-medium">{selected.requested_by || '-'}</p>
                </div>
                <div>
                  <span className="text-xs text-slate-400">부서</span>
                  <p>{selected.requesting_department || '-'}</p>
                </div>
                <div>
                  <span className="text-xs text-slate-400">접수일시</span>
                  <p>{selected.created_at ? new Date(selected.created_at).toLocaleString('ko-KR') : '-'}</p>
                </div>
                <div>
                  <span className="text-xs text-slate-400">HIS Order ID</span>
                  <p className="font-mono text-xs">{selected.his_order_id || '-'}</p>
                </div>
                {selected.study_instance_uid && (
                  <div className="col-span-2">
                    <span className="text-xs text-slate-400">Study UID</span>
                    <p className="font-mono text-xs break-all">{selected.study_instance_uid}</p>
                  </div>
                )}
              </div>

              {/* Payload */}
              {selected.payload && Object.keys(selected.payload).length > 0 && (
                <div>
                  <span className="text-xs text-slate-400 block mb-2">요청 상세 (Payload)</span>
                  <div className="bg-slate-50 rounded-xl p-4 text-xs font-mono overflow-x-auto max-h-60 overflow-y-auto">
                    {Object.entries(selected.payload).map(([k, v]) => (
                      v ? (
                        <div key={k} className="flex gap-2 py-1 border-b border-slate-100 last:border-0">
                          <span className="text-slate-400 w-40 shrink-0">{k}</span>
                          <span className="text-slate-700 break-all">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
                        </div>
                      ) : null
                    ))}
                  </div>
                </div>
              )}

              {/* Processing info */}
              {selected.processed_at && (
                <div className="bg-emerald-50 rounded-xl p-3 text-sm">
                  <span className="text-emerald-600 font-medium">처리 완료</span>
                  <span className="text-emerald-500 ml-2">{new Date(selected.processed_at).toLocaleString('ko-KR')}</span>
                  {selected.processed_by && <span className="text-emerald-500 ml-2">by {selected.processed_by}</span>}
                </div>
              )}
            </div>
            <div className="px-6 py-4 border-t bg-slate-50 flex justify-end gap-3 rounded-b-2xl">
              {selected.study_instance_uid && (
                <a href={`/pacs-admin/reading/view?study=${selected.study_instance_uid}`}
                  className="px-4 py-2 bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700">판독 화면</a>
              )}
              <button onClick={() => setSelected(null)} className="px-4 py-2 border rounded-xl text-sm font-medium hover:bg-slate-100">닫기</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
