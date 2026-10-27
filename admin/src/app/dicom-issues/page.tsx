'use client';

import { useEffect, useState, useCallback } from 'react';
import { apiFetch } from '@/lib/api';
import { formatDate, formatPatientName, ModalityBadge } from '@/lib/format';
import ViewerButton from '@/components/ViewerButton';
import Breadcrumb from '@/components/ui/Breadcrumb';
import Link from 'next/link';

type Resolution = {
  auto_fixable: boolean; fix_method: string | null;
  guidance: string; risk: string;
};
type Issue = {
  id: string; severity: string; category: string; rule_code: string;
  message: string; details: any; resolution?: Resolution;
  patient_name: string; patient_id: string;
  study_instance_uid: string; study_description: string; study_date: string;
  modality: string; ae_title: string; manufacturer: string;
  issue_status: string; auto_fixed: boolean; reviewer_note: string;
  created_at: string; reviewed_at: string;
};

type Stats = {
  total_findings: number; auto_fixed: number; auto_fix_rate: number;
  unique_studies: number;
  by_severity: Record<string, number>;
  by_category: Record<string, number>;
  by_ae_title: Record<string, number>;
  top_rules: Record<string, number>;
  by_status: Record<string, number>;
};

type Trend = { date: string; critical: number; error: number; warning: number; info: number; total: number };

const sevColors: Record<string, string> = {
  critical: 'bg-red-100 text-red-800 border-red-200',
  error: 'bg-orange-100 text-orange-800 border-orange-200',
  warning: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  info: 'bg-blue-100 text-blue-800 border-blue-200',
};
const sevDot: Record<string, string> = {
  critical: 'bg-red-500', error: 'bg-orange-500', warning: 'bg-yellow-500', info: 'bg-blue-500',
};
const statusLabel: Record<string, string> = {
  unreviewed: '미확인', acknowledged: '확인됨', ignored: '무시', auto_fixed: '자동수정', manual_fixed: '수동수정',
};
const statusBadge: Record<string, string> = {
  unreviewed: 'bg-gray-100 text-gray-700', acknowledged: 'bg-blue-100 text-blue-700',
  ignored: 'bg-slate-100 text-slate-500', auto_fixed: 'bg-green-100 text-green-700', manual_fixed: 'bg-emerald-100 text-emerald-700',
};
const catLabel: Record<string, string> = {
  metadata: 'METADATA', pixel_data: 'PIXEL', transfer_syntax: 'TS', jpeg: 'JPEG', character_set: 'CHARSET', uid: 'UID',
};

export default function DicomIssuesPage() {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [trends, setTrends] = useState<Trend[]>([]);
  type FixHistory = { id: string; sop_instance_uid: string; rule_codes: string[]; changes: any[]; fix_status: string; fixed_at: string; rolled_back_at: string | null; post_validation: any };
  const [fixHistory, setFixHistory] = useState<FixHistory[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({ severity: '', category: '', status: '', ae_title: '', days: 30 });
  const [search, setSearch] = useState('');
  const [detail, setDetail] = useState<Issue | null>(null);
  const [statusNote, setStatusNote] = useState('');
  const [updating, setUpdating] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' | 'info' } | null>(null);
  const [aiSuggestions, setAiSuggestions] = useState<any[] | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const PAGE_SIZE = 20;

  useEffect(() => { if (!toast) return; const t = setTimeout(() => setToast(null), 5000); return () => clearTimeout(t); }, [toast]);

  const loadIssues = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    params.set('page', String(page));
    params.set('page_size', String(PAGE_SIZE));
    params.set('days', String(filters.days));
    if (filters.severity) params.set('severity', filters.severity);
    if (filters.category) params.set('category', filters.category);
    if (filters.status) params.set('status', filters.status);
    if (filters.ae_title) params.set('ae_title', filters.ae_title);
    try {
      const data = await apiFetch<{ issues: Issue[]; total: number }>(`/api/v1/dicom-issues?${params}`);
      setIssues(data.issues);
      setTotal(data.total);
    } catch {} finally { setLoading(false); }
  }, [page, filters]);

  const loadStats = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([
        apiFetch<Stats>(`/api/v1/dicom-issues/statistics?days=${filters.days}`),
        apiFetch<{ trends: Trend[] }>(`/api/v1/dicom-issues/trends?days=7`),
      ]);
      setStats(s);
      setTrends(t.trends);
    } catch {}
  }, [filters.days]);

  useEffect(() => { loadIssues(); }, [loadIssues]);
  useEffect(() => { loadStats(); }, [loadStats]);

  const updateStatus = async (id: string, status: string) => {
    setUpdating(true);
    try {
      await apiFetch(`/api/v1/dicom-issues/${id}/status`, {
        method: 'PATCH', body: JSON.stringify({ status, note: statusNote || null }),
      });
      loadIssues();
      loadStats();
      setDetail(null);
      setStatusNote('');
    } catch {} finally { setUpdating(false); }
  };

  const revalidate = async (id: string) => {
    setUpdating(true);
    try {
      const res = await apiFetch<any>(`/api/v1/dicom-issues/${id}/revalidate`, { method: 'POST' });
      if (res?.ok) { loadIssues(); loadStats(); setDetail(null); }
    } catch {} finally { setUpdating(false); }
  };

  const filtered = search
    ? issues.filter(i =>
        (i.patient_name || '').toLowerCase().includes(search.toLowerCase()) ||
        (i.patient_id || '').toLowerCase().includes(search.toLowerCase()) ||
        (i.rule_code || '').toLowerCase().includes(search.toLowerCase()) ||
        (i.study_description || '').toLowerCase().includes(search.toLowerCase())
      )
    : issues;

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const maxTrendTotal = Math.max(...trends.map(t => t.total), 1);

  return (
    <div className="p-4 sm:p-6 max-w-[1400px] mx-auto">
      {/* Toast notification */}
      {toast && (
        <div className={`fixed top-4 right-4 z-[9999] max-w-md px-4 py-3 rounded-xl shadow-lg text-sm font-medium animate-in slide-in-from-right ${
          toast.type === 'error' ? 'bg-red-500 text-white' :
          toast.type === 'success' ? 'bg-green-600 text-white' :
          'bg-blue-600 text-white'
        }`}>
          <div className="flex items-center gap-2">
            <span>{toast.type === 'success' ? '✓' : toast.type === 'error' ? '✕' : 'ℹ'}</span>
            <span>{toast.msg}</span>
            <button onClick={() => setToast(null)} className="ml-2 opacity-70 hover:opacity-100">✕</button>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between mb-6">
        <div>
          <Breadcrumb items={[{ label: '관리', href: '/' }, { label: 'DICOM 이슈' }]} />
          <h1 className="text-2xl font-bold mt-1">DICOM 이슈 컨트롤 센터</h1>
        </div>
        <div className="flex gap-2">
          <button onClick={async () => {
            if (!confirm('스캔 + 자동수정을 실행합니다. 진행하시겠습니까?')) return;
            setLoading(true);
            try {
              const res = await apiFetch<any>('/api/v1/dicom-issues/scan?limit=200&auto_fix=true', { method: 'POST' });
              setToast({ msg: `스캔 완료: ${res.scanned_studies}개 스터디, ${res.issues_found}개 이슈, ${res.auto_fixed || 0}건 자동수정`, type: 'success' });
              loadIssues(); loadStats();
            } catch (e: any) { setToast({ msg: '스캔 실패: ' + e.message, type: 'error' }); setLoading(false); }
          }}
            className="px-4 py-2 bg-indigo-500 text-white rounded-lg text-sm font-medium hover:bg-indigo-600 transition">
            스캔+자동수정
          </button>
          <button onClick={async () => {
            if (!confirm('미확인 이슈를 일괄 자동수정합니다. 진행하시겠습니까?')) return;
            setLoading(true);
            try {
              const res = await apiFetch<any>('/api/v1/dicom-issues/auto-fix-all?limit=100', { method: 'POST' });
              setToast({ msg: `일괄 자동수정: ${res.fixed}건 수정 (${res.resolved_total || 0}건 해소), ${res.skipped}건 건너뜀`, type: 'success' });
              loadIssues(); loadStats();
            } catch (e: any) { setToast({ msg: '일괄 자동수정 실패: ' + e.message, type: 'error' }); setLoading(false); }
          }}
            className="px-4 py-2 bg-amber-500 text-white rounded-lg text-sm font-medium hover:bg-amber-600 transition">
            일괄 자동수정
          </button>
          <Link href="/dicom-issues/settings"
            className="px-4 py-2 bg-slate-100 text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-200 transition">
            규칙 설정
          </Link>
          <button onClick={() => { loadIssues(); loadStats(); }}
            className="px-3 py-2 bg-white border rounded-lg text-sm hover:bg-gray-50">↻</button>
        </div>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
          {[
            { label: 'CRITICAL', value: stats.by_severity?.critical || 0, color: 'border-red-400 bg-red-50 text-red-700' },
            { label: 'ERROR', value: stats.by_severity?.error || 0, color: 'border-orange-400 bg-orange-50 text-orange-700' },
            { label: 'WARNING', value: stats.by_severity?.warning || 0, color: 'border-yellow-400 bg-yellow-50 text-yellow-700' },
            { label: 'INFO', value: stats.by_severity?.info || 0, color: 'border-blue-400 bg-blue-50 text-blue-700' },
            { label: '이슈 스터디', value: stats.unique_studies, color: 'border-gray-300 bg-gray-50 text-gray-700' },
            { label: '자동 수정율', value: `${stats.auto_fix_rate}%`, color: 'border-green-400 bg-green-50 text-green-700' },
          ].map(c => (
            <div key={c.label} className={`border-l-4 rounded-lg p-3 ${c.color}`}>
              <div className="text-2xl font-bold">{c.value}</div>
              <div className="text-xs font-medium mt-0.5">{c.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-2 mb-4">
        <select value={filters.severity} onChange={e => { setFilters(f => ({ ...f, severity: e.target.value })); setPage(1); }}
          className="border rounded-lg px-3 py-1.5 text-sm">
          <option value="">전체 심각도</option>
          <option value="critical">CRITICAL</option>
          <option value="error">ERROR</option>
          <option value="warning">WARNING</option>
          <option value="info">INFO</option>
        </select>
        <select value={filters.category} onChange={e => { setFilters(f => ({ ...f, category: e.target.value })); setPage(1); }}
          className="border rounded-lg px-3 py-1.5 text-sm">
          <option value="">전체 카테고리</option>
          <option value="metadata">METADATA</option>
          <option value="pixel_data">PIXEL_DATA</option>
          <option value="jpeg">JPEG</option>
          <option value="uid">UID</option>
          <option value="character_set">CHARACTER_SET</option>
          <option value="transfer_syntax">TRANSFER_SYNTAX</option>
        </select>
        <select value={filters.status} onChange={e => { setFilters(f => ({ ...f, status: e.target.value })); setPage(1); }}
          className="border rounded-lg px-3 py-1.5 text-sm">
          <option value="">전체 상태</option>
          <option value="unreviewed">미확인</option>
          <option value="acknowledged">확인됨</option>
          <option value="ignored">무시</option>
          <option value="auto_fixed">자동수정</option>
          <option value="manual_fixed">수동수정</option>
        </select>
        <select value={filters.days} onChange={e => { setFilters(f => ({ ...f, days: Number(e.target.value) })); setPage(1); }}
          className="border rounded-lg px-3 py-1.5 text-sm">
          <option value={7}>7일</option>
          <option value={30}>30일</option>
          <option value={90}>90일</option>
          <option value={365}>전체</option>
        </select>
        <input type="text" placeholder="검색: 환자명, ID, 규칙..." value={search}
          onChange={e => setSearch(e.target.value)}
          className="border rounded-lg px-3 py-1.5 text-sm flex-1 min-w-[200px]" />
      </div>

      {/* Issue Table */}
      <div className="bg-white rounded-xl border shadow-sm overflow-hidden mb-6">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-3 py-2.5 text-left font-semibold w-16">심각도</th>
                <th className="px-3 py-2.5 text-left font-semibold">규칙</th>
                <th className="px-3 py-2.5 text-left font-semibold">환자</th>
                <th className="px-3 py-2.5 text-left font-semibold hidden md:table-cell">스터디</th>
                <th className="px-3 py-2.5 text-left font-semibold w-16">모달</th>
                <th className="px-3 py-2.5 text-left font-semibold hidden lg:table-cell">AE Title</th>
                <th className="px-3 py-2.5 text-left font-semibold w-20">상태</th>
                <th className="px-3 py-2.5 text-left font-semibold hidden lg:table-cell w-20">발생일</th>
                <th className="px-3 py-2.5 text-right font-semibold w-28">액션</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {loading ? (
                <tr><td colSpan={9} className="px-4 py-12 text-center text-gray-400">불러오는 중...</td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={9} className="px-4 py-12 text-center text-gray-400">이슈가 없습니다</td></tr>
              ) : filtered.map(issue => (
                <tr key={issue.id} className="hover:bg-gray-50 cursor-pointer" onClick={() => setDetail(issue)}>
                  <td className="px-3 py-2.5">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${sevColors[issue.severity]}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${sevDot[issue.severity]}`} />
                      {issue.severity.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="font-mono text-xs text-gray-600">{issue.rule_code}</div>
                    <div className="text-[10px] text-gray-400">{catLabel[issue.category] || issue.category}</div>
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="font-medium text-sm">{formatPatientName(issue.patient_name) || '-'}</div>
                    <div className="text-[10px] text-gray-400">{issue.patient_id || ''}</div>
                  </td>
                  <td className="px-3 py-2.5 hidden md:table-cell text-gray-500 text-xs">{issue.study_description || '-'}</td>
                  <td className="px-3 py-2.5">{issue.modality ? <ModalityBadge modality={issue.modality} /> : '-'}</td>
                  <td className="px-3 py-2.5 hidden lg:table-cell text-xs text-gray-500 font-mono">{issue.ae_title || '-'}</td>
                  <td className="px-3 py-2.5">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${statusBadge[issue.issue_status] || 'bg-gray-100'}`}>
                      {statusLabel[issue.issue_status] || issue.issue_status}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 hidden lg:table-cell text-xs text-gray-400">{formatDate(issue.created_at?.slice(0, 10))}</td>
                  <td className="px-3 py-2.5 text-right" onClick={e => e.stopPropagation()}>
                    <div className="flex gap-1 justify-end">
                      <button onClick={() => setDetail(issue)} className="px-2 py-1 bg-gray-100 rounded text-[10px] hover:bg-gray-200">상세</button>
                      {issue.study_instance_uid && (
                        <ViewerButton url={`/werub-viewer/viewer?StudyInstanceUIDs=${issue.study_instance_uid}`} label="W" size="sm" modality={issue.modality} />
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t bg-gray-50 text-sm">
            <span className="text-gray-500">총 {total}건</span>
            <div className="flex gap-1">
              <button disabled={page === 1} onClick={() => setPage(p => p - 1)} className="px-2 py-1 border rounded disabled:opacity-40">◀</button>
              <span className="px-3 py-1">{page} / {totalPages}</span>
              <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)} className="px-2 py-1 border rounded disabled:opacity-40">▶</button>
            </div>
          </div>
        )}
      </div>

      {/* Trend Chart (simple bar) */}
      {trends.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
          <div className="bg-white rounded-xl border p-4">
            <h3 className="font-semibold text-sm mb-3">이슈 트렌드 (7일)</h3>
            <div className="flex items-end gap-1 h-24">
              {trends.map(t => (
                <div key={t.date} className="flex-1 flex flex-col items-center gap-0.5">
                  <div className="w-full flex flex-col-reverse">
                    {t.critical > 0 && <div className="bg-red-400 rounded-t" style={{ height: `${(t.critical / maxTrendTotal) * 80}px` }} />}
                    {t.error > 0 && <div className="bg-orange-400" style={{ height: `${(t.error / maxTrendTotal) * 80}px` }} />}
                    {t.warning > 0 && <div className="bg-yellow-400" style={{ height: `${(t.warning / maxTrendTotal) * 80}px` }} />}
                    {t.info > 0 && <div className="bg-blue-300 rounded-b" style={{ height: `${(t.info / maxTrendTotal) * 80}px` }} />}
                  </div>
                  <span className="text-[8px] text-gray-400">{t.date.slice(5)}</span>
                </div>
              ))}
            </div>
          </div>
          {stats && Object.keys(stats.top_rules).length > 0 && (
            <div className="bg-white rounded-xl border p-4">
              <h3 className="font-semibold text-sm mb-3">규칙별 TOP 이슈</h3>
              <div className="space-y-1.5">
                {Object.entries(stats.top_rules).slice(0, 6).map(([rule, cnt]) => {
                  const maxCnt = Math.max(...Object.values(stats.top_rules));
                  return (
                    <div key={rule} className="flex items-center gap-2">
                      <span className="text-[10px] font-mono text-gray-500 w-40 truncate">{rule}</span>
                      <div className="flex-1 bg-gray-100 rounded-full h-3">
                        <div className="bg-indigo-400 h-3 rounded-full" style={{ width: `${(cnt / maxCnt) * 100}%` }} />
                      </div>
                      <span className="text-xs font-bold text-gray-600 w-8 text-right">{cnt}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Fix History Section */}
      <div className="mb-6">
        <button onClick={async () => {
          if (!showHistory) {
            try {
              const data = await apiFetch<{ history: FixHistory[] }>('/api/v1/dicom-issues/fix-history?page_size=50');
              setFixHistory(data.history);
            } catch {}
          }
          setShowHistory(!showHistory);
        }}
          className="text-sm font-medium text-indigo-600 hover:text-indigo-800">
          {showHistory ? '▼ 수정 이력 접기' : '▶ 수정 이력 보기'} ({fixHistory.length}건)
        </button>
        {showHistory && fixHistory.length > 0 && (
          <div className="mt-2 bg-white rounded-xl border shadow-sm overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-3 py-2 text-left">SOP Instance</th>
                  <th className="px-3 py-2 text-left">규칙</th>
                  <th className="px-3 py-2 text-left">변경 사항</th>
                  <th className="px-3 py-2 text-left">상태</th>
                  <th className="px-3 py-2 text-left">일시</th>
                  <th className="px-3 py-2 text-right">액션</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {fixHistory.map(h => (
                  <tr key={h.id} className="hover:bg-gray-50">
                    <td className="px-3 py-2 font-mono text-gray-500 truncate max-w-[150px]">{h.sop_instance_uid?.slice(-20)}</td>
                    <td className="px-3 py-2">{h.rule_codes?.join(', ')}</td>
                    <td className="px-3 py-2 text-gray-600 max-w-[200px] truncate">
                      {h.changes?.map((c: any) => c.tag).join(', ')}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                        h.fix_status === 'applied' ? 'bg-green-100 text-green-700' :
                        h.fix_status === 'rolled_back' ? 'bg-red-100 text-red-700' : 'bg-gray-100'
                      }`}>{h.fix_status}</span>
                    </td>
                    <td className="px-3 py-2 text-gray-400">{h.fixed_at?.slice(0, 16).replace('T', ' ')}</td>
                    <td className="px-3 py-2 text-right">
                      {h.fix_status === 'applied' && (
                        <button onClick={async () => {
                          if (!confirm('이 수정을 롤백하시겠습니까? 원본 상태로 복원됩니다.')) return;
                          try {
                            await apiFetch(`/api/v1/dicom-issues/rollback/${h.id}`, { method: 'POST' });
                            setToast({ msg: '롤백 완료 — 원본 복원됨', type: 'info' });
                            const data = await apiFetch<{ history: FixHistory[] }>('/api/v1/dicom-issues/fix-history?page_size=50');
                            setFixHistory(data.history);
                            loadIssues(); loadStats();
                          } catch (e: any) { setToast({ msg: '롤백 실패: ' + e.message, type: 'error' }); }
                        }}
                          className="px-2 py-0.5 bg-red-100 text-red-600 rounded text-[10px] hover:bg-red-200">롤백</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Detail Modal */}
      {detail && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setDetail(null)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="p-5 border-b">
              <div className="flex items-center gap-2 mb-2">
                <span className={`px-2 py-0.5 rounded-full text-xs font-bold border ${sevColors[detail.severity]}`}>
                  {detail.severity.toUpperCase()}
                </span>
                <span className="font-mono text-sm text-gray-600">{detail.rule_code}</span>
                <span className={`ml-auto px-2 py-0.5 rounded text-[10px] ${statusBadge[detail.issue_status]}`}>
                  {statusLabel[detail.issue_status]}
                </span>
              </div>
              <h3 className="font-semibold">{detail.message}</h3>
            </div>
            <div className="p-5 space-y-3 text-sm">
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div><span className="text-gray-400">환자</span><div className="font-medium">{formatPatientName(detail.patient_name) || '-'}</div></div>
                <div><span className="text-gray-400">환자 ID</span><div>{detail.patient_id || '-'}</div></div>
                <div><span className="text-gray-400">스터디</span><div>{detail.study_description || '-'}</div></div>
                <div><span className="text-gray-400">날짜</span><div>{formatDate(detail.study_date)}</div></div>
                <div><span className="text-gray-400">모달리티</span><div>{detail.modality || '-'}</div></div>
                <div><span className="text-gray-400">AE Title</span><div className="font-mono">{detail.ae_title || '-'}</div></div>
                <div><span className="text-gray-400">제조사</span><div>{detail.manufacturer || '-'}</div></div>
                <div><span className="text-gray-400">카테고리</span><div>{catLabel[detail.category]}</div></div>
              </div>

              {detail.details && Object.keys(detail.details).length > 0 && (
                <div>
                  <div className="text-xs text-gray-400 mb-1">상세 정보</div>
                  <pre className="bg-gray-50 rounded-lg p-3 text-[11px] overflow-x-auto">{JSON.stringify(detail.details, null, 2)}</pre>
                </div>
              )}

              {detail.reviewer_note && (
                <div>
                  <div className="text-xs text-gray-400 mb-1">리뷰어 메모</div>
                  <p className="text-sm text-gray-700 bg-blue-50 rounded p-2">{detail.reviewer_note}</p>
                </div>
              )}

              <div>
                <div className="text-xs text-gray-400 mb-1">메모 (선택)</div>
                <textarea value={statusNote} onChange={e => setStatusNote(e.target.value)} rows={2}
                  className="w-full border rounded-lg p-2 text-sm" placeholder="상태 변경 사유..." />
              </div>

              {/* Resolution guidance */}
              {detail.resolution && (
                <div className={`rounded-lg p-3 text-xs space-y-1 ${detail.resolution.auto_fixable ? 'bg-amber-50 border border-amber-200' : 'bg-gray-50 border border-gray-200'}`}>
                  <div className="font-semibold text-gray-700">
                    {detail.resolution.auto_fixable ? '🔧 자동수정 가능' : '📋 수동 확인 필요'}
                  </div>
                  <p className="text-gray-600">{detail.resolution.guidance}</p>
                  {detail.resolution.fix_method && (
                    <p className="text-gray-500">수정 방법: <span className="font-medium text-gray-700">{detail.resolution.fix_method}</span></p>
                  )}
                  {detail.resolution.risk && detail.resolution.risk !== 'info' && (
                    <span className={`inline-block px-1.5 py-0.5 rounded text-[9px] font-bold ${
                      detail.resolution.risk === 'safe' ? 'bg-green-100 text-green-700' :
                      detail.resolution.risk === 'medium' ? 'bg-yellow-100 text-yellow-700' :
                      detail.resolution.risk === 'critical' ? 'bg-red-100 text-red-700' :
                      'bg-orange-100 text-orange-700'
                    }`}>위험도: {detail.resolution.risk.toUpperCase()}</span>
                  )}
                </div>
              )}

              <div className="flex flex-wrap gap-2">
                {detail.issue_status !== 'auto_fixed' && detail.resolution?.auto_fixable && (
                  <button onClick={async () => {
                    setUpdating(true);
                    try {
                      const res = await apiFetch<any>(`/api/v1/dicom-issues/auto-fix/${detail.id}`, { method: 'POST' });
                      if (res?.resolved) {
                        setToast({ msg: `자동수정 완료 — 이슈 해소됨 (${res.changes?.map((c: any) => c.tag).join(', ')})`, type: 'success' });
                      } else if (res?.fixed) {
                        setToast({ msg: `수정 적용됨 (일부 이슈 잔존: ${res.changes?.map((c: any) => c.tag).join(', ')})`, type: 'info' });
                      } else {
                        setToast({ msg: res?.reason || '자동수정 대상 없음', type: 'info' });
                      }
                      loadIssues(); loadStats(); setDetail(null);
                    } catch (e: any) { setToast({ msg: '자동수정 실패: ' + e.message, type: 'error' }); }
                    setUpdating(false);
                  }} disabled={updating}
                    className="px-3 py-1.5 bg-amber-500 text-white rounded-lg text-xs font-medium hover:bg-amber-600 disabled:opacity-50">자동수정</button>
                )}
                {detail.issue_status !== 'acknowledged' && (
                  <button onClick={() => updateStatus(detail.id, 'acknowledged')} disabled={updating}
                    className="px-3 py-1.5 bg-blue-500 text-white rounded-lg text-xs font-medium hover:bg-blue-600 disabled:opacity-50">확인</button>
                )}
                {detail.issue_status !== 'ignored' && (
                  <button onClick={() => updateStatus(detail.id, 'ignored')} disabled={updating}
                    className="px-3 py-1.5 bg-slate-400 text-white rounded-lg text-xs font-medium hover:bg-slate-500 disabled:opacity-50">무시</button>
                )}
                {detail.issue_status !== 'manual_fixed' && (
                  <button onClick={() => updateStatus(detail.id, 'manual_fixed')} disabled={updating}
                    className="px-3 py-1.5 bg-green-500 text-white rounded-lg text-xs font-medium hover:bg-green-600 disabled:opacity-50">수동수정</button>
                )}
                <button onClick={() => revalidate(detail.id)} disabled={updating}
                  className="px-3 py-1.5 bg-indigo-500 text-white rounded-lg text-xs font-medium hover:bg-indigo-600 disabled:opacity-50">재검증</button>
                <button onClick={async () => {
                  setAiLoading(true); setAiSuggestions(null);
                  try {
                    const res = await apiFetch<any>(`/api/v1/dicom-issues/ai-suggest/${detail.id}`, { method: 'POST' });
                    setAiSuggestions(res.suggestions || []);
                  } catch (e: any) { setToast({ msg: 'AI 제안 실패: ' + e.message, type: 'error' }); }
                  setAiLoading(false);
                }} disabled={aiLoading}
                  className="px-3 py-1.5 bg-purple-500 text-white rounded-lg text-xs font-medium hover:bg-purple-600 disabled:opacity-50">
                  {aiLoading ? 'AI 분석중...' : 'AI 제안'}
                </button>
              </div>

              {/* AI Suggestions */}
              {aiSuggestions && aiSuggestions.length > 0 && (
                <div className="mt-3 space-y-2">
                  <div className="text-xs font-semibold text-purple-700">AI 수정 제안</div>
                  {aiSuggestions.map((s, i) => (
                    <div key={i} className="bg-purple-50 border border-purple-200 rounded-lg p-3 text-xs space-y-1">
                      <div className="flex items-center gap-2">
                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                          s.confidence === 'high' ? 'bg-green-100 text-green-700' :
                          s.confidence === 'medium' ? 'bg-yellow-100 text-yellow-700' :
                          s.confidence === 'ai' ? 'bg-purple-100 text-purple-700' :
                          'bg-gray-100 text-gray-600'
                        }`}>{s.confidence === 'ai' ? 'AI' : s.confidence?.toUpperCase()}</span>
                        <span className="font-medium text-gray-700">{s.method === 'sibling_inference' ? '동일 Study 추론' :
                          s.method === 'pixel_analysis' ? '픽셀 분석' : s.method === 'bit_analysis' ? '비트 분석' :
                          s.method === 'ai_analysis' ? 'AI 분석' : s.method}</span>
                        {s.tag && <code className="text-gray-500">{s.tag}</code>}
                      </div>
                      {s.suggested_value && (
                        <div className="font-mono text-sm text-purple-800 bg-purple-100 rounded px-2 py-1">
                          {s.suggested_value}
                        </div>
                      )}
                      <p className="text-gray-600 whitespace-pre-wrap">{s.rationale}</p>
                      {s.source && <p className="text-[10px] text-gray-400">출처: {s.source}</p>}
                    </div>
                  ))}
                </div>
              )}
              {aiSuggestions && aiSuggestions.length === 0 && (
                <p className="mt-2 text-xs text-gray-400">AI 제안을 생성할 수 없습니다.</p>
              )}
            </div>
            <div className="p-4 border-t flex justify-end">
              <button onClick={() => { setDetail(null); setStatusNote(''); setAiSuggestions(null); }}
                className="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50">닫기</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
