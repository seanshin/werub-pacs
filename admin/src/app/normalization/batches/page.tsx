'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { apiFetch, getUser } from '@/lib/api';
import { BatchStatusBadge } from '@/components/normalization/BatchStatusBadge';
import type { BatchJob } from '../types';

type BatchListState = {
  loading: boolean;
  error: string | null;
  batches: BatchJob[];
  page: number;
  totalPages: number;
  statusFilter: 'all' | 'queued' | 'processing' | 'completed' | 'failed';
  dateRange: '7d' | '30d' | '90d';
  toast: { message: string; type: 'error' | 'success' } | null;
};

export default function BatchListPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [state, setState] = useState<BatchListState>({
    loading: true,
    error: null,
    batches: [],
    page: 1,
    totalPages: 1,
    statusFilter: 'all',
    dateRange: '7d',
    toast: null,
  });

  // Auth guard + initial fetch
  useEffect(() => {
    const u = getUser();
    if (!u || !['admin', 'technologist'].includes(u.role)) {
      router.replace('/');
      return;
    }
    setUser(u);
    fetchBatches(1, 'all', '7d');
  }, [router]);

  // Auto-refresh when batches are processing
  useEffect(() => {
    const hasProcessing = state.batches.some(
      b => b.status === 'processing' || b.status === 'queued'
    );
    if (!hasProcessing) return;

    const id = setInterval(() => {
      fetchBatches(state.page, state.statusFilter, state.dateRange, true);
    }, 30_000);

    return () => clearInterval(id);
  }, [state.batches, state.page, state.statusFilter, state.dateRange]);

  // Toast auto-dismiss (4 seconds)
  useEffect(() => {
    if (!state.toast) return;
    const id = setTimeout(() => {
      setState(prev => ({ ...prev, toast: null }));
    }, 4000);
    return () => clearTimeout(id);
  }, [state.toast]);

  const fetchBatches = async (
    page: number,
    status: 'all' | 'queued' | 'processing' | 'completed' | 'failed',
    dateRange: '7d' | '30d' | '90d',
    skipNotification = false
  ) => {
    setState(prev => ({ ...prev, loading: !skipNotification, error: null }));
    try {
      const params = new URLSearchParams();
      if (status !== 'all') params.append('status', status);
      params.append('page', String(page));
      params.append('page_size', '20');
      params.append('days', dateRange.replace('d', ''));

      const data = await apiFetch<{ batches: BatchJob[]; total_pages: number }>(
        `/api/v1/batch/normalize?${params}`
      );

      setState(prev => ({
        ...prev,
        loading: false,
        batches: data.batches,
        totalPages: data.total_pages,
        page,
      }));
    } catch (err: any) {
      setState(prev => ({
        ...prev,
        loading: false,
        error: err.message,
        toast: !skipNotification ? { message: err.message, type: 'error' } : null,
      }));
    }
  };

  const handleFilterChange = (
    status: 'all' | 'queued' | 'processing' | 'completed' | 'failed',
    dateRange: '7d' | '30d' | '90d'
  ) => {
    setState(prev => ({
      ...prev,
      statusFilter: status,
      dateRange,
      page: 1,
    }));
    fetchBatches(1, status, dateRange);
  };

  const formatDate = (isoString: string) => {
    try {
      const date = new Date(isoString);
      const dateStr = date.toLocaleDateString('ko-KR');
      const timeStr = date.toLocaleTimeString('ko-KR', {
        hour: '2-digit',
        minute: '2-digit',
      });
      return `${dateStr} ${timeStr}`;
    } catch {
      return isoString;
    }
  };

  if (!user) {
    return <div className="p-4 text-gray-500">인증 중...</div>;
  }

  if (state.loading && state.batches.length === 0) {
    return (
      <div className="space-y-4 p-4">
        <div className="h-12 bg-gray-200 rounded animate-pulse" />
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-16 bg-gray-100 rounded animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4">
      {/* Toast */}
      {state.toast && (
        <div
          role="alert"
          aria-live="polite"
          className={`fixed bottom-4 right-4 shadow-lg z-50 px-4 py-2 rounded text-sm ${
            state.toast.type === 'success'
              ? 'bg-green-100 text-green-800'
              : 'bg-red-100 text-red-800'
          }`}
        >
          {state.toast.message}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">배치 작업 목록</h1>
        <button
          onClick={() => fetchBatches(state.page, state.statusFilter, state.dateRange)}
          className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
        >
          새로고침
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        <select
          value={state.statusFilter}
          onChange={e =>
            handleFilterChange(
              e.target.value as 'all' | 'queued' | 'processing' | 'completed' | 'failed',
              state.dateRange
            )
          }
          className="border rounded px-2 py-1 text-sm"
        >
          <option value="all">상태: 전체</option>
          <option value="queued">대기중</option>
          <option value="processing">처리중</option>
          <option value="completed">완료</option>
          <option value="failed">실패</option>
        </select>

        <select
          value={state.dateRange}
          onChange={e =>
            handleFilterChange(state.statusFilter, e.target.value as '7d' | '30d' | '90d')
          }
          className="border rounded px-2 py-1 text-sm"
        >
          <option value="7d">기간: 최근 7일</option>
          <option value="30d">최근 30일</option>
          <option value="90d">최근 90일</option>
        </select>
      </div>

      {/* Table */}
      {state.batches.length > 0 ? (
        <div className="overflow-x-auto bg-white rounded-lg border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-gray-50">
                <th scope="col" className="text-left py-2 px-2 w-24">배치ID</th>
                <th scope="col" className="text-left py-2 px-2 w-32">제출일시</th>
                <th scope="col" className="text-right py-2 px-2 w-20">파일수</th>
                <th scope="col" className="text-left py-2 px-2 w-24">상태</th>
                <th scope="col" className="text-right py-2 px-2 w-20">성공률</th>
                <th scope="col" className="text-left py-2 px-2 hidden lg:table-cell">제출자</th>
              </tr>
            </thead>
            <tbody>
              {state.batches.map(batch => (
                <tr
                  key={batch.batch_id}
                  onClick={() => router.push(`/normalization/batches/${batch.batch_id}`)}
                  className="border-b hover:bg-gray-50 cursor-pointer"
                >
                  <td className="py-2 px-2" title={batch.batch_id}>
                    {batch.batch_id.substring(0, 8)}…
                  </td>
                  <td className="py-2 px-2">{formatDate(batch.submitted_at)}</td>
                  <td className="text-right py-2 px-2">
                    {batch.file_count.toLocaleString()}
                  </td>
                  <td className="py-2 px-2">
                    <BatchStatusBadge status={batch.status} />
                  </td>
                  <td className="text-right py-2 px-2">
                    {batch.success_rate !== null
                      ? `${batch.success_rate.toFixed(1)}%`
                      : '—'}
                  </td>
                  <td className="py-2 px-2 hidden lg:table-cell">{batch.submitted_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-center py-12 text-gray-500 bg-white rounded-lg border">
          배치 작업이 없습니다. 새로운 배치를 제출하면 여기에 표시됩니다.
        </div>
      )}

      {/* Pagination */}
      {state.totalPages > 1 && (
        <div className="flex items-center justify-between py-4">
          <button
            onClick={() =>
              state.page > 1 &&
              fetchBatches(state.page - 1, state.statusFilter, state.dateRange)
            }
            disabled={state.page === 1}
            className="px-3 py-1 text-sm border rounded hover:bg-gray-50 disabled:opacity-50"
          >
            이전
          </button>
          <span className="text-sm text-gray-600">
            페이지 {state.page} / {state.totalPages}
          </span>
          <button
            onClick={() =>
              state.page < state.totalPages &&
              fetchBatches(state.page + 1, state.statusFilter, state.dateRange)
            }
            disabled={state.page === state.totalPages}
            className="px-3 py-1 text-sm border rounded hover:bg-gray-50 disabled:opacity-50"
          >
            다음
          </button>
        </div>
      )}
    </div>
  );
}
