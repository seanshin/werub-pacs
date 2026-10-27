'use client';

import { useEffect, useRef } from 'react';
import { subscribeNotifications } from '@/lib/notificationSocket';

/**
 * Hook that refreshes data via WebSocket events with polling fallback.
 * Replaces setInterval polling with instant WebSocket-triggered refreshes.
 *
 * 공유 알림 소켓(notificationSocket 싱글턴)을 구독 — NotificationBell과
 * 같은 연결을 재사용하므로 페이지당 WebSocket은 1개만 열린다.
 *
 * @param onRefresh - callback to reload data
 * @param pollingMs - fallback polling interval (default 30s)
 * @param events - WebSocket event types to listen for (default: all)
 */
export function useRealtimeRefresh(
  onRefresh: () => void,
  pollingMs = 30000,
  events?: string[],
) {
  const refreshRef = useRef(onRefresh);
  refreshRef.current = onRefresh;
  const eventsRef = useRef(events);
  eventsRef.current = events;

  useEffect(() => {
    // Initial load
    refreshRef.current();

    // 공유 WebSocket 구독
    const unsubscribe = subscribeNotifications((data) => {
      const eventType = data.type || data.event || '';
      if (eventType === 'ping') return;
      const filter = eventsRef.current;
      if (!filter || filter.length === 0 || filter.includes(eventType)) {
        refreshRef.current();
      }
    });

    // Polling fallback
    const iv = setInterval(() => refreshRef.current(), pollingMs);

    return () => {
      clearInterval(iv);
      unsubscribe();
    };
  }, [pollingMs]);
}
