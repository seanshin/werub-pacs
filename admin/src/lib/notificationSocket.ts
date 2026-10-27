'use client';

/**
 * 공유 알림 WebSocket 싱글턴.
 *
 * NotificationBell(상시)과 useRealtimeRefresh(판독/응급 등)가 각자
 * /pacs-api/ws/notifications 연결을 만들던 것을 페이지당 1연결로 통합.
 * 구독자가 있는 동안만 연결을 유지하고, 끊기면 5초 후 자동 재연결한다.
 */

type Listener = (data: any) => void;

let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
const listeners = new Set<Listener>();

function connect() {
  if (typeof window === 'undefined') return;
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  try {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const token = localStorage.getItem('pacs_token') || '';
    const socket = new WebSocket(`${proto}//${location.host}/pacs-api/ws/notifications?token=${token}`);

    socket.onopen = () => {
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    };

    socket.onmessage = (e) => {
      let data: any;
      try { data = JSON.parse(e.data); } catch { return; }
      listeners.forEach(l => { try { l(data); } catch {} });
    };

    socket.onclose = () => {
      ws = null;
      if (listeners.size > 0 && !reconnectTimer) {
        reconnectTimer = setTimeout(() => { reconnectTimer = null; connect(); }, 5000);
      }
    };
    socket.onerror = () => { socket.close(); };

    ws = socket;
  } catch {}
}

/** 알림 메시지 구독. 반환된 함수로 해제 — 마지막 구독자가 빠지면 연결을 닫는다. */
export function subscribeNotifications(listener: Listener): () => void {
  listeners.add(listener);
  connect();
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
      ws?.close();
      ws = null;
    }
  };
}
