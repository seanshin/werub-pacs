'use client';

import { useState, useCallback } from 'react';

export type ToastType = 'success' | 'error' | 'info' | 'warning';

export interface Toast {
  message: string;
  type: ToastType;
}

export function useToast(duration = 3000) {
  const [toast, setToast] = useState<Toast | null>(null);

  const showToast = useCallback((message: string, type: ToastType = 'info') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), duration);
  }, [duration]);

  const toastColor = toast ? {
    success: 'bg-green-100 text-green-800 border-green-300',
    error: 'bg-red-100 text-red-800 border-red-300',
    info: 'bg-blue-100 text-blue-800 border-blue-300',
    warning: 'bg-yellow-100 text-yellow-800 border-yellow-300',
  }[toast.type] : '';

  const ToastUI = toast ? (
    <div className={`fixed top-4 right-4 z-[100] px-4 py-3 rounded-lg border shadow-lg text-sm font-medium ${toastColor}`}>
      {toast.message}
    </div>
  ) : null;

  return { toast, showToast, ToastUI };
}
