'use client';

import { useEffect, useState, useCallback } from 'react';
import { getUser, login } from '@/lib/api';
import { useRealtimeRefresh } from '@/hooks/useRealtimeRefresh';
import { formatPatientName, ModalityBadge } from '@/lib/format';
import ViewerButton from '@/components/ViewerButton';

const API_BASE = '/pacs-api';

// Non-redirecting fetch — returns null on 401 instead of redirect
async function erFetch<T>(path: string): Promise<T | null> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('pacs_token') : null;
  if (!token) return null;
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 401) return null;
  if (!res.ok) return null;
  return res.json();
}

type BoardItem = {
  study_uid: string; patient_name: string; patient_id: string;
  modality: string; study_description: string; study_date: string;
  study_time: string; read_status: string; urgency: string;
  wait_minutes: number | null; impression: string | null;
  reader: string | null; signed_at: string | null; viewer_url: string;
};

function ERLogin({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try { await login(username, password); onLogin(); } catch (err: any) { setError(err.message); }
  };

  return (
    <div className="min-h-screen bg-gray-900 flex items-center justify-center">
      <form onSubmit={handleSubmit} className="bg-gray-800 p-8 rounded-2xl shadow-xl w-full max-w-sm space-y-4">
        <div className="text-center">
          <div className="text-3xl font-bold text-red-500 mb-1">ER Board</div>
          <div className="text-sm text-gray-400">응급 영상 보드 로그인</div>
        </div>
        <input type="text" value={username} onChange={e => setUsername(e.target.value)}
          className="w-full border border-gray-600 rounded-lg px-4 py-2.5 bg-gray-700 text-white focus:ring-2 focus:ring-red-500 outline-none" placeholder="사용자명" />
        <input type="password" value={password} onChange={e => setPassword(e.target.value)}
          className="w-full border border-gray-600 rounded-lg px-4 py-2.5 bg-gray-700 text-white focus:ring-2 focus:ring-red-500 outline-none" placeholder="비밀번호" />
        {error && <p className="text-red-400 text-sm">{error}</p>}
        <button type="submit" className="w-full bg-red-600 text-white py-2.5 rounded-lg font-semibold hover:bg-red-700 transition">로그인</button>
      </form>
      <div className="mt-4 bg-gray-800/50 border border-gray-700 rounded-xl p-4 text-sm text-gray-400 w-full max-w-sm">
        <p className="font-semibold text-gray-300 mb-2">테스트 계정</p>
        <div className="space-y-1">
          {[
            { label: '응급실', user: 'er.doctor', pw: '' },
            { label: '관리자', user: 'admin', pw: '' },
            { label: '판독의', user: 'dr.kim', pw: '' },
            { label: '방사선사', user: 'tech.park', pw: '' },
            { label: '주치의', user: 'dr.lee', pw: '' },
          ].map(a => (
            <button key={a.user} type="button" onClick={() => { setUsername(a.user); setPassword(a.pw); }}
              className="w-full flex justify-between hover:bg-gray-700/50 rounded-lg px-3 py-1.5 transition">
              <span>{a.label}</span><span className="font-mono text-xs text-gray-500">{a.user}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function EmergencyPage() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [board, setBoard] = useState<BoardItem[]>([]);
  const [urgentCount, setUrgentCount] = useState(0);
  const [pendingCount, setPendingCount] = useState(0);
  const [filter, setFilter] = useState<'all' | 'urgent' | 'pending' | 'done'>('all');

  const load = async () => {
    const d = await erFetch<{ board: BoardItem[]; urgent_count: number; pending_count: number }>('/api/v1/emergency/board');
    if (!d) { setAuthed(false); return; }
    setAuthed(true);
    setBoard(d.board); setUrgentCount(d.urgent_count); setPendingCount(d.pending_count);
  };

  useRealtimeRefresh(load, 15000, ['notification', 'urgent_reading', 'new_study', 'sla_critical']);

  if (authed === null) return <div className="min-h-screen bg-gray-900 flex items-center justify-center text-gray-500">로딩 중...</div>;
  if (authed === false) return <ERLogin onLogin={load} />;

  const filtered = board.filter(b => {
    if (filter === 'urgent') return b.urgency === 'urgent' || b.urgency === 'stat';
    if (filter === 'pending') return b.read_status === 'unread';
    if (filter === 'done') return b.read_status === 'final' || b.read_status === 'preliminary';
    return true;
  });

  const formatWait = (min: number | null) => {
    if (min === null) return '-';
    if (min < 60) return `${min}분`;
    const h = Math.floor(min / 60);
    return `${h}시간 ${min % 60}분`;
  };

  const waitColor = (min: number | null, status: string) => {
    if (status !== 'unread' || min === null) return '';
    if (min >= 60) return 'text-red-600 font-bold animate-pulse';
    if (min >= 30) return 'text-orange-500 font-semibold';
    return 'text-gray-500';
  };

  const statusConfig: Record<string, { label: string; bg: string }> = {
    unread: { label: '대기', bg: 'bg-yellow-100 text-yellow-800' },
    draft: { label: '작성중', bg: 'bg-blue-100 text-blue-800' },
    preliminary: { label: '예비', bg: 'bg-purple-100 text-purple-800' },
    final: { label: '완료', bg: 'bg-green-100 text-green-800' },
  };

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold">응급 영상 보드</h1>
          <span className="text-xs text-gray-400">15초 자동 갱신</span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          {urgentCount > 0 && (
            <span className="bg-red-100 text-red-800 px-2 py-0.5 rounded font-bold animate-pulse">
              STAT {urgentCount}
            </span>
          )}
          <span className="bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded font-medium">대기 {pendingCount}</span>
          <span className="text-gray-500">전체 {board.length}</span>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2 mb-4">
        {[
          { key: 'all' as const, label: '전체' },
          { key: 'urgent' as const, label: 'STAT/긴급' },
          { key: 'pending' as const, label: '판독 대기' },
          { key: 'done' as const, label: '판독 완료' },
        ].map(f => (
          <button key={f.key} onClick={() => setFilter(f.key)}
            className={`px-3 py-1.5 rounded text-sm font-medium transition ${
              filter === f.key ? 'bg-red-600 text-white' : 'bg-white border text-gray-600 hover:bg-gray-50'
            }`}>
            {f.label}
          </button>
        ))}
      </div>

      {/* Board */}
      <div className="space-y-2">
        {filtered.map((item, i) => (
          <div key={i}
            className={`bg-white rounded-lg border shadow-sm p-3 flex items-center gap-4 hover:shadow-md transition
              ${item.urgency === 'urgent' || item.urgency === 'stat' ? 'border-red-300 bg-red-50/50' : ''}
              ${item.read_status === 'unread' && (item.wait_minutes || 0) >= 60 ? 'border-red-400' : ''}`}>

            {/* Status + urgency */}
            <div className="flex flex-col items-center gap-1 w-16 shrink-0">
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusConfig[item.read_status]?.bg || 'bg-gray-100'}`}>
                {statusConfig[item.read_status]?.label || item.read_status}
              </span>
              {(item.urgency === 'urgent' || item.urgency === 'stat') && (
                <span className="text-red-600 font-bold text-xs animate-pulse">STAT</span>
              )}
            </div>

            {/* Patient info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-semibold truncate">{formatPatientName(item.patient_name) || item.patient_id}</span>
                <ModalityBadge modality={item.modality} />
                <span className="text-xs text-gray-400 truncate">{item.study_description || ''}</span>
              </div>
              {item.read_status === 'final' && item.impression && (
                <div className="text-sm text-green-700 mt-1 truncate">
                  {item.impression}
                </div>
              )}
              {item.read_status === 'preliminary' && item.impression && (
                <div className="text-sm text-purple-600 mt-1 truncate">
                  [예비] {item.impression}
                </div>
              )}
            </div>

            {/* Wait time */}
            <div className={`text-sm w-20 text-right shrink-0 ${waitColor(item.wait_minutes, item.read_status)}`}>
              {item.read_status === 'unread' ? formatWait(item.wait_minutes) : ''}
            </div>

            {/* Reader */}
            <div className="text-xs text-gray-400 w-20 text-right shrink-0 truncate">
              {item.reader || ''}
            </div>

            {/* Action */}
            <ViewerButton url={item.viewer_url} modality={item.modality} />
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="text-center py-16 text-gray-400">해당 조건의 검사가 없습니다</div>
        )}
      </div>
    </div>
  );
}

