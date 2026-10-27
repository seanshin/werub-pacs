'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { apiFetch, getUser } from '@/lib/api';
import { ReviewDecisionForm } from '@/components/normalization/ReviewDecisionForm';
import ConfirmDialog from '@/components/ConfirmDialog';
import type { ReviewItem, Paginated } from '../types';

type ReviewQueueState = {
  loading: boolean;
  error: string | null;
  items: ReviewItem[];
  page: number;
  totalPages: number;
  totalCount: number;
  changeTypeFilter: string;
  supplierFilter: string;
  submitting: Set<string>;
  confirmBulk: 'approve' | 'reject' | null;
  comments: Record<string, string>;
  toast: { message: string; type: 'error' | 'success' } | null;
};

export default function ReviewQueuePage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [state, setState] = useState<ReviewQueueState>({
    loading: true,
    error: null,
    items: [],
    page: 1,
    totalPages: 1,
    totalCount: 0,
    changeTypeFilter: 'all',
    supplierFilter: 'all',
    submitting: new Set(),
    confirmBulk: null,
    comments: {},
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
    fetchReviews(1, 'all', 'all');
  }, [router]);

  // Auto-refresh every 60 seconds
  useEffect(() => {
    const id = setInterval(() => {
      fetchReviews(state.page, state.changeTypeFilter, state.supplierFilter, true);
    }, 60_000);
    return () => clearInterval(id);
  }, [state.page, state.changeTypeFilter, state.supplierFilter]);

  // Toast auto-dismiss (4 seconds)
  useEffect(() => {
    if (!state.toast) return;
    const id = setTimeout(() => {
      setState(prev => ({ ...prev, toast: null }));
    }, 4000);
    return () => clearTimeout(id);
  }, [state.toast]);

  const fetchReviews = async (
    page: number,
    changeType: string,
    supplier: string,
    skipNotification = false
  ) => {
    setState(prev => ({ ...prev, loading: !skipNotification, error: null }));
    try {
      const params = new URLSearchParams();
      if (changeType !== 'all') params.append('change_type', changeType);
      if (supplier !== 'all') params.append('supplier', supplier);
      params.append('page', String(page));
      params.append('page_size', '10');

      const data = await apiFetch<Paginated<ReviewItem>>(
        `/api/v1/batch/reviews?${params}`
      );

      setState(prev => ({
        ...prev,
        loading: false,
        items: data.items,
        totalPages: data.total_pages,
        totalCount: data.total,
        page,
        changeTypeFilter: changeType,
        supplierFilter: supplier,
      }));

      // Write to localStorage for nav badge
      localStorage.setItem('pacs_review_count', String(data.total));
    } catch (err: any) {
      setState(prev => ({
        ...prev,
        loading: false,
        error: err.message,
        toast: !skipNotification ? { message: err.message, type: 'error' } : null,
      }));
    }
  };

  const submitDecision = async (reviewId: string, decision: 'approve' | 'reject') => {
    setState(prev => ({
      ...prev,
      submitting: new Set(prev.submitting).add(reviewId),
    }));

    try {
      const res = await apiFetch<any>(`/api/v1/batch/reviews/${reviewId}`, {
        method: 'POST',
        body: JSON.stringify({
          decision,
          comment: state.comments[reviewId] || '',
        }),
      });
      // 적용 결과 메시지 — 승인 시 DICOM 변경 적용/롤백 안내
      const n = res?.apply_result?.applied?.length || 0;
      const msg = decision === 'reject'
        ? '반려되었습니다.'
        : (res?.applied
            ? `승인·적용됨 (태그 ${n}개 변경) — 롤백은 DICOM 이슈 이력에서`
            : '승인되었습니다 (적용 대상 변경 없음).');

      // Optimistic removal
      setState(prev => {
        const next = new Set(prev.submitting);
        next.delete(reviewId);
        const newItems = prev.items.filter(item => item.review_id !== reviewId);
        const newTotal = prev.totalCount - 1;

        // Update localStorage
        localStorage.setItem('pacs_review_count', String(newTotal));

        // If page empties and not on first page, go back
        if (newItems.length === 0 && prev.page > 1) {
          fetchReviews(prev.page - 1, prev.changeTypeFilter, prev.supplierFilter);
        }

        return {
          ...prev,
          submitting: next,
          items: newItems,
          totalCount: newTotal,
          toast: { message: msg, type: 'success' },
        };
      });
    } catch (err: any) {
      setState(prev => {
        const next = new Set(prev.submitting);
        next.delete(reviewId);
        return {
          ...prev,
          submitting: next,
          toast: { message: err.message, type: 'error' },
        };
      });
    }
  };

  const submitBulkDecision = async (decision: 'approve' | 'reject') => {
    setState(prev => ({
      ...prev,
      submitting: new Set(state.items.map(item => item.review_id)),
    }));

    try {
      // Submit sequentially (not in parallel) to avoid rate limiting
      for (const item of state.items) {
        await apiFetch(`/api/v1/batch/reviews/${item.review_id}`, {
          method: 'POST',
          body: JSON.stringify({
            decision,
            comment: state.comments[item.review_id] || '',
          }),
        });
      }

      // All succeeded
      const newTotal = state.totalCount - state.items.length;
      localStorage.setItem('pacs_review_count', String(newTotal));

      setState(prev => ({
        ...prev,
        items: [],
        totalCount: newTotal,
        submitting: new Set(),
        confirmBulk: null,
        toast: {
          message: `${state.items.length}개 항목이 ${decision === 'approve' ? '승인' : '거부'}되었습니다.`,
          type: 'success',
        },
      }));

      if (state.page > 1) {
        fetchReviews(state.page - 1, state.changeTypeFilter, state.supplierFilter);
      } else {
        fetchReviews(1, state.changeTypeFilter, state.supplierFilter);
      }
    } catch (err: any) {
      setState(prev => ({
        ...prev,
        submitting: new Set(),
        toast: { message: err.message, type: 'error' },
      }));
    }
  };

  if (!user) {
    return <div className="p-4 text-gray-500">인증 중...</div>;
  }

  if (state.loading && state.items.length === 0) {
    return (
      <div className="space-y-4 p-4">
        <div className="h-12 bg-gray-200 rounded animate-pulse" />
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-24 bg-gray-100 rounded animate-pulse" />
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
        <h1 className="text-2xl font-bold">
          검토 대기 목록 [{state.totalCount}건]
        </h1>
      </div>

      {/* Filters + Bulk actions */}
      <div className="flex gap-2 flex-wrap items-center">
        <select
          value={state.changeTypeFilter}
          onChange={e =>
            fetchReviews(1, e.target.value, state.supplierFilter)
          }
          className="border rounded px-2 py-1 text-sm"
        >
          <option value="all">변경유형: 전체</option>
          <option value="PhotometricInterpretation">PhotometricInterpretation</option>
          <option value="Charset">Charset</option>
          <option value="PixelSpacing">PixelSpacing</option>
        </select>

        <select
          value={state.supplierFilter}
          onChange={e =>
            fetchReviews(1, state.changeTypeFilter, e.target.value)
          }
          className="border rounded px-2 py-1 text-sm"
        >
          <option value="all">공급업체: 전체</option>
          <option value="SIEMENS">SIEMENS</option>
          <option value="GE">GE</option>
          <option value="PHILIPS">PHILIPS</option>
        </select>

        {state.items.length > 0 && (
          <>
            <button
              onClick={() => setState(prev => ({ ...prev, confirmBulk: 'approve' }))}
              disabled={state.submitting.size > 0}
              className="px-3 py-1 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
            >
              전체 승인
            </button>
            <button
              onClick={() => setState(prev => ({ ...prev, confirmBulk: 'reject' }))}
              disabled={state.submitting.size > 0}
              className="px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50"
            >
              전체 거부
            </button>
          </>
        )}
      </div>

      {/* Items list */}
      {state.items.length > 0 ? (
        <div className="space-y-3">
          {state.items.map(item => (
            <div
              key={item.review_id}
              className="bg-white rounded-lg border p-4 space-y-2"
            >
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 text-sm">
                <div>
                  <p className="text-gray-500">파일명</p>
                  <p className="font-medium truncate" title={item.filename}>
                    {item.filename}
                  </p>
                </div>
                <div>
                  <p className="text-gray-500">DICOM 태그</p>
                  <p className="font-mono text-xs">{item.dicom_tag}</p>
                  {item.applicable
                    ? <span className="inline-block mt-1 text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700">승인 시 자동 적용</span>
                    : <span className="inline-block mt-1 text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">기록만(적용 불가)</span>}
                </div>
                <div>
                  <p className="text-gray-500">원래 값</p>
                  <p className="font-mono text-xs break-all">
                    {item.original_value}
                  </p>
                </div>
                <div>
                  <p className="text-gray-500">제안 값</p>
                  <p className="font-mono text-xs break-all">
                    {item.proposed_value}
                  </p>
                </div>
              </div>

              <div className="text-sm">
                <p className="text-gray-500">
                  {item.algorithm}
                  {item.supplier && ` • ${item.supplier}`}
                </p>
                <p className="text-gray-700">{item.risk_rationale}</p>
              </div>

              <ReviewDecisionForm
                reviewId={item.review_id}
                filename={item.filename}
                comment={state.comments[item.review_id] || ''}
                onCommentChange={(id, value) =>
                  setState(prev => ({
                    ...prev,
                    comments: { ...prev.comments, [id]: value },
                  }))
                }
                onDecision={submitDecision}
                submitting={state.submitting.has(item.review_id)}
              />
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-12 text-gray-500 bg-white rounded-lg border">
          {state.totalCount === 0
            ? '검토 대기 항목이 없습니다.'
            : '선택한 필터에 해당하는 항목이 없습니다.'}
        </div>
      )}

      {/* Pagination */}
      {state.totalPages > 1 && (
        <div className="flex items-center justify-between py-4">
          <button
            onClick={() =>
              state.page > 1 &&
              fetchReviews(state.page - 1, state.changeTypeFilter, state.supplierFilter)
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
              fetchReviews(state.page + 1, state.changeTypeFilter, state.supplierFilter)
            }
            disabled={state.page === state.totalPages}
            className="px-3 py-1 text-sm border rounded hover:bg-gray-50 disabled:opacity-50"
          >
            다음
          </button>
        </div>
      )}

      {/* ConfirmDialog for bulk actions */}
      <ConfirmDialog
        open={state.confirmBulk !== null}
        title={`${state.items.length}개 항목을 ${
          state.confirmBulk === 'approve' ? '승인' : '거부'
        }하시겠습니까?`}
        description="이 작업은 되돌릴 수 없습니다."
        onConfirm={() => {
          submitBulkDecision(state.confirmBulk!);
        }}
        onCancel={() => setState(prev => ({ ...prev, confirmBulk: null }))}
        confirmLabel={state.confirmBulk === 'approve' ? '승인' : '거부'}
        confirmClassName={`px-4 py-2 text-white rounded text-sm font-semibold ${
          state.confirmBulk === 'approve'
            ? 'bg-green-600 hover:bg-green-700'
            : 'bg-red-600 hover:bg-red-700'
        }`}
      />
    </div>
  );
}
