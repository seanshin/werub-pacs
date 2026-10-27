'use client';

import { useEffect, useState, useCallback } from 'react';
import { apiFetch } from '@/lib/api';

type AuditLog = {
  id: string;
  username: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  description: string | null;
  ip_address: string | null;
  created_at: string;
  patient_id: string | null;
  study_instance_uid: string | null;
  status: string | null;
};

type AuditStats = {
  total_logs: number;
  by_action: Record<string, number>;
  by_user: Record<string, number>;
};

const ACTION_TYPES = ['LOGIN', 'LOGOUT', 'VIEW', 'CREATE', 'UPDATE', 'DELETE', 'UPLOAD', 'DOWNLOAD', 'EXPORT', 'AI_INFERENCE'];
const ENTITY_TYPES = ['user', 'study', 'series', 'instance', 'report', 'template', 'worklist', 'ai_model'];
const PAGE_LIMIT = 20;

const actionBadgeColor: Record<string, string> = {
  LOGIN: 'bg-green-100 text-green-800',
  LOGOUT: 'bg-gray-100 text-gray-800',
  VIEW: 'bg-blue-100 text-blue-800',
  CREATE: 'bg-teal-100 text-teal-800',
  UPDATE: 'bg-yellow-100 text-yellow-800',
  DELETE: 'bg-red-100 text-red-800',
  UPLOAD: 'bg-purple-100 text-purple-800',
  DOWNLOAD: 'bg-indigo-100 text-indigo-800',
  EXPORT: 'bg-orange-100 text-orange-800',
  AI_INFERENCE: 'bg-pink-100 text-pink-800',
};

export default function AuditPage() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<AuditStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Filters
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [userFilter, setUserFilter] = useState('');
  const [actionFilter, setActionFilter] = useState('');
  const [entityFilter, setEntityFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [searchText, setSearchText] = useState('');
  const [page, setPage] = useState(1);

  // Detail modal
  const [detailLog, setDetailLog] = useState<AuditLog | null>(null);

  // Export state
  const [exporting, setExporting] = useState(false);

  const buildParams = useCallback((overridePage?: number) => {
    const params = new URLSearchParams({
      limit: String(PAGE_LIMIT),
      offset: String(((overridePage ?? page) - 1) * PAGE_LIMIT),
    });
    if (dateFrom) params.append('date_from', dateFrom);
    if (dateTo) params.append('date_to', dateTo);
    if (userFilter) params.append('username', userFilter);
    if (actionFilter) params.append('action', actionFilter);
    if (entityFilter) params.append('resource_type', entityFilter);
    if (statusFilter) params.append('status', statusFilter);
    if (searchText) params.append('search', searchText);
    return params;
  }, [page, dateFrom, dateTo, userFilter, actionFilter, entityFilter, statusFilter, searchText]);

  const loadLogs = useCallback(async (targetPage?: number) => {
    setLoading(true);
    setError('');
    try {
      const params = buildParams(targetPage);
      const result = await apiFetch<{ results: AuditLog[]; total: number }>(
        `/api/v1/audit?${params.toString()}`
      );
      setLogs(result.results || []);
      setTotal(result.total || 0);
    } catch (e: any) {
      setError(e.message || '감사 로그를 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  }, [buildParams]);

  const loadStats = async () => {
    try {
      const s = await apiFetch<AuditStats>('/api/v1/audit/stats');
      setStats(s);
    } catch {
      // stats are non-critical
    }
  };

  useEffect(() => {
    loadStats();
  }, []);

  useEffect(() => {
    setPage(1);
    loadLogs(1);
  }, [dateFrom, dateTo, userFilter, actionFilter, entityFilter, statusFilter, searchText]);

  useEffect(() => {
    loadLogs(page);
  }, [page]);

  const resetFilters = () => {
    setDateFrom('');
    setDateTo('');
    setUserFilter('');
    setActionFilter('');
    setEntityFilter('');
    setStatusFilter('');
    setSearchText('');
    setPage(1);
  };

  const handleExport = async (format: 'csv' | 'json') => {
    setExporting(true);
    try {
      const params = buildParams(1);
      params.set('limit', '10000');
      params.set('offset', '0');
      params.append('format', format);

      const token = typeof window !== 'undefined' ? localStorage.getItem('pacs_token') : null;
      const res = await fetch(`/pacs-api/api/v1/audit/export?${params.toString()}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });

      if (!res.ok) throw new Error('내보내기 실패');

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `audit-log-${new Date().toISOString().slice(0, 10)}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // Fallback: export current page data as JSON
      const data = format === 'json'
        ? JSON.stringify(logs, null, 2)
        : [
            'id,username,action,resource_type,resource_id,ip_address,description,created_at',
            ...logs.map(l =>
              [l.id, l.username, l.action, l.resource_type, l.resource_id || '', l.ip_address || '', `"${(l.description || '').replace(/"/g, '""')}"`, l.created_at].join(',')
            ),
          ].join('\n');

      const blob = new Blob([data], { type: format === 'json' ? 'application/json' : 'text/csv' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `audit-log-${new Date().toISOString().slice(0, 10)}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_LIMIT));
  const hasFilters = dateFrom || dateTo || userFilter || actionFilter || entityFilter || statusFilter || searchText;

  return (
    <div>
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4">
        <h1 className="text-2xl font-bold">감사 로그</h1>
        <div className="flex gap-2">
          <button
            onClick={() => handleExport('csv')}
            disabled={exporting}
            className="px-3 py-2 border rounded-lg text-sm font-medium hover:bg-gray-50 disabled:opacity-50"
          >
            CSV 내보내기
          </button>
          <button
            onClick={() => handleExport('json')}
            disabled={exporting}
            className="px-3 py-2 border rounded-lg text-sm font-medium hover:bg-gray-50 disabled:opacity-50"
          >
            JSON 내보내기
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <div className="bg-white border rounded-lg p-3 text-center">
            <p className="text-sm text-gray-500">전체 로그</p>
            <p className="text-2xl font-bold">{stats.total_logs.toLocaleString()}</p>
          </div>
          {Object.entries(stats.by_action || {}).slice(0, 3).map(([action, count]) => (
            <div key={action} className="bg-white border rounded-lg p-3 text-center">
              <p className="text-sm text-gray-500">{action}</p>
              <p className="text-2xl font-bold">{(count as number).toLocaleString()}</p>
            </div>
          ))}
        </div>
      )}

      {/* Filter Panel */}
      <div className="bg-white rounded-lg border shadow-sm p-4 mb-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 text-sm mb-3">
          <div>
            <label className="text-xs text-gray-500 block mb-1">시작 날짜</label>
            <input
              type="date"
              value={dateFrom}
              onChange={e => setDateFrom(e.target.value)}
              className="w-full border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">종료 날짜</label>
            <input
              type="date"
              value={dateTo}
              onChange={e => setDateTo(e.target.value)}
              className="w-full border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">사용자</label>
            <input
              type="text"
              placeholder="사용자명..."
              value={userFilter}
              onChange={e => setUserFilter(e.target.value)}
              className="w-full border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">작업 유형</label>
            <select
              value={actionFilter}
              onChange={e => setActionFilter(e.target.value)}
              className="w-full border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
            >
              <option value="">모든 작업</option>
              {ACTION_TYPES.map(a => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">대상 유형</label>
            <select
              value={entityFilter}
              onChange={e => setEntityFilter(e.target.value)}
              className="w-full border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
            >
              <option value="">모든 대상</option>
              {ENTITY_TYPES.map(e => (
                <option key={e} value={e}>{e}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">결과 상태</label>
            <select
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
              className="w-full border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
            >
              <option value="">모든 결과</option>
              <option value="success">성공</option>
              <option value="failed">실패</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">메시지/IP 검색</label>
            <input
              type="text"
              placeholder="설명 또는 IP 주소..."
              value={searchText}
              onChange={e => setSearchText(e.target.value)}
              className="w-full border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>
        </div>
        {hasFilters && (
          <button
            onClick={resetFilters}
            className="text-sm text-gray-600 underline hover:text-gray-900"
          >
            필터 초기화
          </button>
        )}
      </div>

      {/* Error State */}
      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800 flex items-center justify-between">
          <span>{error}</span>
          <button
            onClick={() => loadLogs(page)}
            className="ml-4 px-3 py-1 bg-red-100 hover:bg-red-200 rounded text-xs font-medium"
          >
            재시도
          </button>
        </div>
      )}

      {/* Log Table */}
      <div className="bg-white rounded-lg border shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-500">
            <tr>
              <th className="px-4 py-2 text-left">시간</th>
              <th className="px-4 py-2 text-left">사용자</th>
              <th className="px-4 py-2 text-left">작업</th>
              <th className="px-4 py-2 text-left">대상</th>
              <th className="px-4 py-2 text-left">IP</th>
              <th className="px-4 py-2 text-left">환자</th>
              <th className="px-4 py-2 text-center">결과</th>
              <th className="px-4 py-2 text-left">설명</th>
              <th className="px-4 py-2 text-center">상세</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <>
                {[...Array(5)].map((_, i) => (
                  <tr key={i} className="border-t animate-pulse">
                    <td className="px-4 py-3"><div className="h-3 bg-gray-200 rounded w-32" /></td>
                    <td className="px-4 py-3"><div className="h-3 bg-gray-200 rounded w-20" /></td>
                    <td className="px-4 py-3"><div className="h-3 bg-gray-200 rounded w-16" /></td>
                    <td className="px-4 py-3"><div className="h-3 bg-gray-200 rounded w-16" /></td>
                    <td className="px-4 py-3"><div className="h-3 bg-gray-200 rounded w-24" /></td>
                    <td className="px-4 py-3"><div className="h-3 bg-gray-200 rounded w-20" /></td>
                    <td className="px-4 py-3"><div className="h-3 bg-gray-200 rounded w-12 mx-auto" /></td>
                    <td className="px-4 py-3"><div className="h-3 bg-gray-200 rounded w-40" /></td>
                    <td className="px-4 py-3"><div className="h-3 bg-gray-200 rounded w-8 mx-auto" /></td>
                  </tr>
                ))}
              </>
            ) : logs.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-4 py-12 text-center">
                  <p className="text-gray-400 text-base">감사 로그가 없습니다</p>
                  {hasFilters && (
                    <button onClick={resetFilters} className="mt-2 text-sm text-primary underline">
                      필터 초기화
                    </button>
                  )}
                </td>
              </tr>
            ) : (
              logs.map(log => (
                <tr key={log.id} className="border-t hover:bg-gray-50">
                  <td className="px-4 py-2 text-gray-500 whitespace-nowrap text-xs">
                    {new Date(log.created_at).toLocaleString('ko-KR')}
                  </td>
                  <td className="px-4 py-2 font-medium">{log.username || '-'}</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${actionBadgeColor[log.action] || 'bg-gray-100 text-gray-600'}`}>
                      {log.action}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{log.resource_type}</td>
                  <td className="px-4 py-2 text-gray-400 text-xs font-mono">{log.ip_address || '-'}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{log.patient_id || '-'}</td>
                  <td className="px-4 py-2 text-center">
                    {log.status === 'failed' ? (
                      <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-red-100 text-red-600 text-xs font-bold" title="실패">
                        X
                      </span>
                    ) : (
                      <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-green-100 text-green-600 text-xs font-bold" title="성공">
                        V
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-gray-600 max-w-[240px] truncate text-xs">
                    {log.description || '-'}
                  </td>
                  <td className="px-4 py-2 text-center">
                    <button
                      onClick={() => setDetailLog(log)}
                      className="text-primary hover:text-primary-dark text-xs font-medium"
                    >
                      보기
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {total > 0 && (
        <div className="flex items-center justify-between mt-4 text-sm">
          <div className="text-gray-600">
            총 {total.toLocaleString()}건 중 {((page - 1) * PAGE_LIMIT + 1).toLocaleString()}-{Math.min(page * PAGE_LIMIT, total).toLocaleString()}건 표시
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage(1)}
              disabled={page === 1}
              className="px-2 py-1 border rounded disabled:opacity-40 hover:bg-gray-50 text-xs"
            >
              처음
            </button>
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1 border rounded disabled:opacity-40 hover:bg-gray-50"
            >
              이전
            </button>
            <span className="px-3 py-1 text-gray-600">
              {page} / {totalPages}
            </span>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="px-3 py-1 border rounded disabled:opacity-40 hover:bg-gray-50"
            >
              다음
            </button>
            <button
              onClick={() => setPage(totalPages)}
              disabled={page >= totalPages}
              className="px-2 py-1 border rounded disabled:opacity-40 hover:bg-gray-50 text-xs"
            >
              마지막
            </button>
          </div>
        </div>
      )}

      {/* Detail Modal */}
      {detailLog && (
        <div
          className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
          onClick={() => setDetailLog(null)}
        >
          <div
            className="bg-white rounded-xl shadow-2xl p-6 w-full max-w-lg"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-bold">감사 로그 상세</h2>
              <button
                onClick={() => setDetailLog(null)}
                className="text-gray-400 hover:text-gray-600 text-xl leading-none"
              >
                x
              </button>
            </div>

            <div className="space-y-3 text-sm">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <span className="text-xs text-gray-500 block mb-0.5">로그 ID</span>
                  <span className="font-mono text-xs text-gray-700 break-all">{detailLog.id}</span>
                </div>
                <div>
                  <span className="text-xs text-gray-500 block mb-0.5">시간</span>
                  <span className="font-medium">{new Date(detailLog.created_at).toLocaleString('ko-KR')}</span>
                </div>
                <div>
                  <span className="text-xs text-gray-500 block mb-0.5">사용자</span>
                  <span className="font-semibold">{detailLog.username || '-'}</span>
                </div>
                <div>
                  <span className="text-xs text-gray-500 block mb-0.5">IP 주소</span>
                  <span className="font-mono">{detailLog.ip_address || '-'}</span>
                </div>
                <div>
                  <span className="text-xs text-gray-500 block mb-0.5">작업</span>
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${actionBadgeColor[detailLog.action] || 'bg-gray-100 text-gray-600'}`}>
                    {detailLog.action}
                  </span>
                </div>
                <div>
                  <span className="text-xs text-gray-500 block mb-0.5">결과 상태</span>
                  {detailLog.status === 'failed' ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700">
                      <span className="font-bold">X</span> 실패
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700">
                      <span className="font-bold">V</span> 성공
                    </span>
                  )}
                </div>
                <div>
                  <span className="text-xs text-gray-500 block mb-0.5">대상 유형</span>
                  <span className="font-medium">{detailLog.resource_type || '-'}</span>
                </div>
                <div>
                  <span className="text-xs text-gray-500 block mb-0.5">대상 ID</span>
                  <span className="font-mono text-xs text-gray-700 break-all">{detailLog.resource_id || '-'}</span>
                </div>
                <div>
                  <span className="text-xs text-gray-500 block mb-0.5">환자 ID</span>
                  <span className="font-medium">{detailLog.patient_id || '-'}</span>
                </div>
              </div>

              {detailLog.study_instance_uid && (
                <div>
                  <span className="text-xs text-gray-500 block mb-0.5">Study Instance UID</span>
                  <span className="font-mono text-xs text-gray-700 break-all">{detailLog.study_instance_uid}</span>
                </div>
              )}

              {detailLog.description && (
                <div>
                  <span className="text-xs text-gray-500 block mb-0.5">설명</span>
                  <p className="bg-gray-50 rounded p-3 text-gray-700 text-sm whitespace-pre-wrap">
                    {detailLog.description}
                  </p>
                </div>
              )}
            </div>

            <div className="flex justify-end mt-5">
              <button
                onClick={() => setDetailLog(null)}
                className="px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded text-sm font-medium"
              >
                닫기
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
