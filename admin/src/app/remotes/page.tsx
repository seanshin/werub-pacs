'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import Breadcrumb from '@/components/ui/Breadcrumb';

type Remote = {
  id: string; name: string; remote_type: string;
  url: string; ae_title: string; host: string; port: number;
  enabled: boolean; description: string;
  last_echo_at: string; last_echo_status: string;
};

type TransferItem = {
  id: string; direction: string; study_instance_uid: string;
  patient_name: string; modality: string; status: string;
  error_message: string; started_at: string; completed_at: string;
};

type QueryResult = {
  answer_id: string; query_id: string;
  patient_name: string; patient_id: string;
  study_date: string; study_description: string; modality: string;
};

export default function RemotesPage() {
  const [tab, setTab] = useState<'list' | 'query' | 'history'>('list');
  const [remotes, setRemotes] = useState<Remote[]>([]);
  const [history, setHistory] = useState<TransferItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<{ msg: string; type: string } | null>(null);

  // Add/edit form
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', remote_type: 'modality', url: '', username: '', password: '', ae_title: '', host: '', port: 4242, description: '' });
  const [editId, setEditId] = useState<string | null>(null);

  // Query
  const [queryRemote, setQueryRemote] = useState('');
  const [queryParams, setQueryParams] = useState({ patient_name: '', patient_id: '', study_date: '', modality: '' });
  const [queryResults, setQueryResults] = useState<QueryResult[]>([]);
  const [querying, setQuerying] = useState(false);

  useEffect(() => { if (!toast) return; const t = setTimeout(() => setToast(null), 4000); return () => clearTimeout(t); }, [toast]);

  const load = async () => {
    setLoading(true);
    try {
      const [r, h] = await Promise.all([
        apiFetch<{ remotes: Remote[] }>('/api/v1/remotes'),
        apiFetch<{ history: TransferItem[] }>('/api/v1/remotes/transfer-history'),
      ]);
      setRemotes(r.remotes); setHistory(h.history);
    } catch {} finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const saveRemote = async () => {
    try {
      if (editId) {
        await apiFetch(`/api/v1/remotes/${editId}`, { method: 'PUT', body: JSON.stringify(form) });
      } else {
        await apiFetch('/api/v1/remotes', { method: 'POST', body: JSON.stringify(form) });
      }
      setToast({ msg: editId ? '수정 완료' : '등록 완료', type: 'success' });
      setShowForm(false); setEditId(null); load();
    } catch (e: any) { setToast({ msg: e.message, type: 'error' }); }
  };

  const deleteRemote = async (id: string) => {
    if (!confirm('삭제하시겠습니까?')) return;
    try { await apiFetch(`/api/v1/remotes/${id}`, { method: 'DELETE' }); load(); } catch {}
  };

  const echoRemote = async (id: string) => {
    try {
      const res = await apiFetch<any>(`/api/v1/remotes/${id}/echo`, { method: 'POST' });
      setToast({ msg: res.ok ? `연결 성공: ${res.message}` : `연결 실패: ${res.message}`, type: res.ok ? 'success' : 'error' });
      load();
    } catch (e: any) { setToast({ msg: '연결 테스트 실패', type: 'error' }); }
  };

  const runQuery = async () => {
    if (!queryRemote) return;
    setQuerying(true);
    try {
      const params = new URLSearchParams();
      if (queryParams.patient_name) params.set('patient_name', queryParams.patient_name);
      if (queryParams.patient_id) params.set('patient_id', queryParams.patient_id);
      if (queryParams.study_date) params.set('study_date', queryParams.study_date);
      if (queryParams.modality) params.set('modality', queryParams.modality);
      const res = await apiFetch<{ results: QueryResult[]; query_id: string }>(`/api/v1/remotes/${queryRemote}/query?${params}`);
      setQueryResults(res.results || []);
      setToast({ msg: `${res.results?.length || 0}건 검색됨`, type: 'success' });
    } catch (e: any) { setToast({ msg: 'Query 실패: ' + e.message, type: 'error' }); }
    setQuerying(false);
  };

  const retrieve = async (remoteId: string, queryId: string, answerId: string) => {
    try {
      const res = await apiFetch<any>(`/api/v1/remotes/${remoteId}/retrieve?query_id=${queryId}&answer_id=${answerId}`, { method: 'POST' });
      setToast({ msg: res.ok ? '가져오기 완료' : '가져오기 실패', type: res.ok ? 'success' : 'error' });
      load();
    } catch (e: any) { setToast({ msg: '가져오기 실패: ' + e.message, type: 'error' }); }
  };

  return (
    <div className="p-4 sm:p-6 max-w-[1200px] mx-auto">
      {toast && (
        <div className={`fixed top-4 right-4 z-[9999] px-4 py-3 rounded-xl shadow-lg text-sm text-white ${toast.type === 'error' ? 'bg-red-500' : 'bg-green-600'}`}>
          {toast.msg}
        </div>
      )}

      <Breadcrumb items={[{ label: '관리', href: '/' }, { label: '외부 PACS 연동' }]} />
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold mt-1">외부 PACS 연동</h1>
        <button onClick={() => { setShowForm(true); setEditId(null); setForm({ name: '', remote_type: 'modality', url: '', username: '', password: '', ae_title: '', host: '', port: 4242, description: '' }); }}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700">+ 추가</button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 border-b">
        {([['list', '피어/모달리티'], ['query', 'Query/Retrieve'], ['history', '전송 이력']] as const).map(([k, v]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${tab === k ? 'border-indigo-500 text-indigo-700' : 'border-transparent text-gray-500'}`}>{v}</button>
        ))}
      </div>

      {/* List tab */}
      {tab === 'list' && (
        <div className="grid gap-3">
          {remotes.length === 0 && <p className="text-gray-400 text-center py-8">등록된 피어/모달리티 없음</p>}
          {remotes.map(r => (
            <div key={r.id} className="bg-white rounded-xl border p-4 flex items-center gap-4">
              <div className={`w-10 h-10 rounded-full flex items-center justify-center text-lg ${r.remote_type === 'peer' ? 'bg-purple-100' : 'bg-blue-100'}`}>
                {r.remote_type === 'peer' ? '🌐' : '🖥️'}
              </div>
              <div className="flex-1">
                <div className="font-medium">{r.name}</div>
                <div className="text-xs text-gray-500">
                  {r.remote_type === 'peer' ? r.url : `${r.ae_title} @ ${r.host}:${r.port}`}
                </div>
                {r.description && <div className="text-[10px] text-gray-400">{r.description}</div>}
              </div>
              <div className="text-xs text-center">
                {r.last_echo_status === 'ok' ? <span className="text-green-600">● 연결됨</span> :
                 r.last_echo_status === 'failed' ? <span className="text-red-500">● 실패</span> :
                 <span className="text-gray-400">● 미확인</span>}
              </div>
              <div className="flex gap-1">
                <button onClick={() => echoRemote(r.id)} className="px-2 py-1 bg-gray-100 rounded text-xs hover:bg-gray-200">테스트</button>
                <button onClick={() => { setEditId(r.id); setForm({ name: r.name, remote_type: r.remote_type, url: r.url || '', username: '', password: '', ae_title: r.ae_title || '', host: r.host || '', port: r.port || 4242, description: r.description || '' }); setShowForm(true); }}
                  className="px-2 py-1 bg-gray-100 rounded text-xs hover:bg-gray-200">편집</button>
                <button onClick={() => deleteRemote(r.id)} className="px-2 py-1 bg-red-50 text-red-600 rounded text-xs hover:bg-red-100">삭제</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Query tab */}
      {tab === 'query' && (
        <div className="space-y-4">
          <div className="bg-white rounded-xl border p-4 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <select value={queryRemote} onChange={e => setQueryRemote(e.target.value)} className="border rounded-lg px-3 py-2 text-sm col-span-2">
                <option value="">대상 선택...</option>
                {remotes.filter(r => r.remote_type === 'modality').map(r => (
                  <option key={r.id} value={r.id}>{r.name} ({r.ae_title})</option>
                ))}
              </select>
              <input placeholder="환자명" value={queryParams.patient_name} onChange={e => setQueryParams(p => ({ ...p, patient_name: e.target.value }))} className="border rounded-lg px-3 py-2 text-sm" />
              <input placeholder="환자번호" value={queryParams.patient_id} onChange={e => setQueryParams(p => ({ ...p, patient_id: e.target.value }))} className="border rounded-lg px-3 py-2 text-sm" />
              <input placeholder="검사일 (YYYYMMDD)" value={queryParams.study_date} onChange={e => setQueryParams(p => ({ ...p, study_date: e.target.value }))} className="border rounded-lg px-3 py-2 text-sm" />
              <input placeholder="모달리티 (CT, MR...)" value={queryParams.modality} onChange={e => setQueryParams(p => ({ ...p, modality: e.target.value }))} className="border rounded-lg px-3 py-2 text-sm" />
            </div>
            <button onClick={runQuery} disabled={!queryRemote || querying}
              className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm disabled:opacity-50">
              {querying ? '검색 중...' : 'C-FIND 검색'}
            </button>
          </div>

          {queryResults.length > 0 && (
            <div className="bg-white rounded-xl border overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="px-3 py-2 text-left">환자</th>
                    <th className="px-3 py-2 text-left">검사일</th>
                    <th className="px-3 py-2 text-left">설명</th>
                    <th className="px-3 py-2 text-left">모달</th>
                    <th className="px-3 py-2 text-right">액션</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {queryResults.map((r, i) => (
                    <tr key={i} className="hover:bg-gray-50">
                      <td className="px-3 py-2">{r.patient_name}<span className="text-[10px] text-gray-400 ml-1">{r.patient_id}</span></td>
                      <td className="px-3 py-2 text-gray-500">{r.study_date}</td>
                      <td className="px-3 py-2 text-gray-500 text-xs">{r.study_description}</td>
                      <td className="px-3 py-2">{r.modality}</td>
                      <td className="px-3 py-2 text-right">
                        <button onClick={() => retrieve(queryRemote, r.query_id, r.answer_id)}
                          className="px-2 py-1 bg-green-500 text-white rounded text-xs hover:bg-green-600">가져오기</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* History tab */}
      {tab === 'history' && (
        <div className="bg-white rounded-xl border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-3 py-2 text-left">방향</th>
                <th className="px-3 py-2 text-left">환자</th>
                <th className="px-3 py-2 text-left">모달</th>
                <th className="px-3 py-2 text-left">상태</th>
                <th className="px-3 py-2 text-left">일시</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {history.length === 0 && <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">전송 이력 없음</td></tr>}
              {history.map(h => (
                <tr key={h.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${h.direction === 'send' ? 'bg-blue-100 text-blue-700' : 'bg-green-100 text-green-700'}`}>
                      {h.direction === 'send' ? '↑ 전송' : '↓ 수신'}
                    </span>
                  </td>
                  <td className="px-3 py-2">{h.patient_name || h.study_instance_uid?.slice(-12) || '-'}</td>
                  <td className="px-3 py-2 text-gray-500">{h.modality || '-'}</td>
                  <td className="px-3 py-2">
                    <span className={`text-xs ${h.status === 'completed' ? 'text-green-600' : h.status === 'failed' ? 'text-red-500' : 'text-yellow-600'}`}>
                      {h.status === 'completed' ? '완료' : h.status === 'failed' ? '실패' : '진행중'}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-400">{h.started_at?.slice(0, 16).replace('T', ' ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Add/Edit Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center" onClick={() => setShowForm(false)}>
          <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-md" onClick={e => e.stopPropagation()}>
            <h3 className="font-bold text-lg mb-4">{editId ? '피어/모달리티 수정' : '피어/모달리티 등록'}</h3>
            <div className="space-y-3">
              <input placeholder="이름" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} className="w-full border rounded-lg px-3 py-2 text-sm" />
              <select value={form.remote_type} onChange={e => setForm(f => ({ ...f, remote_type: e.target.value }))} className="w-full border rounded-lg px-3 py-2 text-sm">
                <option value="modality">DICOM Modality (DIMSE)</option>
                <option value="peer">Orthanc Peer (HTTP)</option>
              </select>
              {form.remote_type === 'peer' ? (
                <>
                  <input placeholder="URL (https://...)" value={form.url} onChange={e => setForm(f => ({ ...f, url: e.target.value }))} className="w-full border rounded-lg px-3 py-2 text-sm" />
                  <div className="grid grid-cols-2 gap-2">
                    <input placeholder="Username" value={form.username} onChange={e => setForm(f => ({ ...f, username: e.target.value }))} className="border rounded-lg px-3 py-2 text-sm" />
                    <input placeholder="Password" type="password" value={form.password} onChange={e => setForm(f => ({ ...f, password: e.target.value }))} className="border rounded-lg px-3 py-2 text-sm" />
                  </div>
                </>
              ) : (
                <>
                  <input placeholder="AE Title" value={form.ae_title} onChange={e => setForm(f => ({ ...f, ae_title: e.target.value }))} className="w-full border rounded-lg px-3 py-2 text-sm" />
                  <div className="grid grid-cols-3 gap-2">
                    <input placeholder="Host" value={form.host} onChange={e => setForm(f => ({ ...f, host: e.target.value }))} className="col-span-2 border rounded-lg px-3 py-2 text-sm" />
                    <input placeholder="Port" type="number" value={form.port} onChange={e => setForm(f => ({ ...f, port: Number(e.target.value) }))} className="border rounded-lg px-3 py-2 text-sm" />
                  </div>
                </>
              )}
              <input placeholder="설명 (선택)" value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} className="w-full border rounded-lg px-3 py-2 text-sm" />
            </div>
            <div className="flex gap-2 justify-end mt-4">
              <button onClick={() => setShowForm(false)} className="px-4 py-2 border rounded-lg text-sm">취소</button>
              <button onClick={saveRemote} className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm">{editId ? '수정' : '등록'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
