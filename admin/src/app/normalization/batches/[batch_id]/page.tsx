'use client';

import { useRouter, useParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { apiFetch, getUser } from '@/lib/api';
import { BatchStatusBadge } from '@/components/normalization/BatchStatusBadge';
import { RiskLevelBadge } from '@/components/normalization/RiskLevelBadge';
import { ProgressBar } from '@/components/normalization/ProgressBar';
import type { BatchDetail, BatchFile, ProgressMessage, Paginated } from '../../types';

type BatchDetailState = {
  loading: boolean;
  error: string | null;
  batch: BatchDetail | null;
  progress: ProgressMessage | null;
  wsConnected: boolean;
  files: BatchFile[];
  filePage: number;
  fileTotalPages: number;
  fileStatusFilter: 'all' | 'completed' | 'failed' | 'pending';
  fileRiskFilter: 'all' | 'safe' | 'medium' | 'risky';
  expandedErrors: Set<string>;
  toast: { message: string; type: 'error' | 'success' } | null;
};

export default function BatchDetailPage() {
  const router = useRouter();
  const params = useParams();
  const batchId = params.batch_id as string;
  const [user, setUser] = useState<any>(null);
  const [state, setState] = useState<BatchDetailState>({
    loading: true,
    error: null,
    batch: null,
    progress: null,
    wsConnected: false,
    files: [],
    filePage: 1,
    fileTotalPages: 1,
    fileStatusFilter: 'all',
    fileRiskFilter: 'all',
    expandedErrors: new Set(),
    toast: null,
  });

  // Auth guard
  useEffect(() => {
    const u = getUser();
    if (!u || !['admin', 'technologist'].includes(u.role)) {
      router.replace('/');
      return;
    }
    setUser(u);
  }, [router]);

  // Initial batch fetch
  useEffect(() => {
    if (!user || !batchId) return;
    fetchBatch();
    fetchFiles(1, 'all', 'all');
  }, [user, batchId]);

  // WebSocket + Polling lifecycle
  useEffect(() => {
    if (!batchId) return;

    const token = localStorage.getItem('pacs_token');
    if (!token) {
      router.replace('/');
      return;
    }

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(
      `${proto}//${location.host}/pacs-api/api/v1/ws/batch/${batchId}?token=${token}`
    );

    let pollingId: ReturnType<typeof setInterval> | null = null;

    ws.onopen = () => {
      setState(prev => ({ ...prev, wsConnected: true }));
    };

    ws.onmessage = (event) => {
      try {
        const msg: ProgressMessage = JSON.parse(event.data);
        setState(prev => ({ ...prev, progress: msg }));

        if (msg.status === 'completed' || msg.status === 'failed') {
          ws.close(1000);
          fetchBatch();
        }
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    const startPolling = () => {
      if (pollingId) return;
      setState(prev => ({ ...prev, wsConnected: false }));
      pollingId = setInterval(async () => {
        try {
          const job = await apiFetch<BatchDetail>(`/api/v1/batch/normalize/${batchId}`);
          setState(prev => ({ ...prev, batch: job }));
          if (job.status === 'completed' || job.status === 'failed') {
            clearInterval(pollingId!);
            pollingId = null;
          }
        } catch (err: any) {
          // Error already toasted by apiFetch
        }
      }, 5_000);
    };

    ws.onerror = () => {
      startPolling();
    };

    ws.onclose = (e) => {
      if (e.code !== 1000) {
        startPolling();
      }
    };

    return () => {
      ws.close();
      if (pollingId) clearInterval(pollingId);
    };
  }, [batchId, router]);

  // Toast auto-dismiss (4 seconds)
  useEffect(() => {
    if (!state.toast) return;
    const id = setTimeout(() => {
      setState(prev => ({ ...prev, toast: null }));
    }, 4000);
    return () => clearTimeout(id);
  }, [state.toast]);

  const fetchBatch = async () => {
    try {
      const batch = await apiFetch<BatchDetail>(`/api/v1/batch/normalize/${batchId}`);
      setState(prev => ({ ...prev, batch, loading: false }));
    } catch (err: any) {
      setState(prev => ({
        ...prev,
        loading: false,
        error: err.message,
        toast: { message: err.message, type: 'error' },
      }));
    }
  };

  const fetchFiles = async (
    page: number,
    statusFilter: 'all' | 'completed' | 'failed' | 'pending',
    riskFilter: 'all' | 'safe' | 'medium' | 'risky'
  ) => {
    try {
      const params = new URLSearchParams();
      if (statusFilter !== 'all') params.append('status', statusFilter);
      if (riskFilter !== 'all') params.append('risk', riskFilter);
      params.append('page', String(page));
      params.append('page_size', '10');

      const data = await apiFetch<Paginated<BatchFile>>(
        `/api/v1/batch/normalize/${batchId}/files?${params}`
      );

      setState(prev => ({
        ...prev,
        files: data.items,
        filePage: page,
        fileTotalPages: data.total_pages,
        fileStatusFilter: statusFilter,
        fileRiskFilter: riskFilter,
      }));
    } catch (err: any) {
      setState(prev => ({
        ...prev,
        toast: { message: err.message, type: 'error' },
      }));
    }
  };

  const toggleErrorExpand = (fileId: string) => {
    setState(prev => {
      const next = new Set(prev.expandedErrors);
      if (next.has(fileId)) {
        next.delete(fileId);
      } else {
        next.add(fileId);
      }
      return { ...prev, expandedErrors: next };
    });
  };

  const downloadJson = async () => {
    try {
      const stats = await apiFetch<any>(
        `/api/v1/batch/normalize/${batchId}/report`
      );
      const blob = new Blob([JSON.stringify(stats, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `batch-${batchId}-report.json`;
      a.click();
      URL.revokeObjectURL(url);
      setState(prev => ({
        ...prev,
        toast: { message: 'JSON 다운로드 완료', type: 'success' },
      }));
    } catch (err: any) {
      setState(prev => ({
        ...prev,
        toast: { message: err.message, type: 'error' },
      }));
    }
  };

  const formatDate = (isoString: string) => {
    try {
      const date = new Date(isoString);
      return date.toLocaleDateString('ko-KR');
    } catch {
      return isoString;
    }
  };

  if (!user) {
    return <div className="p-4 text-gray-500">인증 중...</div>;
  }

  if (state.loading && !state.batch) {
    return (
      <div className="space-y-4 p-4">
        <div className="h-12 bg-gray-200 rounded animate-pulse" />
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-16 bg-gray-100 rounded animate-pulse" />
        ))}
      </div>
    );
  }

  const batch = state.batch;
  const progress = state.progress;

  if (!batch) {
    return (
      <div className="p-4 text-center text-gray-500">
        배치를 찾을 수 없습니다.
      </div>
    );
  }

  const displayProgress = progress || {
    processed_files: batch.normalized_count,
    total_files: batch.file_count,
    status: batch.status,
    files_per_min: 0,
    errors: batch.error_count,
    medium_risk_pending: batch.medium_risk_pending,
  };

  return (
    <div className="space-y-6 p-4">
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
        <div>
          <h1 className="text-2xl font-bold">
            배치 상세: {batch.batch_id.substring(0, 8)}…
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            제출: {formatDate(batch.submitted_at)} | 제출자: {batch.submitted_by}
          </p>
        </div>
        <div className="flex gap-2">
          <BatchStatusBadge status={batch.status} />
          <button
            onClick={downloadJson}
            className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            JSON 다운로드
          </button>
        </div>
      </div>

      {/* Progress section */}
      <div className="bg-white rounded-lg border p-4 space-y-3">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold">진행 상황</h2>
          {batch.status !== 'completed' && batch.status !== 'failed' && (
            <span
              className={`inline-flex items-center gap-1 text-xs font-medium ${
                state.wsConnected
                  ? 'text-green-600'
                  : 'text-orange-600'
              }`}
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  state.wsConnected ? 'bg-green-600' : 'bg-orange-600'
                }`}
              />
              {state.wsConnected ? '실시간 연결' : '5초마다 갱신 중'}
            </span>
          )}
        </div>

        <ProgressBar
          processed={displayProgress.processed_files}
          total={displayProgress.total_files}
          animated={batch.status === 'processing' || batch.status === 'queued'}
        />

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
          <div>
            <p className="text-gray-500">처리 속도</p>
            <p className="font-semibold">{displayProgress.files_per_min} 파일/분</p>
          </div>
          <div>
            <p className="text-gray-500">오류</p>
            <p className="font-semibold text-red-600">
              {displayProgress.errors}
            </p>
          </div>
          <div>
            <p className="text-gray-500">검토 대기</p>
            <p className="font-semibold text-yellow-600">
              {displayProgress.medium_risk_pending}
            </p>
          </div>
          <div>
            <p className="text-gray-500">처리시간</p>
            <p className="font-semibold">
              {batch.processing_time_ms
                ? `${(batch.processing_time_ms / 1000).toFixed(1)}s`
                : '—'}
            </p>
          </div>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-lg border p-4">
          <p className="text-sm text-gray-500">전체파일</p>
          <p className="text-2xl font-bold">{batch.file_count.toLocaleString()}</p>
        </div>
        <div className="bg-white rounded-lg border p-4">
          <p className="text-sm text-gray-500">정규화완료</p>
          <p className="text-2xl font-bold text-green-600">
            {batch.normalized_count.toLocaleString()}
          </p>
        </div>
        <div className="bg-white rounded-lg border p-4">
          <p className="text-sm text-gray-500">오류</p>
          <p className="text-2xl font-bold text-red-600">
            {batch.error_count.toLocaleString()}
          </p>
        </div>
        <div className="bg-white rounded-lg border p-4">
          <p className="text-sm text-gray-500">검토대기</p>
          <p className="text-2xl font-bold text-yellow-600">
            {batch.medium_risk_pending.toLocaleString()}
          </p>
        </div>
      </div>

      {/* File list */}
      <div className="bg-white rounded-lg border p-4 space-y-4">
        <div>
          <h2 className="text-lg font-semibold mb-3">파일 목록</h2>
          <div className="flex gap-2 flex-wrap mb-4">
            <select
              value={state.fileStatusFilter}
              onChange={e =>
                fetchFiles(
                  1,
                  e.target.value as 'all' | 'completed' | 'failed' | 'pending',
                  state.fileRiskFilter
                )
              }
              className="border rounded px-2 py-1 text-sm"
            >
              <option value="all">상태: 전체</option>
              <option value="completed">완료</option>
              <option value="failed">오류</option>
              <option value="pending">대기중</option>
            </select>

            <select
              value={state.fileRiskFilter}
              onChange={e =>
                fetchFiles(
                  1,
                  state.fileStatusFilter,
                  e.target.value as 'all' | 'safe' | 'medium' | 'risky'
                )
              }
              className="border rounded px-2 py-1 text-sm"
            >
              <option value="all">위험도: 전체</option>
              <option value="safe">안전</option>
              <option value="medium">중간위험</option>
              <option value="risky">위험</option>
            </select>
          </div>
        </div>

        {state.files.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-gray-50">
                  <th scope="col" className="text-left py-2 px-2">파일명</th>
                  <th scope="col" className="text-left py-2 px-2 w-20">상태</th>
                  <th scope="col" className="text-left py-2 px-2 hidden lg:table-cell">적용 알고리즘</th>
                  <th scope="col" className="text-left py-2 px-2 w-24">위험도</th>
                  <th scope="col" className="text-left py-2 px-2">오류</th>
                </tr>
              </thead>
              <tbody>
                {state.files.map(file => (
                  <tr key={file.file_id} className="border-b hover:bg-gray-50">
                    <td className="py-2 px-2 truncate" title={file.filename}>
                      {file.filename}
                    </td>
                    <td className="py-2 px-2">
                      <BatchStatusBadge
                        status={file.status === 'pending' ? 'queued' : file.status}
                      />
                    </td>
                    <td className="py-2 px-2 hidden lg:table-cell text-xs">
                      {file.algorithms_applied.length > 0
                        ? file.algorithms_applied.join(', ')
                        : '—'}
                    </td>
                    <td className="py-2 px-2">
                      <RiskLevelBadge level={file.risk_level} />
                    </td>
                    <td className="py-2 px-2">
                      {file.error_message ? (
                        <>
                          <button
                            onClick={() => toggleErrorExpand(file.file_id)}
                            aria-expanded={state.expandedErrors.has(file.file_id)}
                            aria-controls={`error-${file.file_id}`}
                            className="text-blue-600 hover:underline text-xs"
                          >
                            펼치기 {state.expandedErrors.has(file.file_id) ? '▲' : '▼'}
                          </button>
                          {state.expandedErrors.has(file.file_id) && (
                            <div id={`error-${file.file_id}`} className="mt-2 p-2 bg-gray-100 rounded text-xs border border-gray-300">
                              <p className="font-semibold text-gray-700 mb-1">
                                {file.error_message}
                              </p>
                              {file.error_detail && (
                                <p className="text-gray-600 whitespace-pre-wrap">
                                  {file.error_detail.substring(0, 500)}
                                  {file.error_detail.length > 500 ? '...' : ''}
                                </p>
                              )}
                            </div>
                          )}
                        </>
                      ) : (
                        '—'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-center py-8 text-gray-500">파일이 없습니다.</p>
        )}

        {/* File pagination */}
        {state.fileTotalPages > 1 && (
          <div className="flex items-center justify-between pt-4 border-t">
            <button
              onClick={() =>
                state.filePage > 1 &&
                fetchFiles(state.filePage - 1, state.fileStatusFilter, state.fileRiskFilter)
              }
              disabled={state.filePage === 1}
              className="px-3 py-1 text-sm border rounded hover:bg-gray-50 disabled:opacity-50"
            >
              이전
            </button>
            <span className="text-sm text-gray-600">
              페이지 {state.filePage} / {state.fileTotalPages}
            </span>
            <button
              onClick={() =>
                state.filePage < state.fileTotalPages &&
                fetchFiles(state.filePage + 1, state.fileStatusFilter, state.fileRiskFilter)
              }
              disabled={state.filePage === state.fileTotalPages}
              className="px-3 py-1 text-sm border rounded hover:bg-gray-50 disabled:opacity-50"
            >
              다음
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
