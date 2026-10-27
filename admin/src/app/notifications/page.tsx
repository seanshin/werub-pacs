'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { apiFetch, getUser } from '@/lib/api';
import { useRealtimeRefresh } from '@/hooks/useRealtimeRefresh';
import Breadcrumb from '@/components/ui/Breadcrumb';
import Pagination from '@/components/ui/Pagination';

type NotifItem = {
  id: string; type: string; title: string; message: string;
  urgency: string; study_instance_uid: string | null; patient_id: string | null;
  action_url: string | null; is_read: boolean; acknowledged: boolean; created_at: string;
};

const PAGE_SIZE = 20;

const URGENCY_BADGE: Record<string, { label: string; cls: string }> = {
  critical: { label: '긴급', cls: 'bg-red-100 text-red-700' },
  urgent: { label: '주의', cls: 'bg-amber-100 text-amber-700' },
  normal: { label: '일반', cls: 'bg-blue-100 text-blue-700' },
};

const TYPE_ICON: Record<string, string> = {
  sla_warning: '⏱', sla_critical: '🚨', retake_request: '🔄',
  urgent_reading: '🚨', report_ready: '📋', report_signed: '✅',
  ai_critical: '🤖', new_study: '📥', external_consult: '🏥',
};

export default function NotificationsPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [items, setItems] = useState<NotifItem[]>([]);
  const [total, setTotal] = useState(0);
  const [unread, setUnread] = useState(0);
  const [page, setPage] = useState(1);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [urgency, setUrgency] = useState('');
  const [busy, setBusy] = useState('');

  useEffect(() => {
    const u = getUser();
    if (!u) { router.replace('/'); return; }
    setUser(u);
  }, []);

  const load = useCallback(() => {
    if (!getUser()) return;
    let url = `/api/v1/notifications?limit=${PAGE_SIZE}&offset=${(page - 1) * PAGE_SIZE}`;
    if (unreadOnly) url += '&unread_only=true';
    if (urgency) url += `&urgency=${urgency}`;
    apiFetch<{ notifications: NotifItem[]; total: number; unread: number }>(url)
      .then(d => { setItems(d.notifications || []); setTotal(d.total || 0); setUnread(d.unread || 0); })
      .catch(() => {});
  }, [page, unreadOnly, urgency]);

  useEffect(() => { if (user) load(); }, [user, load]);
  useRealtimeRefresh(load, 60000, ['notification', 'urgent_reading', 'sla_critical', 'new_study']);

  const markRead = async (id: string) => {
    setBusy(id);
    await apiFetch(`/api/v1/notifications/${id}/read`, { method: 'POST' }).catch(() => {});
    setBusy('');
    load();
  };

  const acknowledgeNotif = async (id: string) => {
    setBusy(id);
    await apiFetch(`/api/v1/notifications/${id}/acknowledge`, { method: 'POST' }).catch(() => {});
    setBusy('');
    load();
  };

  const markAllRead = async () => {
    setBusy('all');
    await apiFetch('/api/v1/notifications/read-all', { method: 'POST' }).catch(() => {});
    setBusy('');
    load();
  };

  const formatTime = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleString('ko-KR', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  if (!user) return null;

  return (
    <div className="space-y-4">
      <Breadcrumb items={[{ label: '알림' }]} />

      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold">알림</h1>
          <p className="text-sm text-slate-500 mt-1">전체 알림 이력 — 미읽음 {unread.toLocaleString()}건</p>
        </div>
        {unread > 0 && (
          <button onClick={markAllRead} disabled={busy === 'all'}
            className="px-4 py-2 bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700 disabled:opacity-50">
            모두 읽음 처리
          </button>
        )}
      </div>

      {/* 필터 */}
      <div className="flex gap-2 items-center flex-wrap">
        <div className="flex bg-slate-100 rounded-lg p-0.5">
          {[{ v: false, l: '전체' }, { v: true, l: '안 읽음' }].map(f => (
            <button key={f.l} onClick={() => { setUnreadOnly(f.v); setPage(1); }}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition ${unreadOnly === f.v ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'}`}>{f.l}</button>
          ))}
        </div>
        <div className="flex bg-slate-100 rounded-lg p-0.5">
          {[{ v: '', l: '전체 긴급도' }, { v: 'critical', l: '긴급' }, { v: 'urgent', l: '주의' }, { v: 'normal', l: '일반' }].map(f => (
            <button key={f.v} onClick={() => { setUrgency(f.v); setPage(1); }}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition ${urgency === f.v ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'}`}>{f.l}</button>
          ))}
        </div>
        <div className="flex-1" />
        <span className="text-xs text-slate-400">{total.toLocaleString()}건</span>
      </div>

      {/* 목록 */}
      <div className="bg-white rounded-xl border shadow-sm divide-y divide-slate-100">
        {items.length === 0 && (
          <div className="px-4 py-16 text-center text-slate-400 text-sm">알림이 없습니다</div>
        )}
        {items.map(n => (
          <div key={n.id} className={`px-4 py-3 flex items-start gap-3 ${!n.is_read ? 'bg-blue-50/50' : ''}`}>
            <span className="text-lg mt-0.5 shrink-0">{TYPE_ICON[n.type] || '📌'}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-sm font-medium ${!n.is_read ? 'text-slate-900' : 'text-slate-600'}`}>{n.title}</span>
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${URGENCY_BADGE[n.urgency]?.cls || 'bg-slate-100 text-slate-500'}`}>
                  {URGENCY_BADGE[n.urgency]?.label || n.urgency}
                </span>
                {n.acknowledged && <span className="text-[10px] text-emerald-600 font-medium">✓ 확인됨</span>}
              </div>
              <p className="text-xs text-slate-500 mt-0.5">{n.message}</p>
              <div className="text-[11px] text-slate-400 mt-1 flex items-center gap-3">
                <span>{formatTime(n.created_at)}</span>
                {n.patient_id && <span>환자 {n.patient_id}</span>}
              </div>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              {n.action_url && (
                <Link href={n.action_url.replace(/^\/pacs-admin/, '') || '/'}
                  className="text-xs px-2 py-1 bg-slate-800 text-white rounded-lg hover:bg-slate-900">바로가기</Link>
              )}
              {!n.is_read && (
                <button onClick={() => markRead(n.id)} disabled={busy === n.id}
                  className="text-xs px-2 py-1 border rounded-lg hover:bg-slate-100 disabled:opacity-40">읽음</button>
              )}
              {n.urgency === 'critical' && !n.acknowledged && (
                <button onClick={() => acknowledgeNotif(n.id)} disabled={busy === n.id}
                  className="text-xs px-2 py-1 border border-red-200 text-red-600 rounded-lg hover:bg-red-50 disabled:opacity-40">확인</button>
              )}
            </div>
          </div>
        ))}
      </div>

      <Pagination page={page} totalPages={Math.max(1, Math.ceil(total / PAGE_SIZE))}
        total={total} pageSize={PAGE_SIZE} onPageChange={setPage} />
    </div>
  );
}
