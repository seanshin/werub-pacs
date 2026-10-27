'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

type Item = {
  id: string; kind: string; label: string; status: string;
  reason?: string; question?: string;
  requested_by_name?: string; requester?: string;
  physician_name?: string; institution_name?: string;
  urgency?: string; portal_url?: string;
  requested_at?: string; responded_at?: string;
  external_findings?: string; external_impression?: string;
  response?: string; agreement?: string; comment?: string;
  external_email?: string;
};

export default function ConsultsPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [filter, setFilter] = useState('');
  const [kindFilter, setKindFilter] = useState('');
  const [detail, setDetail] = useState<Item | null>(null);
  const [respondData, setRespondData] = useState({ findings: '', impression: '' });

  const load = () => {
    // Load all 3 types via consult-history with a dummy call, or load separately
    Promise.all([
      apiFetch<{ consults: any[] }>(`/api/v1/external-consult${filter ? `?status=${filter}` : ''}`).catch(() => ({ consults: [] })),
      apiFetch<{ requests: any[] }>(`/api/v1/conferences/second-opinion/all${filter ? `?status=${filter}` : ''}`).catch(() => ({ requests: [] })),
      apiFetch<{ pending: any[] }>('/api/v1/peer-review/pending').catch(() => ({ pending: [] })),
    ]).then(([ec, so, pr]) => {
      const all: Item[] = [];
      (ec.consults || []).forEach((c: any) => all.push({ ...c, kind: 'external_consult', label: '외부 판독', reason: c.reason }));
      (so.requests || []).forEach((s: any) => all.push({ ...s, kind: 'second_opinion', label: '세컨드 오피니언', reason: s.question, requested_by_name: s.requester, requested_at: s.created_at }));
      (pr.pending || []).forEach((p: any) => all.push({ ...p, kind: 'peer_review', label: '피어 리뷰', physician_name: p.reviewer, requested_by_name: p.original_reader, requested_at: p.assigned_at }));
      all.sort((a, b) => (b.requested_at || '').localeCompare(a.requested_at || ''));
      setItems(all);
    });
  };

  useEffect(() => { load(); }, [filter]);

  const filtered = kindFilter ? items.filter(i => i.kind === kindFilter) : items;

  const statusBadge: Record<string, string> = {
    requested: 'bg-yellow-100 text-yellow-800', pending: 'bg-yellow-100 text-yellow-800',
    in_progress: 'bg-blue-100 text-blue-800', completed: 'bg-green-100 text-green-800',
    cancelled: 'bg-gray-100 text-gray-500',
  };
  const kindBadge: Record<string, string> = {
    external_consult: 'bg-red-100 text-red-700', second_opinion: 'bg-purple-100 text-purple-700',
    peer_review: 'bg-blue-100 text-blue-700',
  };

  const counts = {
    total: items.length,
    pending: items.filter(i => i.status === 'pending' || i.status === 'requested').length,
    completed: items.filter(i => i.status === 'completed').length,
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">협진 관리</h1>
        <div className="flex items-center gap-2 text-sm">
          {counts.pending > 0 && <span className="bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded font-medium">대기 {counts.pending}</span>}
          <span className="text-gray-500">전체 {counts.total}건</span>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        <button onClick={() => { setFilter(''); setKindFilter(''); }}
          className={`bg-white border rounded-lg p-3 text-center hover:border-blue-400 transition ${!filter && !kindFilter ? 'border-blue-500' : ''}`}>
          <div className="text-xs text-gray-500">전체</div>
          <div className="text-2xl font-bold">{counts.total}</div>
        </button>
        <button onClick={() => setKindFilter(kindFilter === 'external_consult' ? '' : 'external_consult')}
          className={`bg-white border rounded-lg p-3 text-center hover:border-red-400 transition ${kindFilter === 'external_consult' ? 'border-red-500' : ''}`}>
          <div className="text-xs text-gray-500">외부 판독</div>
          <div className="text-2xl font-bold text-red-600">{items.filter(i => i.kind === 'external_consult').length}</div>
        </button>
        <button onClick={() => setKindFilter(kindFilter === 'second_opinion' ? '' : 'second_opinion')}
          className={`bg-white border rounded-lg p-3 text-center hover:border-purple-400 transition ${kindFilter === 'second_opinion' ? 'border-purple-500' : ''}`}>
          <div className="text-xs text-gray-500">세컨드 오피니언</div>
          <div className="text-2xl font-bold text-purple-600">{items.filter(i => i.kind === 'second_opinion').length}</div>
        </button>
        <button onClick={() => setKindFilter(kindFilter === 'peer_review' ? '' : 'peer_review')}
          className={`bg-white border rounded-lg p-3 text-center hover:border-blue-400 transition ${kindFilter === 'peer_review' ? 'border-blue-500' : ''}`}>
          <div className="text-xs text-gray-500">피어 리뷰</div>
          <div className="text-2xl font-bold text-blue-600">{items.filter(i => i.kind === 'peer_review').length}</div>
        </button>
      </div>

      {/* Status Filter */}
      <div className="flex gap-2 mb-4">
        {[{ key: '', label: '전체' }, { key: 'requested', label: '대기' }, { key: 'completed', label: '완료' }].map(f => (
          <button key={f.key} onClick={() => setFilter(f.key)}
            className={`px-3 py-1.5 rounded text-sm font-medium transition ${filter === f.key ? 'bg-primary text-white' : 'bg-white border text-gray-600 hover:bg-gray-50'}`}>
            {f.label}
          </button>
        ))}
      </div>

      {/* List */}
      <div className="space-y-2">
        {filtered.length === 0 && <div className="text-center py-16 text-gray-400">협진 이력이 없습니다</div>}
        {filtered.map(item => (
          <div key={`${item.kind}-${item.id}`}
            className={`bg-white rounded-lg border shadow-sm p-4 hover:shadow-md transition cursor-pointer ${item.status === 'requested' || item.status === 'pending' ? 'border-l-4 border-l-yellow-400' : item.status === 'completed' ? 'border-l-4 border-l-green-400' : ''}`}
            onClick={() => setDetail(item)}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${kindBadge[item.kind] || 'bg-gray-100'}`}>{item.label}</span>
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusBadge[item.status] || 'bg-gray-100'}`}>
                  {item.status === 'completed' ? '완료' : item.status === 'cancelled' ? '취소' : '대기'}
                </span>
                {item.urgency === 'stat' && <span className="text-red-600 font-bold text-xs animate-pulse">STAT</span>}
                {item.urgency === 'urgent' && <span className="text-orange-500 font-semibold text-xs">긴급</span>}
              </div>
              <span className="text-xs text-gray-400">{item.requested_at ? new Date(item.requested_at).toLocaleDateString('ko-KR') : ''}</span>
            </div>
            <div className="mt-2 flex items-center gap-4 text-sm">
              {item.institution_name && <span className="text-gray-700 font-medium">{item.institution_name}</span>}
              {item.physician_name && <span className="text-gray-500">{item.physician_name}</span>}
              {item.requested_by_name && <span className="text-gray-400 text-xs">의뢰자: {item.requested_by_name}</span>}
            </div>
            {item.reason && <div className="mt-1 text-sm text-gray-600 line-clamp-1">{item.reason}</div>}
            {item.status === 'completed' && (item.external_findings || item.response || item.agreement) && (
              <div className="mt-2 bg-green-50 rounded p-2 text-xs text-green-800 line-clamp-2">
                {item.external_findings || item.response || `결과: ${item.agreement}`}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Detail Modal */}
      {detail && (
        <div className="fixed inset-0 bg-black/50 z-40 flex items-center justify-center" onClick={() => setDetail(null)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg p-6 max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${kindBadge[detail.kind] || ''}`}>{detail.label}</span>
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusBadge[detail.status] || ''}`}>
                  {detail.status === 'completed' ? '완료' : '대기'}
                </span>
              </div>
              <button onClick={() => setDetail(null)} className="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
            </div>
            <div className="space-y-3 text-sm">
              {detail.institution_name && <div><span className="text-gray-500">기관:</span> <strong>{detail.institution_name}</strong></div>}
              {detail.physician_name && <div><span className="text-gray-500">판독의:</span> {detail.physician_name}</div>}
              {detail.requested_by_name && <div><span className="text-gray-500">의뢰자:</span> {detail.requested_by_name}</div>}
              {detail.reason && <div><span className="text-gray-500">사유:</span><div className="bg-gray-50 rounded p-3 mt-1">{detail.reason}</div></div>}
              {detail.portal_url && detail.status !== 'completed' && (
                <div>
                  <span className="text-gray-500">포털 링크:</span>
                  <div className="flex items-center gap-2 mt-1">
                    <code className="text-xs bg-gray-100 px-2 py-1 rounded flex-1 truncate">{window.location.origin}{detail.portal_url}</code>
                    <button onClick={() => navigator.clipboard.writeText(window.location.origin + (detail.portal_url || ''))}
                      className="px-2 py-1 bg-blue-600 text-white rounded text-xs">복사</button>
                  </div>
                </div>
              )}
              {detail.status === 'completed' && (
                <div>
                  <span className="text-gray-500">결과:</span>
                  <div className="bg-green-50 border border-green-200 rounded-lg p-3 mt-1 whitespace-pre-wrap">
                    {detail.external_findings || detail.response || (detail.agreement ? `동의: ${detail.agreement}\n${detail.comment || ''}` : '-')}
                  </div>
                  {detail.external_impression && <div className="bg-green-50 border border-green-200 rounded-lg p-3 mt-2">{detail.external_impression}</div>}
                </div>
              )}
              {detail.kind === 'external_consult' && detail.status === 'requested' && (
                <div className="pt-2">
                  <h4 className="font-semibold text-gray-700 mb-2">결과 입력</h4>
                  <textarea rows={3} placeholder="외부 판독 소견..." className="w-full border rounded-lg px-3 py-2 text-sm"
                    value={respondData.findings} onChange={e => setRespondData({...respondData, findings: e.target.value})} />
                  <textarea rows={2} placeholder="결론..." className="w-full border rounded-lg px-3 py-2 text-sm mt-2"
                    value={respondData.impression} onChange={e => setRespondData({...respondData, impression: e.target.value})} />
                  <button onClick={async () => {
                    await apiFetch(`/api/v1/external-consult/${detail.id}/respond`, {
                      method: 'PUT', body: JSON.stringify({ external_findings: respondData.findings, external_impression: respondData.impression }),
                    });
                    setDetail(null); setRespondData({ findings: '', impression: '' }); load();
                  }} className="mt-2 px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-semibold hover:bg-green-700">결과 저장</button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
