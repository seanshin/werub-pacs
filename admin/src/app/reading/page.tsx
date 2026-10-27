'use client';

import Link from 'next/link';
import { useEffect, useState, useCallback } from 'react';
import { apiFetch } from '@/lib/api';
import { useRealtimeRefresh } from '@/hooks/useRealtimeRefresh';
import { isNonRenderable, isValidDicomUID } from '@/lib/dicom-renderability';
import { formatDate, formatPatientName, ModalityBadge } from '@/lib/format';
import ViewerButton from '@/components/ViewerButton';
import Breadcrumb from '@/components/ui/Breadcrumb';
import TableSkeleton from '@/components/ui/TableSkeleton';
import EmptyState from '@/components/ui/EmptyState';

const originIcon: Record<string, { letter: string; tip: string; bg: string; fg: string }> = {
  internal:       { letter: 'IN', tip: '원내 촬영',      bg: 'bg-emerald-500', fg: 'text-white' },
  external:       { letter: 'EX', tip: '원외 (타 병원)', bg: 'bg-orange-500',  fg: 'text-white' },
  patient_upload: { letter: 'PT', tip: '환자 업로드',    bg: 'bg-violet-500',  fg: 'text-white' },
  kiosk:          { letter: 'KI', tip: '키오스크',       bg: 'bg-cyan-500',    fg: 'text-white' },
  test_data:      { letter: 'TE', tip: '테스트 데이터',  bg: 'bg-gray-300',    fg: 'text-gray-600' },
  research:       { letter: 'RS', tip: '연구용',         bg: 'bg-indigo-500',  fg: 'text-white' },
  ai_generated:   { letter: 'AI', tip: 'AI 생성',       bg: 'bg-pink-500',    fg: 'text-white' },
  migration:      { letter: 'MG', tip: '데이터 이관',   bg: 'bg-amber-400',   fg: 'text-white' },
  unknown:        { letter: '--', tip: '미분류',         bg: 'bg-gray-200',    fg: 'text-gray-400' },
};

type ReadingItem = {
  patient_name: string; patient_id: string; modality: string;
  study_description: string; study_date: string; study_time: string;
  read_status: string; urgency: string; viewer_url: string;
  study_instance_uid: string; accession_number: string; series_count: number;
  instance_count?: number; report_id: string | null; reader: string | null;
  sla_minutes: number | null; sla_level: string | null;
  ai_available: boolean;
  origin: string | null; origin_label: string | null; source_institution: string | null;
};

export default function ReadingPage() {
  const [queue, setQueue] = useState<ReadingItem[]>([]);
  const [filtered, setFiltered] = useState<ReadingItem[]>([]);
  const [filter, setFilter] = useState('');
  const [search, setSearch] = useState('');
  const [total, setTotal] = useState(0);
  const [unread, setUnread] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [aiLoading, setAiLoading] = useState<string | null>(null);
  const [aiResult, setAiResult] = useState<{ uid: string; findings: string; impression: string } | null>(null);
  const [preliminary, setPreliminary] = useState(0);
  const [archiveTarget, setArchiveTarget] = useState<ReadingItem | null>(null);
  const [archiveReason, setArchiveReason] = useState('quality_reject');
  const [archiveNote, setArchiveNote] = useState('');
  const [archiving, setArchiving] = useState(false);

  // Orchestration pipeline
  type ProdPipeline = { pipeline: string; modalities?: string[]; keywords?: string[] };
  const [prodPipeline, setProdPipeline] = useState<ProdPipeline | null>(null);
  const [pipeLoading, setPipeLoading] = useState<string | null>(null);
  const [pipeResult, setPipeResult] = useState<{ uid: string; result: string; pipeline: string; duration_ms: number } | null>(null);

  const PIPE_MATCH: Record<string, { modalities: string[]; keywords: string[] }> = {
    'chest-xray': { modalities: ['CR', 'DX'], keywords: ['chest', 'thorax', 'lung', '흉부'] },
    'ct-abdomen': { modalities: ['CT'], keywords: ['abdomen', 'liver', 'pancreas', '복부'] },
    'emergency-triage': { modalities: ['CR', 'DX', 'CT'], keywords: [] },
    'medical': { modalities: ['CR', 'DX', 'CT', 'MR', 'US'], keywords: [] },
    'consensus': { modalities: ['CR', 'DX', 'CT', 'MR'], keywords: [] },
  };

  const isPipelineMatch = (item: ReadingItem): boolean => {
    if (!prodPipeline) return false;
    const match = PIPE_MATCH[prodPipeline.pipeline];
    if (!match) return true; // unknown pipeline = show for all
    const mod = (item.modality || '').toUpperCase();
    return match.modalities.some(m => mod.includes(m));
  };
  const PAGE_SIZE = 20;

  const [provenanceScanned, setProvenanceScanned] = useState(false);

  const load = (status?: string) => {
    const url = status ? `/api/v1/dashboard/reading-queue?status=${status}` : '/api/v1/dashboard/reading-queue';
    apiFetch<{ queue: ReadingItem[]; total: number; unread: number }>(url).then(d => {
      setQueue(d.queue); setTotal(d.total); setUnread(d.unread); setLoading(false);
      setPreliminary(d.queue.filter(i => i.read_status === 'preliminary').length);
      applySearch(d.queue, search);
      // Auto-scan provenance if any item has no origin, then reload
      if (!provenanceScanned && d.queue.some(i => !i.origin)) {
        setProvenanceScanned(true);
        apiFetch('/api/v1/provenance/scan?limit=200', { method: 'POST' }).then(() => {
          // Reload queue to pick up provenance data
          const reloadUrl = status ? `/api/v1/dashboard/reading-queue?status=${status}` : '/api/v1/dashboard/reading-queue';
          apiFetch<{ queue: ReadingItem[]; total: number; unread: number }>(reloadUrl).then(d2 => {
            setQueue(d2.queue); applySearch(d2.queue, search);
          }).catch(() => {});
        }).catch(() => {});
      }
    }).catch(() => setLoading(false)); // 실패 시 스피너 영구 고착 방지
  };

  const applySearch = (items: ReadingItem[], q: string) => {
    if (!q) { setFiltered(items); return; }
    const lower = q.toLowerCase();
    setFiltered(items.filter(i =>
      (i.patient_name || '').toLowerCase().includes(lower) ||
      (i.patient_id || '').toLowerCase().includes(lower) ||
      (i.study_description || '').toLowerCase().includes(lower) ||
      (i.accession_number || '').toLowerCase().includes(lower)
    ));
    setPage(1);
  };

  const refreshQueue = useCallback(() => load(filter || undefined), [filter]);
  useRealtimeRefresh(refreshQueue, 15000, ['notification', 'new_study', 'report_signed', 'urgent_reading']);

  // Load production pipeline on mount
  useEffect(() => {
    apiFetch<Record<string, any>>('/api/v1/ai/orchestration/production').then(d => {
      if (d?.reading?.pipeline) setProdPipeline({ pipeline: d.reading.pipeline });
    }).catch(() => {});
  }, []);

  const pageItems = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);

  const handleFilter = (s: string) => { setFilter(s); load(s || undefined); };

  const statusBadge: Record<string, string> = {
    unread: 'bg-yellow-100 text-yellow-800',
    draft: 'bg-blue-100 text-blue-800',
    preliminary: 'bg-purple-100 text-purple-800',
    final: 'bg-green-100 text-green-800',
  };
  const statusLabel: Record<string, string> = {
    unread: '판독 대기', draft: '작성 중', preliminary: '예비 판독', final: '판독 완료',
  };

  return (
    <div>
      <Breadcrumb items={[{ label: '판독 큐' }]} />
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">판독 큐</h1>
        <div className="flex items-center gap-3 text-sm">
          <Link href="/reading/stats" className="text-blue-600 hover:underline">판독 시간</Link>
          <Link href="/reading/residents" className="text-blue-600 hover:underline">레지던트 성과</Link>
          <span className="text-gray-500">전체 {total}건</span>
          {unread > 0 && <span className="bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded font-medium">대기 {unread}건</span>}
          {preliminary > 0 && <span className="bg-purple-100 text-purple-800 px-2 py-0.5 rounded font-medium">예비 {preliminary}건</span>}
          <div className="hidden xl:flex items-center gap-1 border-l pl-3 ml-1">
            {Object.entries(originIcon).filter(([k]) => k !== 'unknown').map(([k, o]) => (
              <span key={k} className="relative group inline-flex">
                <span className={`w-5 h-5 rounded text-[7px] font-black flex items-center justify-center ${o.bg} ${o.fg}`}>{o.letter}</span>
                <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-2 py-1 bg-gray-900 text-white text-[10px] rounded-md whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-10">
                  {o.tip}
                  <span className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900" />
                </span>
              </span>
            ))}
            <span className="text-[9px] text-gray-400 ml-0.5">출처</span>
          </div>
        </div>
      </div>

      <div className="flex gap-2 mb-4">
        {[
          { key: '', label: '전체' },
          { key: 'unread', label: '판독 대기' },
          { key: 'draft', label: '작성 중' },
          { key: 'preliminary', label: '예비 판독' },
          { key: 'final', label: '완료' },
        ].map(f => (
          <button key={f.key} onClick={() => handleFilter(f.key)}
            className={`px-3 py-1.5 rounded text-sm font-medium transition ${filter === f.key ? 'bg-primary text-white' : 'bg-white border text-gray-600 hover:bg-gray-50'}`}>
            {f.label}
          </button>
        ))}
        <div className="flex-1" />
        <input type="text" placeholder="🔍 환자명, 환자번호, 검사설명 검색..."
          className="border rounded px-3 py-1.5 text-sm w-64"
          value={search} onChange={e => { setSearch(e.target.value); applySearch(queue, e.target.value); }} />
      </div>

      {loading ? <TableSkeleton rows={8} cols={7} /> : (
      <div className="bg-white rounded-lg border shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-500">
            <tr>
              <th className="px-2 sm:px-4 py-3 text-left whitespace-nowrap">상태</th>
              <th className="px-2 sm:px-4 py-3 text-left whitespace-nowrap">환자명</th>
              <th className="px-2 sm:px-4 py-3 text-left hidden sm:table-cell">환자번호</th>
              <th className="px-2 sm:px-4 py-3 text-left">모달리티</th>
              <th className="px-2 sm:px-4 py-3 text-left hidden md:table-cell">검사설명</th>
              <th className="px-2 sm:px-4 py-3 text-left hidden lg:table-cell">검사일</th>
              <th className="px-2 sm:px-4 py-3 text-left hidden lg:table-cell">접수번호</th>
              <th className="px-2 sm:px-4 py-3 text-left hidden md:table-cell">판독의</th>
              <th className="px-2 sm:px-4 py-3 sticky right-0 bg-gray-50 text-center">출처</th>
            </tr>
          </thead>
          <tbody>
            {pageItems.length === 0 && (
              <tr><td colSpan={10}>
                <EmptyState
                  icon={search ? 'search' : 'inbox'}
                  title={search ? `"${search}" 검색 결과가 없습니다` : filter ? `'${statusLabel[filter] || filter}' 상태의 검사가 없습니다` : '판독 큐가 비어있습니다'}
                  description={search ? '검색어를 변경하거나 필터를 초기화해 보세요' : undefined}
                  action={search || filter ? { label: '필터 초기화', onClick: () => { setSearch(''); setFilter(''); load(); } } : undefined}
                />
              </td></tr>
            )}
            {pageItems.map((item, i) => (
              <tr key={i} className={`border-t hover:bg-gray-50 ${item.urgency === 'urgent' ? 'bg-red-50' : ''}`}>
                <td className="px-2 sm:px-4 py-3 whitespace-nowrap">
                  <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap ${statusBadge[item.read_status] || 'bg-gray-100'}`}>
                    {statusLabel[item.read_status] || item.read_status}
                  </span>
                  {item.urgency === 'urgent' && <span className="ml-1 text-red-600 font-bold text-xs">STAT</span>}
                  {item.sla_level === 'critical' && (
                    <span className="ml-1 text-red-600 text-[10px] font-semibold animate-pulse">{item.sla_minutes}분</span>
                  )}
                  {item.sla_level === 'warning' && (
                    <span className="ml-1 text-orange-500 text-[10px] font-semibold">{item.sla_minutes}분</span>
                  )}
                </td>
                <td className="px-2 sm:px-4 py-3 font-medium whitespace-nowrap">{formatPatientName(item.patient_name)}</td>
                <td className="px-2 sm:px-4 py-3 text-gray-500 hidden sm:table-cell">{item.patient_id}</td>
                <td className="px-2 sm:px-4 py-3">
                  <span className="flex items-center gap-1.5">
                    <ModalityBadge modality={item.modality} />
                    {item.series_count > 0 && (
                      <span className="text-[10px] text-gray-400" title={`${item.series_count}개 시리즈`}>{item.series_count}s</span>
                    )}
                    {isNonRenderable(item.modality) && (
                      <span className="text-amber-500 text-[10px] font-bold" title="영상 표시 불가 모달리티">⚠</span>
                    )}
                    {!isValidDicomUID(item.study_instance_uid) && (
                      <span className="text-red-500 text-[10px] font-bold" title="비표준 Study UID — 뷰어 표시 불가">⛔</span>
                    )}
                  </span>
                </td>
                <td className="px-2 sm:px-4 py-3 text-gray-600 hidden md:table-cell">{item.study_description || '-'}</td>
                <td className="px-2 sm:px-4 py-3 text-gray-500 whitespace-nowrap hidden lg:table-cell">{formatDate(item.study_date)}</td>
                <td className="px-2 sm:px-4 py-3 text-gray-500 hidden lg:table-cell">{item.accession_number || '-'}</td>
                <td className="px-2 sm:px-4 py-3 text-gray-500 hidden md:table-cell">{item.reader || '-'}</td>
                <td className="px-2 py-2 sticky right-0 bg-white">
                <div className="flex gap-1.5 items-center justify-end whitespace-nowrap">
                  {(() => {
                    const o = originIcon[item.origin || 'unknown'] || originIcon.unknown;
                    return (
                      <span className="relative group inline-flex items-center justify-center">
                        <span className={`w-5 h-5 rounded text-[7px] font-black leading-none flex items-center justify-center ${o.bg} ${o.fg}`}>
                          {o.letter}
                        </span>
                        <span className="absolute bottom-full right-0 mb-1.5 px-2 py-1 bg-gray-900 text-white text-[10px] rounded-md whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-10">
                          {o.tip}{item.source_institution ? ` — ${item.source_institution}` : ''}
                          <span className="absolute top-full right-2 border-4 border-transparent border-t-gray-900" />
                        </span>
                      </span>
                    );
                  })()}
                  {item.ai_available && (
                  <button onClick={async () => {
                    setAiLoading(item.study_instance_uid);
                    try {
                      const res = await apiFetch<any>('/api/v1/ai/analyze-and-draft', {
                        method: 'POST',
                        body: JSON.stringify({ study_instance_uid: item.study_instance_uid, modality: item.modality, auto_create_report: true }),
                      });
                      if (res?.ai_analysis) {
                        setAiResult({ uid: item.study_instance_uid, findings: res.ai_analysis.findings, impression: res.ai_analysis.impression });
                      }
                    } catch {} finally { setAiLoading(null); }
                  }}
                    disabled={aiLoading === item.study_instance_uid}
                    className="bg-purple-500 text-white px-2 py-1 rounded text-xs hover:bg-purple-600 transition disabled:opacity-50"
                    title="AI 분석">
                    {aiLoading === item.study_instance_uid ? '...' : 'AI'}
                  </button>
                  )}
                  {prodPipeline && isPipelineMatch(item) && (
                  <button onClick={async () => {
                    setPipeLoading(item.study_instance_uid);
                    try {
                      const res = await apiFetch<any>('/api/v1/ai/orchestration/run', {
                        method: 'POST',
                        body: JSON.stringify({ pipeline: prodPipeline.pipeline, study_instance_uid: item.study_instance_uid, debug: false }),
                      });
                      if (res && !res.error) {
                        setPipeResult({ uid: item.study_instance_uid, result: res.result || '', pipeline: prodPipeline.pipeline, duration_ms: res.total_duration_ms || 0 });
                      }
                    } catch {} finally { setPipeLoading(null); }
                  }}
                    disabled={pipeLoading === item.study_instance_uid}
                    className="bg-green-600 text-white px-2 py-1 rounded text-xs hover:bg-green-700 transition disabled:opacity-50"
                    title={`${prodPipeline.pipeline} 파이프라인 실행`}>
                    {pipeLoading === item.study_instance_uid ? '...' : `🔗${prodPipeline.pipeline.split('-')[0]}`}
                  </button>
                  )}
                  <ViewerButton url={`/werub-viewer/viewer?StudyInstanceUIDs=${item.study_instance_uid || ''}`} label="W" size="sm" modality={item.modality} />
                  <a href={`/pacs-admin/reading/view?study=${item.study_instance_uid || ''}`}
                    className="bg-primary text-white px-3 py-1 rounded text-xs hover:bg-primary-dark transition">
                    판독 ↗
                  </a>
                  <button onClick={(e) => { e.stopPropagation(); setArchiveTarget(item); setArchiveNote(''); }}
                    className="text-gray-400 hover:text-orange-600 px-1 py-1 rounded text-xs transition"
                    title="아카이브 (삭제 대신 보관)">
                    🗄️
                  </button>
                </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}

      {aiResult && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={() => setAiResult(null)}>
          <div className="bg-white rounded-xl shadow-2xl p-6 w-full max-w-lg max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-lg font-bold">AI 분석 결과</h2>
              <button onClick={() => setAiResult(null)} className="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
            </div>
            <div className="space-y-3 text-sm">
              <div>
                <label className="text-xs text-gray-500 font-semibold">소견 (Findings)</label>
                <div className="bg-gray-50 rounded p-3 mt-1 whitespace-pre-wrap">{aiResult.findings || '-'}</div>
              </div>
              <div>
                <label className="text-xs text-gray-500 font-semibold">결론 (Impression)</label>
                <div className="bg-blue-50 rounded p-3 mt-1 whitespace-pre-wrap">{aiResult.impression || '-'}</div>
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setAiResult(null)} className="px-4 py-2 border rounded text-sm">닫기</button>
              <a href={`/pacs-admin/reading/view?study=${aiResult.uid}`}
                className="px-4 py-2 bg-primary text-white rounded text-sm font-semibold">판독 화면으로 →</a>
            </div>
          </div>
        </div>
      )}

      {pipeResult && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={() => setPipeResult(null)}>
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl p-6 w-full max-w-2xl max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-lg font-bold">
                🔗 {pipeResult.pipeline} 파이프라인 결과
                <span className="text-blue-500 text-sm font-normal ml-2">{(pipeResult.duration_ms / 1000).toFixed(1)}초</span>
              </h2>
              <button onClick={() => setPipeResult(null)} className="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
            </div>
            <div className="bg-blue-50 dark:bg-blue-900/20 rounded p-4 text-sm leading-relaxed whitespace-pre-wrap max-h-96 overflow-y-auto">
              {pipeResult.result}
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setPipeResult(null)} className="px-4 py-2 border rounded text-sm">닫기</button>
              <a href={`/pacs-admin/reading/view?study=${pipeResult.uid}`}
                className="px-4 py-2 bg-primary text-white rounded text-sm font-semibold">판독 화면으로 →</a>
            </div>
          </div>
        </div>
      )}

      {archiveTarget && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={() => setArchiveTarget(null)}>
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl p-6 w-full max-w-md" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-lg font-bold">🗄️ 아카이브</h2>
              <button onClick={() => setArchiveTarget(null)} className="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
            </div>
            <div className="space-y-3 text-sm">
              <div className="bg-gray-50 dark:bg-gray-700 rounded p-3">
                <p className="font-semibold">{formatPatientName(archiveTarget.patient_name)} ({archiveTarget.patient_id})</p>
                <p className="text-gray-500 text-xs mt-1">{archiveTarget.modality} · {archiveTarget.study_description || '-'} · {formatDate(archiveTarget.study_date)}</p>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-600 dark:text-gray-300">아카이브 사유</label>
                <select value={archiveReason} onChange={e => setArchiveReason(e.target.value)}
                  className="w-full mt-1 border rounded px-3 py-2 text-sm dark:bg-gray-700 dark:border-gray-600">
                  <option value="quality_reject">화질 불량</option>
                  <option value="patient_safety">환자 안전 (잘못된 환자)</option>
                  <option value="worklist_error">오더 오류</option>
                  <option value="superseded">재촬영으로 대체</option>
                  <option value="storage_migration">스토리지 이동</option>
                  <option value="manual">수동 아카이브</option>
                </select>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-600 dark:text-gray-300">메모 (선택)</label>
                <textarea value={archiveNote} onChange={e => setArchiveNote(e.target.value)}
                  placeholder="아카이브 사유를 상세히 기록하세요"
                  className="w-full mt-1 border rounded px-3 py-2 text-sm h-20 dark:bg-gray-700 dark:border-gray-600" />
              </div>
              <p className="text-xs text-orange-600">⚠ 아카이브된 영상은 Orthanc에서 제거되며, 관리 페이지에서 복원할 수 있습니다.</p>
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setArchiveTarget(null)} className="px-4 py-2 border rounded text-sm">취소</button>
              <button disabled={archiving} onClick={async () => {
                setArchiving(true);
                try {
                  await apiFetch('/api/v1/archive', {
                    method: 'POST',
                    body: JSON.stringify({
                      study_instance_uid: archiveTarget.study_instance_uid,
                      reason: archiveReason,
                      note: archiveNote || undefined,
                    }),
                  });
                  setArchiveTarget(null);
                  load(filter || undefined);
                } catch (e: any) {
                  alert(`아카이브 실패: ${(e as Error).message || '알 수 없는 오류'}`);
                } finally { setArchiving(false); }
              }}
                className="px-4 py-2 bg-orange-600 text-white rounded text-sm font-semibold hover:bg-orange-700 disabled:opacity-50">
                {archiving ? '처리 중...' : '아카이브 실행'}
              </button>
            </div>
          </div>
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4 text-sm">
          <span className="text-gray-500">총 {filtered.length}건 중 {(page-1)*PAGE_SIZE+1}-{Math.min(page*PAGE_SIZE, filtered.length)}건</span>
          <div className="flex items-center gap-1">
            <button onClick={() => setPage(p => Math.max(1, p-1))} disabled={page === 1}
              className="px-3 py-1.5 border rounded hover:bg-gray-50 disabled:opacity-30 disabled:cursor-not-allowed">← 이전</button>
            {Array.from({ length: totalPages }, (_, i) => i + 1)
              .filter(p => p === 1 || p === totalPages || Math.abs(p - page) <= 2)
              .reduce<(number|string)[]>((acc, p, i, arr) => {
                if (i > 0 && p - (arr[i-1] as number) > 1) acc.push('...');
                acc.push(p);
                return acc;
              }, [])
              .map((p, i) =>
                typeof p === 'string' ? <span key={`e${i}`} className="px-1 text-gray-400">...</span> :
                <button key={p} onClick={() => setPage(p)}
                  className={`w-8 h-8 rounded ${page === p ? 'bg-primary text-white font-bold' : 'hover:bg-gray-50 border'}`}>{p}</button>
              )}
            <button onClick={() => setPage(p => Math.min(totalPages, p+1))} disabled={page === totalPages}
              className="px-3 py-1.5 border rounded hover:bg-gray-50 disabled:opacity-30 disabled:cursor-not-allowed">다음 →</button>
          </div>
        </div>
      )}
    </div>
  );
}
