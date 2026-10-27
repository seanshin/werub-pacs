'use client';

import Link from 'next/link';
import { useEffect, useState, useRef, useCallback } from 'react';
import { apiFetch, getUser } from '@/lib/api';
import { subscribeNotifications } from '@/lib/notificationSocket';

type NotifItem = {
  id: string; type: string; title: string; message: string;
  urgency: string; study_instance_uid: string | null;
  action_url: string | null; is_read: boolean; created_at: string;
};

const URGENCY_DOT: Record<string, string> = {
  critical: 'bg-red-500', urgent: 'bg-amber-500', normal: 'bg-blue-500',
};

const TYPE_ICON: Record<string, string> = {
  sla_warning: '⏱', sla_critical: '🚨', retake_request: '🔄',
  urgent_reading: '🚨', report_ready: '📋', report_signed: '✅',
  ai_critical: '🤖', new_study: '📥', external_consult: '🏥',
};

/* ── B5/B6: Alert sound helpers ── */
const SOUND_URGENT = typeof window !== 'undefined' ? (() => {
  try {
    const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
    return (urgent: boolean) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain); gain.connect(ctx.destination);
      osc.frequency.value = urgent ? 880 : 660;
      gain.gain.value = 0.15;
      osc.start(); osc.stop(ctx.currentTime + (urgent ? 0.3 : 0.15));
      if (urgent) {
        setTimeout(() => {
          const o2 = ctx.createOscillator();
          const g2 = ctx.createGain();
          o2.connect(g2); g2.connect(ctx.destination);
          o2.frequency.value = 880; g2.gain.value = 0.15;
          o2.start(); o2.stop(ctx.currentTime + 0.3);
        }, 400);
      }
    };
  } catch { return () => {}; }
})() : () => {};

/* ── B5: Browser notification helper ── */
function sendBrowserNotification(title: string, body: string, url?: string | null) {
  if (typeof window === 'undefined') return;
  if (Notification.permission !== 'granted') return;
  const n = new Notification(title, {
    body,
    icon: '/pacs-admin/favicon.ico',
    tag: 'pacs-alert',
    requireInteraction: true,
  });
  if (url) n.onclick = () => { window.focus(); window.location.href = url; n.close(); };
  setTimeout(() => n.close(), 15000);
}

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [notifs, setNotifs] = useState<NotifItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const ref = useRef<HTMLDivElement>(null);
  const prevUnreadRef = useRef(0);

  const load = useCallback(() => {
    const user = getUser();
    if (!user) return;
    apiFetch<{ notifications: NotifItem[]; unread: number }>('/api/v1/notifications?limit=20')
      .then(d => { setNotifs(d.notifications || []); setUnread(d.unread || 0); })
      .catch(() => {});
  }, []);

  /* ── B5: Request browser notification permission on mount ── */
  useEffect(() => {
    if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
      Notification.requestPermission();
    }
    // Restore sound preference
    const pref = localStorage.getItem('pacs_sound_enabled');
    if (pref !== null) setSoundEnabled(pref !== 'false');
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(load, 30000);
    return () => clearInterval(iv);
  }, [load]);

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  /* ── B7: 공유 알림 WebSocket 구독 (notificationSocket 싱글턴) ── */
  const handleMessage = useCallback((data: any) => {
    if (data.type === 'notification' || data.event) {
      load();
      // B5: Browser notification for urgent/critical
      const urgency = data.urgency || data.data?.urgency || '';
      const title = data.title || data.data?.title || 'PACS 알림';
      const message = data.message || data.data?.message || '';
      const url = data.action_url || data.data?.action_url;
      const isUrgent = urgency === 'critical' || urgency === 'urgent'
        || data.type === 'urgent_reading' || data.type === 'sla_critical';

      if (isUrgent) {
        sendBrowserNotification(title, message, url);
        if (soundEnabled) SOUND_URGENT(urgency === 'critical');
      } else if (soundEnabled && data.type !== 'ping') {
        SOUND_URGENT(false);
      }
    }
  }, [load, soundEnabled]);

  const handlerRef = useRef(handleMessage);
  handlerRef.current = handleMessage;

  useEffect(() => subscribeNotifications(d => handlerRef.current(d)), []);

  /* ── B6: Play sound when unread count increases (polling fallback) ── */
  useEffect(() => {
    if (unread > prevUnreadRef.current && prevUnreadRef.current >= 0) {
      const latest = notifs.find(n => !n.is_read);
      if (latest) {
        const isUrgent = latest.urgency === 'critical' || latest.urgency === 'urgent';
        if (isUrgent) {
          sendBrowserNotification(latest.title, latest.message, latest.action_url);
        }
        if (soundEnabled) SOUND_URGENT(isUrgent);
      }
    }
    prevUnreadRef.current = unread;
  }, [unread, notifs, soundEnabled]);

  const toggleSound = () => {
    const next = !soundEnabled;
    setSoundEnabled(next);
    localStorage.setItem('pacs_sound_enabled', String(next));
  };

  const markRead = async (id: string) => {
    await apiFetch(`/api/v1/notifications/${id}/read`, { method: 'POST' }).catch(() => {});
    setNotifs(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n));
    setUnread(prev => Math.max(0, prev - 1));
  };

  const markAllRead = async () => {
    await apiFetch('/api/v1/notifications/read-all', { method: 'POST' }).catch(() => {});
    setNotifs(prev => prev.map(n => ({ ...n, is_read: true })));
    setUnread(0);
  };

  const formatTime = (iso: string) => {
    const d = new Date(iso);
    const now = new Date();
    const diff = (now.getTime() - d.getTime()) / 60000;
    if (diff < 1) return '방금';
    if (diff < 60) return `${Math.floor(diff)}분 전`;
    if (diff < 1440) return `${Math.floor(diff / 60)}시간 전`;
    return d.toLocaleDateString('ko-KR', { month: 'short', day: 'numeric' });
  };

  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)}
        className="relative p-1.5 rounded-lg hover:bg-gray-100 transition" title="알림">
        <svg className="w-5 h-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
        </svg>
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 bg-red-500 text-white text-[10px] font-bold rounded-full min-w-[18px] h-[18px] flex items-center justify-center px-1">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-96 bg-white rounded-2xl shadow-2xl border border-slate-200 z-50 overflow-hidden">
          {/* Header */}
          <div className="px-4 py-3 border-b flex items-center justify-between bg-slate-50">
            <div className="flex items-center gap-2">
              <h3 className="font-bold text-sm">알림</h3>
              {unread > 0 && (
                <span className="bg-red-100 text-red-700 text-xs font-bold px-2 py-0.5 rounded-full">{unread}</span>
              )}
            </div>
            <div className="flex items-center gap-3">
              <button onClick={toggleSound} title={soundEnabled ? '알림 소리 끄기' : '알림 소리 켜기'}
                className="text-xs text-slate-500 hover:text-slate-700 transition">
                {soundEnabled ? '🔔' : '🔕'}
              </button>
              {unread > 0 && (
                <button onClick={markAllRead} className="text-xs text-blue-600 hover:underline">모두 읽음</button>
              )}
            </div>
          </div>

          {/* List */}
          <div className="max-h-[400px] overflow-y-auto">
            {notifs.length === 0 ? (
              <div className="px-4 py-12 text-center text-slate-400 text-sm">알림이 없습니다</div>
            ) : (
              notifs.map(n => (
                <div key={n.id}
                  className={`px-4 py-3 border-b border-slate-100 hover:bg-slate-50 cursor-pointer transition ${!n.is_read ? 'bg-blue-50/50' : ''}`}
                  onClick={() => {
                    if (!n.is_read) markRead(n.id);
                    if (n.action_url) { window.location.href = n.action_url; setOpen(false); }
                  }}>
                  <div className="flex items-start gap-3">
                    <div className="flex items-center gap-1.5 shrink-0 mt-0.5">
                      {!n.is_read && <span className={`w-2 h-2 rounded-full ${URGENCY_DOT[n.urgency] || 'bg-blue-500'}`} />}
                      <span className="text-base">{TYPE_ICON[n.type] || '📌'}</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <span className={`text-sm font-medium ${!n.is_read ? 'text-slate-900' : 'text-slate-600'} truncate`}>{n.title}</span>
                        <span className="text-[10px] text-slate-400 shrink-0 ml-2">{formatTime(n.created_at)}</span>
                      </div>
                      <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">{n.message}</p>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Footer */}
          <div className="px-4 py-2.5 border-t bg-slate-50 text-center">
            <Link href="/notifications" className="text-xs text-blue-600 hover:underline font-medium"
              onClick={() => setOpen(false)}>
              전체 알림 보기
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
