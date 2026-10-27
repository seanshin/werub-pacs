'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { formatDate, formatPatientName, ModalityBadge } from '@/lib/format';
import ConfirmDialog from '@/components/ConfirmDialog';
import Breadcrumb from '@/components/ui/Breadcrumb';

type ArchiveItem = {
  id: string;
  study_instance_uid: string;
  series_instance_uid: string | null;
  patient_id: string;
  patient_name: string;
  patient_sex: string | null;
  modality: string | null;
  study_date: string | null;
  study_description: string | null;
  series_count: number;
  instance_count: number;
  reason: string;
  note: string | null;
  rejection_code: string | null;
  archived_by_name: string | null;
  archived_at: string;
  storage_type: string;
  file_size_bytes: number;
  is_restorable: boolean;
  restored_at: string | null;
  restored_by_name: string | null;
  retention_expires_at: string | null;
  has_thumbnail: boolean;
  original_report_id: string | null;
};

type ArchiveStats = {
  total: number;
  active: number;
  restored: number;
  this_month: number;
  expiring_soon: number;
  by_reason: Record<string, number>;
  by_modality: Record<string, number>;
  total_size_gb: number;
};

const reasonLabel: Record<string, string> = {
  quality_reject: '화질 불량',
  patient_safety: '환자 안전',
  worklist_error: '오더 오류',
  retention_expired: '보존기간 만료',
  superseded: '재촬영 대체',
  storage_migration: '스토리지 이동',
  manual: '수동 아카이브',
};

const reasonColor: Record<string, string> = {
  quality_reject: 'bg-red-100 text-red-700',
  patient_safety: 'bg-orange-100 text-orange-700',
  worklist_error: 'bg-yellow-100 text-yellow-700',
  superseded: 'bg-blue-100 text-blue-700',
  storage_migration: 'bg-gray-100 text-gray-700',
  manual: 'bg-purple-100 text-purple-700',
  retention_expired: 'bg-gray-100 text-gray-600',
};

export default function ArchivePage() {
  const [archives, setArchives] = useState<ArchiveItem[]>([]);
  const [stats, setStats] = useState<ArchiveStats | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');
  const [search, setSearch] = useState('');
  const [includeRestored, setIncludeRestored] = useState(false);
  const [selected, setSelected] = useState<ArchiveItem | null>(null);
  const [dicomTags, setDicomTags] = useState<Record<string, any> | null>(null);
  const [restoreId, setRestoreId] = useState<string | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [thumbnailUrl, setThumbnailUrl] = useState<string | null>(null);
  const [msg, setMsg] = useState('');
  const PAGE_SIZE = 20;

  const loadData = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
      if (filter) params.set('reason', filter);
      if (search) params.set('patient_id', search);
      if (includeRestored) params.set('include_restored', 'true');
      const data = await apiFetch<{ total: number; archives: ArchiveItem[] }>(`/api/v1/archive?${params}`);
      setArchives(data.archives);
      setTotal(data.total);

      const s = await apiFetch<ArchiveStats>('/api/v1/archive/statistics');
      setStats(s);
    } catch (e: any) {
      setMsg(`데이터 로드 실패: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadData(); }, [page, filter, includeRestored]);

  const handleRestore = async (id: string) => {
    try {
      await apiFetch(`/api/v1/archive/${id}/restore`, { method: 'POST', body: JSON.stringify({}) });
      setMsg('복원되었습니다.');
      setRestoreId(null);
      setSelected(null);
      await loadData();
    } catch (e: any) {
      setMsg(`복원 실패: ${e.message}`);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await apiFetch(`/api/v1/archive/${id}`, { method: 'DELETE' });
      setMsg('영구 삭제되었습니다.');
      setDeleteId(null);
      setSelected(null);
      await loadData();
    } catch (e: any) {
      setMsg(`삭제 실패: ${e.message}`);
    }
  };

  const loadThumbnail = async (item: ArchiveItem) => {
    if (!item.has_thumbnail) { setThumbnailUrl(null); return; }
    try {
      const token = localStorage.getItem('pacs_token');
      const res = await fetch(`/pacs-api/api/v1/archive/${item.id}/thumbnail`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        const blob = await res.blob();
        setThumbnailUrl(URL.createObjectURL(blob));
      } else {
        setThumbnailUrl(null);
      }
    } catch { setThumbnailUrl(null); }
  };

  const handleViewTags = async (item: ArchiveItem) => {
    try {
      const data = await apiFetch<{ tags: Record<string, any> }>(`/api/v1/archive/${item.id}/dicom-tags`);
      setDicomTags(data.tags);
    } catch {
      setDicomTags({});
    }
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div>
      <Breadcrumb items={[{ label: 'PACS', href: '/' }, { label: '아카이브' }]} />
      <h1 className="text-2xl font-bold mb-4">DICOM 아카이브 관리</h1>

      {msg && (
        <div className="bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 px-4 py-2 rounded mb-4 text-sm">
          {msg}
          <button onClick={() => setMsg('')} className="ml-2 text-blue-500">&times;</button>
        </div>
      )}

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-6">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border p-4 text-center">
            <p className="text-sm text-gray-500">총 아카이브</p>
            <p className="text-2xl font-bold">{stats.active}</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border p-4 text-center">
            <p className="text-sm text-gray-500">이번 달</p>
            <p className="text-2xl font-bold text-blue-600">{stats.this_month}</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border p-4 text-center">
            <p className="text-sm text-gray-500">복원됨</p>
            <p className="text-2xl font-bold text-green-600">{stats.restored}</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border p-4 text-center">
            <p className="text-sm text-gray-500">만료 임박 (90일)</p>
            <p className="text-2xl font-bold text-orange-600">{stats.expiring_soon}</p>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border p-4 text-center">
            <p className="text-sm text-gray-500">총 용량</p>
            <p className="text-2xl font-bold">{stats.total_size_gb} GB</p>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <select value={filter} onChange={e => { setFilter(e.target.value); setPage(1); }}
          className="border rounded px-3 py-1.5 text-sm dark:bg-gray-800 dark:border-gray-600">
          <option value="">전체 사유</option>
          {Object.entries(reasonLabel).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
        <input value={search} onChange={e => setSearch(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && loadData()}
          placeholder="환자 ID 검색"
          className="border rounded px-3 py-1.5 text-sm w-40 dark:bg-gray-800 dark:border-gray-600" />
        <button onClick={() => loadData()} className="bg-primary text-white px-3 py-1.5 rounded text-sm">검색</button>
        <label className="flex items-center gap-1 text-sm text-gray-500 ml-auto">
          <input type="checkbox" checked={includeRestored} onChange={e => { setIncludeRestored(e.target.checked); setPage(1); }} />
          복원된 항목 포함
        </label>
      </div>

      {/* Table */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 dark:bg-gray-700 text-left text-xs text-gray-500 dark:text-gray-400 uppercase">
              <th className="px-3 py-2">환자</th>
              <th className="px-3 py-2">모달리티</th>
              <th className="px-3 py-2 hidden sm:table-cell">검사</th>
              <th className="px-3 py-2">사유</th>
              <th className="px-3 py-2 hidden md:table-cell">작업자</th>
              <th className="px-3 py-2 hidden lg:table-cell">아카이브 일시</th>
              <th className="px-3 py-2 text-center">상태</th>
              <th className="px-3 py-2 text-center">작업</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-gray-400">로딩 중...</td></tr>
            ) : archives.length === 0 ? (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-gray-400">아카이브된 영상이 없습니다</td></tr>
            ) : archives.map(a => (
              <tr key={a.id}
                className={`border-t cursor-pointer transition ${a.restored_at ? 'opacity-50 bg-green-50 dark:bg-green-900/10' : 'hover:bg-gray-50 dark:hover:bg-gray-700'} ${selected?.id === a.id ? 'bg-blue-50 dark:bg-blue-900/20' : ''}`}
                onClick={() => {
                  if (selected?.id === a.id) { setSelected(null); setDicomTags(null); setThumbnailUrl(null); }
                  else { setSelected(a); setDicomTags(null); setThumbnailUrl(null); loadThumbnail(a); }
                }}>
                <td className="px-3 py-2">
                  <p className="font-medium">{formatPatientName(a.patient_name)}</p>
                  <p className="text-xs text-gray-400">{a.patient_id}</p>
                </td>
                <td className="px-3 py-2">
                  {a.modality ? <ModalityBadge modality={a.modality} /> : '-'}
                  <span className="text-[10px] text-gray-400 ml-1">{a.series_count}s/{a.instance_count}i</span>
                </td>
                <td className="px-3 py-2 text-gray-600 hidden sm:table-cell max-w-[150px] truncate">{a.study_description || '-'}</td>
                <td className="px-3 py-2">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${reasonColor[a.reason] || 'bg-gray-100'}`}>
                    {reasonLabel[a.reason] || a.reason}
                  </span>
                </td>
                <td className="px-3 py-2 text-gray-500 text-xs hidden md:table-cell">{a.archived_by_name?.split(' ')[0] || '-'}</td>
                <td className="px-3 py-2 text-gray-500 text-xs hidden lg:table-cell whitespace-nowrap">{formatDate(a.archived_at?.slice(0, 10))}</td>
                <td className="px-3 py-2 text-center">
                  {a.restored_at ? (
                    <span className="text-[10px] bg-green-100 text-green-700 px-1.5 py-0.5 rounded font-medium">복원됨</span>
                  ) : (
                    <span className="text-[10px] bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded font-medium">보관 중</span>
                  )}
                </td>
                <td className="px-3 py-2 text-center" onClick={e => e.stopPropagation()}>
                  <div className="flex gap-1 justify-center">
                    {a.has_thumbnail && (
                      <a href={`/pacs-api/api/v1/archive/${a.id}/thumbnail`} target="_blank"
                        className="text-blue-500 hover:text-blue-700 text-xs" title="썸네일">
                        🖼
                      </a>
                    )}
                    {!a.restored_at && a.is_restorable && (
                      <button onClick={() => setRestoreId(a.id)}
                        className="text-green-600 hover:text-green-800 text-xs font-semibold" title="복원">
                        복원
                      </button>
                    )}
                    <button onClick={() => setDeleteId(a.id)}
                      className="text-red-500 hover:text-red-700 text-xs font-semibold" title="영구 삭제">
                      삭제
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-4 text-sm">
          <button onClick={() => setPage(p => Math.max(1, p-1))} disabled={page === 1}
            className="px-3 py-1 border rounded disabled:opacity-30">&lt;</button>
          <span className="text-gray-500">{page} / {totalPages} ({total}건)</span>
          <button onClick={() => setPage(p => Math.min(totalPages, p+1))} disabled={page === totalPages}
            className="px-3 py-1 border rounded disabled:opacity-30">&gt;</button>
        </div>
      )}

      {/* Detail Side Panel */}
      {selected && (
        <div className="fixed inset-0 bg-black/50 z-50 flex justify-end" onClick={() => { setSelected(null); setDicomTags(null); setThumbnailUrl(null); }}>
          <div className="bg-white dark:bg-gray-800 w-full max-w-md h-full overflow-y-auto shadow-xl p-6" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-lg font-bold">아카이브 상세</h2>
              <button onClick={() => { setSelected(null); setDicomTags(null); setThumbnailUrl(null); }} className="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
            </div>

            {/* Thumbnail */}
            {thumbnailUrl && (
              <div className="mb-4 bg-black rounded-lg overflow-hidden flex justify-center">
                <img src={thumbnailUrl} alt="thumbnail" className="max-h-48 object-contain" />
              </div>
            )}

            {/* Info */}
            <div className="space-y-3 text-sm">
              <div className="bg-gray-50 dark:bg-gray-700 rounded p-3">
                <p className="font-semibold text-base">{formatPatientName(selected.patient_name)}</p>
                <p className="text-gray-500 text-xs">{selected.patient_id} · {selected.patient_sex || '?'}</p>
              </div>

              <div className="grid grid-cols-2 gap-2 text-xs">
                <div><span className="text-gray-500">모달리티:</span> {selected.modality || '-'}</div>
                <div><span className="text-gray-500">검사일:</span> {formatDate(selected.study_date)}</div>
                <div><span className="text-gray-500">시리즈:</span> {selected.series_count}</div>
                <div><span className="text-gray-500">인스턴스:</span> {selected.instance_count}</div>
              </div>

              <div className="border-t pt-3">
                <p className="text-xs font-semibold text-gray-500 mb-1">아카이브 정보</p>
                <div className="space-y-1 text-xs">
                  <p><span className="text-gray-500">사유:</span> <span className={`px-1.5 py-0.5 rounded ${reasonColor[selected.reason] || ''}`}>{reasonLabel[selected.reason] || selected.reason}</span></p>
                  {selected.note && <p><span className="text-gray-500">메모:</span> {selected.note}</p>}
                  {selected.rejection_code && <p><span className="text-gray-500">DICOM 코드:</span> {selected.rejection_code}</p>}
                  <p><span className="text-gray-500">작업자:</span> {selected.archived_by_name}</p>
                  <p><span className="text-gray-500">일시:</span> {selected.archived_at?.replace('T', ' ').slice(0, 19)}</p>
                  <p><span className="text-gray-500">보존 만료:</span> {selected.retention_expires_at?.slice(0, 10) || '-'}</p>
                  {selected.restored_at && (
                    <p className="text-green-600"><span className="text-gray-500">복원:</span> {selected.restored_at.replace('T', ' ').slice(0, 19)} ({selected.restored_by_name})</p>
                  )}
                </div>
              </div>

              {/* DICOM Tags */}
              <div className="border-t pt-3">
                <button onClick={() => handleViewTags(selected)}
                  className="text-xs text-blue-600 hover:text-blue-800 font-semibold">
                  {dicomTags ? '▼ DICOM 태그' : '▶ DICOM 태그 보기'}
                </button>
                {dicomTags && (
                  <div className="mt-2 bg-gray-50 dark:bg-gray-700 rounded p-3 text-xs max-h-48 overflow-y-auto font-mono">
                    {Object.entries(dicomTags).map(([k, v]) => (
                      <p key={k}><span className="text-gray-500">{k}:</span> {String(v)}</p>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Actions */}
            <div className="space-y-2 mt-6 pt-4 border-t">
              <a href={`/werub-viewer/viewer?StudyInstanceUIDs=${selected.study_instance_uid}`} target="_blank"
                className="block w-full text-center bg-blue-600 text-white py-2 rounded text-sm font-semibold hover:bg-blue-700">
                🖥️ 뷰어로 열기
              </a>
              <div className="flex gap-2">
                {!selected.restored_at && selected.is_restorable && (
                  <button onClick={() => setRestoreId(selected.id)}
                    className="flex-1 bg-green-600 text-white py-2 rounded text-sm font-semibold hover:bg-green-700">
                    복원
                  </button>
                )}
                <button onClick={() => setDeleteId(selected.id)}
                  className="flex-1 bg-red-600 text-white py-2 rounded text-sm font-semibold hover:bg-red-700">
                  영구 삭제
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Confirm Dialogs */}
      <ConfirmDialog
        open={!!restoreId}
        title="아카이브 복원"
        description="이 영상을 복원하시겠습니까? Orthanc에 재업로드가 필요할 수 있습니다."
        confirmLabel="복원"
        onConfirm={() => restoreId && handleRestore(restoreId)}
        onCancel={() => setRestoreId(null)}
      />
      <ConfirmDialog
        open={!!deleteId}
        title="영구 삭제"
        description="정말 영구 삭제하시겠습니까? 보존기간이 만료된 아카이브만 삭제 가능합니다. 이 작업은 되돌릴 수 없습니다."
        confirmLabel="영구 삭제"
        onConfirm={() => deleteId && handleDelete(deleteId)}
        onCancel={() => setDeleteId(null)}
      />
    </div>
  );
}
