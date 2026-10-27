'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { formatPatientName, ModalityBadge } from '@/lib/format';
import ViewerButton from '@/components/ViewerButton';
import Breadcrumb from '@/components/ui/Breadcrumb';
import EmptyState from '@/components/ui/EmptyState';

type Study = {
  study_instance_uid: string;
  patient_id: string;
  patient_name: string;
  modality: string;
  study_description: string | null;
  read_status: string;
  report_id: string | null;
  viewer_url: string;
  report_url: string | null;
};

const STATUS_BADGE: Record<string, string> = {
  completed: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  final: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  preliminary: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  unread: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
};
const STATUS_LABEL: Record<string, string> = {
  completed: '판독 완료', final: '판독 완료', preliminary: '예비 판독', unread: '판독 대기',
};

const PAGE_SIZE = 20;
const FILTERS = [
  { key: 'all', label: '전체' },
  { key: 'unread', label: '판독 대기' },
  { key: 'completed', label: '판독 완료' },
];

export default function MyPatientsPage() {
  const [studies, setStudies] = useState<Study[]>([]);
  const [status, setStatus] = useState('all');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setErr('');
    try {
      const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
      if (status !== 'all') params.set('status', status);
      if (search) params.set('search', search);
      const res: any = await apiFetch(`/api/v1/my-patients?${params}`);
      setStudies(res.studies || []);
    } catch (e: any) {
      setErr(e?.message || '목록 로드 실패');
      setStudies([]);
    } finally {
      setLoading(false);
    }
  }, [page, status, search]);

  useEffect(() => { load(); }, [load]);

  const handleSearch = (e: React.FormEvent) => { e.preventDefault(); setPage(1); load(); };

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <Breadcrumb items={[{ label: '내 환자' }]} />
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">내 환자</h1>
      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">담당 환자의 영상·판독 결과를 조회합니다.</p>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button key={f.key}
            onClick={() => { setStatus(f.key); setPage(1); }}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
              status === f.key
                ? 'bg-blue-600 text-white'
                : 'border border-gray-300 text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700'
            }`}>
            {f.label}
          </button>
        ))}
        <form onSubmit={handleSearch} className="ml-auto">
          <input type="text" value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="🔍 환자명·번호 검색"
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100" />
        </form>
      </div>

      <div className="mt-4 overflow-x-auto rounded-xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <table className="min-w-full text-sm">
          <thead className="border-b border-gray-200 text-gray-500 dark:border-gray-700 dark:text-gray-400">
            <tr>
              <th className="px-4 py-3 text-left whitespace-nowrap">상태</th>
              <th className="px-4 py-3 text-left whitespace-nowrap">환자명</th>
              <th className="px-4 py-3 text-left hidden sm:table-cell">환자번호</th>
              <th className="px-4 py-3 text-left">모달리티</th>
              <th className="px-4 py-3 text-left hidden md:table-cell">검사설명</th>
              <th className="px-4 py-3 text-right">조회</th>
            </tr>
          </thead>
          <tbody>
            {!loading && studies.length === 0 && (
              <tr><td colSpan={6} className="py-10">
                <EmptyState title={err || (search ? `"${search}" 검색 결과가 없습니다` : '담당 환자 영상이 없습니다')} />
              </td></tr>
            )}
            {studies.map((s) => (
              <tr key={s.study_instance_uid} className="border-b border-gray-100 last:border-0 dark:border-gray-700">
                <td className="px-4 py-3 whitespace-nowrap">
                  <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${STATUS_BADGE[s.read_status] || 'bg-gray-100 text-gray-600'}`}>
                    {STATUS_LABEL[s.read_status] || s.read_status}
                  </span>
                </td>
                <td className="px-4 py-3 font-medium whitespace-nowrap text-gray-900 dark:text-gray-100">{formatPatientName(s.patient_name)}</td>
                <td className="px-4 py-3 text-gray-500 hidden sm:table-cell">{s.patient_id}</td>
                <td className="px-4 py-3"><ModalityBadge modality={s.modality} /></td>
                <td className="px-4 py-3 text-gray-500 hidden md:table-cell">{s.study_description || '-'}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1.5 whitespace-nowrap">
                    {s.report_url && (
                      <Link href={s.report_url}
                        className="rounded bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100 dark:bg-blue-900/40 dark:text-blue-300">
                        리포트
                      </Link>
                    )}
                    <ViewerButton url={`/werub-viewer/viewer?StudyInstanceUIDs=${s.study_instance_uid}`} label="W" size="sm" modality={s.modality} />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex items-center justify-between">
        <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1 || loading}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm disabled:opacity-40 dark:border-gray-600 dark:text-gray-300">← 이전</button>
        <span className="text-sm text-gray-500">{page} 페이지</span>
        <button onClick={() => setPage((p) => p + 1)} disabled={studies.length < PAGE_SIZE || loading}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm disabled:opacity-40 dark:border-gray-600 dark:text-gray-300">다음 →</button>
      </div>
    </div>
  );
}
