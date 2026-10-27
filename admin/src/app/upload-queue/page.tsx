'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import Breadcrumb from '@/components/ui/Breadcrumb';

type QueueItem = {
  id: string; source: string; source_detail: string;
  patient_id: string; patient_name: string;
  file_count: number; total_size_bytes: number;
  study_uids: string[]; modalities: string[];
  validation_status: string; status: string; reject_reason: string;
  created_at: string; expires_at: string; approved_at: string;
};

const sourceLabel: Record<string, string> = {
  patient_portal: '환자 포털', kiosk: '키오스크', admin: '관리자', remote: '외부 PACS',
};

export default function UploadQueuePage() {
  const [items, setItems] = useState<QueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState('pending');
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<{ msg: string; type: string } | null>(null);
  const [rejectId, setRejectId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState('');

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  const load = async () => {
    setLoading(true);
    try {
      const data = await apiFetch<{ items: QueueItem[]; total: number }>(`/api/v1/upload-queue?status=${filter}`);
      setItems(data.items); setTotal(data.total);
    } catch {} finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [filter]);

  const approve = async (id: string) => {
    try {
      const res = await apiFetch<any>(`/api/v1/upload-queue/${id}/approve`, { method: 'POST' });
      setToast({ msg: `승인 완료: ${res.uploaded}건 Orthanc 저장`, type: 'success' });
      load();
    } catch (e: any) { setToast({ msg: '승인 실패: ' + e.message, type: 'error' }); }
  };

  const reject = async (id: string) => {
    try {
      await apiFetch(`/api/v1/upload-queue/${id}/reject?reason=${encodeURIComponent(rejectReason)}`, { method: 'POST' });
      setToast({ msg: '거부 완료', type: 'info' });
      setRejectId(null); setRejectReason('');
      load();
    } catch (e: any) { setToast({ msg: '거부 실패: ' + e.message, type: 'error' }); }
  };

  return (
    <div className="p-4 sm:p-6 max-w-[1200px] mx-auto">
      {toast && (
        <div className={`fixed top-4 right-4 z-[9999] px-4 py-3 rounded-xl shadow-lg text-sm text-white ${toast.type === 'error' ? 'bg-red-500' : toast.type === 'success' ? 'bg-green-600' : 'bg-blue-600'}`}>
          {toast.msg}
        </div>
      )}

      <Breadcrumb items={[{ label: '관리', href: '/' }, { label: '업로드 승인 큐' }]} />
      <h1 className="text-2xl font-bold mt-1 mb-6">업로드 승인 큐</h1>

      <div className="flex gap-1 mb-4">
        {['pending', 'approved', 'rejected'].map(s => (
          <button key={s} onClick={() => setFilter(s)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium ${filter === s ? 'bg-indigo-600 text-white' : 'bg-gray-100 hover:bg-gray-200'}`}>
            {s === 'pending' ? '대기 중' : s === 'approved' ? '승인됨' : '거부됨'}
          </button>
        ))}
      </div>

      <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-3 py-2.5 text-left">출처</th>
              <th className="px-3 py-2.5 text-left">환자</th>
              <th className="px-3 py-2.5 text-left">파일</th>
              <th className="px-3 py-2.5 text-left hidden md:table-cell">모달리티</th>
              <th className="px-3 py-2.5 text-left hidden lg:table-cell">등록일</th>
              <th className="px-3 py-2.5 text-left hidden lg:table-cell">만료</th>
              <th className="px-3 py-2.5 text-right">액션</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {loading ? (
              <tr><td colSpan={7} className="px-4 py-12 text-center text-gray-400">불러오는 중...</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={7} className="px-4 py-12 text-center text-gray-400">{filter === 'pending' ? '대기 중인 항목 없음' : '항목 없음'}</td></tr>
            ) : items.map(item => (
              <tr key={item.id} className="hover:bg-gray-50">
                <td className="px-3 py-2.5">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                    item.source === 'patient_portal' ? 'bg-purple-100 text-purple-700' :
                    item.source === 'kiosk' ? 'bg-teal-100 text-teal-700' :
                    'bg-gray-100 text-gray-700'}`}>
                    {sourceLabel[item.source] || item.source}
                  </span>
                </td>
                <td className="px-3 py-2.5">
                  <div className="font-medium">{item.patient_name || '-'}</div>
                  <div className="text-[10px] text-gray-400">{item.patient_id || ''}</div>
                </td>
                <td className="px-3 py-2.5 text-gray-600">
                  {item.file_count}건
                  <span className="text-[10px] text-gray-400 ml-1">({(item.total_size_bytes / 1024 / 1024).toFixed(1)}MB)</span>
                </td>
                <td className="px-3 py-2.5 hidden md:table-cell text-xs text-gray-500">{item.modalities?.join(', ') || '-'}</td>
                <td className="px-3 py-2.5 hidden lg:table-cell text-xs text-gray-400">{item.created_at?.slice(0, 16).replace('T', ' ')}</td>
                <td className="px-3 py-2.5 hidden lg:table-cell text-xs text-gray-400">{item.expires_at?.slice(0, 16).replace('T', ' ')}</td>
                <td className="px-3 py-2.5 text-right">
                  {item.status === 'pending' ? (
                    <div className="flex gap-1 justify-end">
                      <button onClick={() => approve(item.id)} className="px-2 py-1 bg-green-500 text-white rounded text-xs hover:bg-green-600">승인</button>
                      <button onClick={() => setRejectId(item.id)} className="px-2 py-1 bg-red-100 text-red-600 rounded text-xs hover:bg-red-200">거부</button>
                    </div>
                  ) : (
                    <span className={`text-[10px] ${item.status === 'approved' ? 'text-green-600' : 'text-red-500'}`}>
                      {item.status === 'approved' ? '승인됨' : `거부: ${item.reject_reason || ''}`}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Reject modal */}
      {rejectId && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center" onClick={() => setRejectId(null)}>
          <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-sm" onClick={e => e.stopPropagation()}>
            <h3 className="font-bold mb-3">업로드 거부</h3>
            <textarea value={rejectReason} onChange={e => setRejectReason(e.target.value)}
              placeholder="거부 사유를 입력하세요..." rows={3}
              className="w-full border rounded-lg p-2 text-sm mb-3" />
            <div className="flex gap-2 justify-end">
              <button onClick={() => setRejectId(null)} className="px-3 py-1.5 border rounded-lg text-sm">취소</button>
              <button onClick={() => reject(rejectId)} className="px-3 py-1.5 bg-red-500 text-white rounded-lg text-sm">거부</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
