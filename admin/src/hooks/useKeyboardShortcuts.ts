'use client';

import { useEffect } from 'react';

/**
 * Keyboard shortcuts for reading workflow.
 *
 * N = next unread, S = save, Ctrl+Enter = sign, V = open viewer, T = template
 */
export function useKeyboardShortcuts(handlers: {
  onSave?: () => void;
  onSign?: () => void;
  onNextUnread?: () => void;
  onOpenViewer?: () => void;
  onTemplate?: () => void;
}) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger in input/textarea
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') {
        // Only allow Ctrl+Enter in textarea (for sign)
        if (e.ctrlKey && e.key === 'Enter' && handlers.onSign) {
          e.preventDefault();
          handlers.onSign();
        }
        return;
      }

      // Global shortcuts
      switch (e.key.toLowerCase()) {
        case 'n':
          if (!e.ctrlKey && !e.metaKey && handlers.onNextUnread) {
            e.preventDefault();
            handlers.onNextUnread();
          }
          break;
        case 's':
          if (!e.ctrlKey && !e.metaKey && handlers.onSave) {
            e.preventDefault();
            handlers.onSave();
          }
          break;
        case 'v':
          if (!e.ctrlKey && !e.metaKey && handlers.onOpenViewer) {
            e.preventDefault();
            handlers.onOpenViewer();
          }
          break;
        case 't':
          if (!e.ctrlKey && !e.metaKey && handlers.onTemplate) {
            e.preventDefault();
            handlers.onTemplate();
          }
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handlers]);
}
