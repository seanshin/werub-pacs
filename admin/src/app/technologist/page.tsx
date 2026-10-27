'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { formatDate, formatPatientName, ModalityBadge } from '@/lib/format';
import ViewerButton from '@/components/ViewerButton';

type Study = {
  orthanc_id: string; study_instance_uid: string;
  patient_name: string; patient_id: string; modality: string;
  study_description: string; study_date: string; study_time: string;
  read_status: string; urgency: string; series_count: number;
  accession_number: string;
};

type Transfer = {
  orthanc_id: string; study_uid: string; patient_id: string;
  patient_name: string; modality: string; study_date: string;
  study_description: string; station_name: string; received_at: string;
  series_count: number;
};

type ModalitySummary = { by_modality: Record<string, number>; by_station: Record<string, number>; total: number };

export default function TechnologistPage() {
  const [tab, setTab] = useState<'today' | 'qc' | 'transfers' | 'equipment'>('today');
  const [studies, setStudies] = useState<Study[]>([]);
  const [transfers, setTransfers] = useState<Transfer[]>([]);
  const [summary, setSummary] = useState<ModalitySummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      apiFetch<{ queue: Study[] }>('/api/v1/dashboard/reading-queue'),
      apiFetch<{ transfers: Transfer[] }>('/api/v1/equipment/transfers?limit=50'),
      apiFetch<ModalitySummary>('/api/v1/equipment/summary'),
    ]).then(([q, t, s]) => {
      setStudies(q.queue || []);
      setTransfers(t.transfers || []);
      setSummary(s);
    }).finally(() => setLoading(false));

    const iv = setInterval(() => {
      apiFetch<{ queue: Study[] }>('/api/v1/dashboard/reading-queue').then(d => setStudies(d.queue || []));
    }, 30000);
    return () => clearInterval(iv);
  }, []);

  const todayStudies = studies;
  const qcNeeded = studies.filter(s => s.read_status === 'unread' && (!s.patient_name || !s.study_description));
  const unreadCount = studies.filter(s => s.read_status === 'unread').length;
  const completedCount = studies.filter(s => s.read_status === 'final').length;

  const statusBadge: Record<string, string> = {
    unread: 'bg-yellow-100 text-yellow-800', draft: 'bg-blue-100 text-blue-800',
    preliminary: 'bg-purple-100 text-purple-800', final: 'bg-green-100 text-green-800',
  };
  const statusLabel: Record<string, string> = {
    unread: '판독 대기', draft: '작성 중', preliminary: '예비 판독', final: '판독 완료',
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">방사선사 워크스테이션</h1>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-gray-500">전체 {studies.length}건</span>
          <span className="bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded font-medium">대기 {unreadCount}</span>
          <span className="bg-green-100 text-green-800 px-2 py-0.5 rounded font-medium">완료 {completedCount}</span>
          {qcNeeded.length > 0 && <span className="bg-red-100 text-red-800 px-2 py-0.5 rounded font-medium">QC {qcNeeded.length}</span>}
        </div>
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          <div className="bg-white rounded-lg border p-3">
            <div className="text-xs text-gray-500">오늘 촬영</div>
            <div className="text-2xl font-bold">{summary.total}</div>
          </div>
          {Object.entries(summary.by_modality).map(([mod, count]) => (
            <div key={mod} className="bg-white rounded-lg border p-3">
              <div className="text-xs text-gray-500">{mod}</div>
              <div className="text-2xl font-bold">{count}</div>
            </div>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 mb-4">
        {[
          { key: 'today' as const, label: '오늘 검사', count: studies.length },
          { key: 'qc' as const, label: 'QC 필요', count: qcNeeded.length },
          { key: 'transfers' as const, label: '전송 이력', count: transfers.length },
          { key: 'equipment' as const, label: '장비 현황' },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-3 py-1.5 rounded text-sm font-medium transition ${tab === t.key
              ? 'bg-primary text-white' : 'bg-white border text-gray-600 hover:bg-gray-50'}`}>
            {t.label} {t.count !== undefined && `(${t.count})`}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="text-center py-12 text-gray-400">로딩 중...</div>
      ) : (
        <>
          {/* 오늘 검사 / QC 필요 */}
          {(tab === 'today' || tab === 'qc') && (
            <div className="bg-white rounded-lg border shadow-sm overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-gray-500">
                  <tr>
                    <th className="px-3 py-2 text-left">상태</th>
                    <th className="px-3 py-2 text-left">환자명</th>
                    <th className="px-3 py-2 text-left">환자번호</th>
                    <th className="px-3 py-2 text-left">모달리티</th>
                    <th className="px-3 py-2 text-left">검사설명</th>
                    <th className="px-3 py-2 text-left">검사일</th>
                    <th className="px-3 py-2 text-left">시리즈</th>
                    <th className="px-3 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {(tab === 'qc' ? qcNeeded : todayStudies).map((item, i) => (
                    <tr key={i} className={`border-t hover:bg-gray-50 ${item.urgency === 'urgent' ? 'bg-red-50' : ''}`}>
                      <td className="px-3 py-2">
                        <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${statusBadge[item.read_status] || 'bg-gray-100'}`}>
                          {statusLabel[item.read_status] || item.read_status}
                        </span>
                      </td>
                      <td className="px-3 py-2 font-medium">{formatPatientName(item.patient_name) || <span className="text-red-500">누락</span>}</td>
                      <td className="px-3 py-2 text-gray-500">{item.patient_id}</td>
                      <td className="px-3 py-2"><ModalityBadge modality={item.modality} /></td>
                      <td className="px-3 py-2 text-gray-600">{item.study_description || <span className="text-red-500">누락</span>}</td>
                      <td className="px-3 py-2 text-gray-500">{formatDate(item.study_date)}</td>
                      <td className="px-3 py-2 text-gray-500">{item.series_count}</td>
                      <td className="px-3 py-2">
                        <div className="flex gap-1 justify-end">
                          <ViewerButton url={`/werub-viewer/viewer?StudyInstanceUIDs=${item.study_instance_uid}`} label="뷰어" size="sm" />
                        </div>
                      </td>
                    </tr>
                  ))}
                  {(tab === 'qc' ? qcNeeded : todayStudies).length === 0 && (
                    <tr><td colSpan={8} className="px-4 py-12 text-center text-gray-400">
                      {tab === 'qc' ? 'QC가 필요한 검사가 없습니다' : '검사가 없습니다'}
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          {/* 전송 이력 */}
          {tab === 'transfers' && (
            <div className="bg-white rounded-lg border shadow-sm overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-gray-500">
                  <tr>
                    <th className="px-3 py-2 text-left">수신 시각</th>
                    <th className="px-3 py-2 text-left">환자번호</th>
                    <th className="px-3 py-2 text-left">환자명</th>
                    <th className="px-3 py-2 text-left">모달리티</th>
                    <th className="px-3 py-2 text-left">검사설명</th>
                    <th className="px-3 py-2 text-left">장비</th>
                    <th className="px-3 py-2 text-left">시리즈</th>
                  </tr>
                </thead>
                <tbody>
                  {transfers.map((t, i) => (
                    <tr key={i} className="border-t hover:bg-gray-50">
                      <td className="px-3 py-2 text-gray-500 whitespace-nowrap">{t.received_at?.replace('T', ' ').slice(0, 17)}</td>
                      <td className="px-3 py-2">{t.patient_id}</td>
                      <td className="px-3 py-2 font-medium">{formatPatientName(t.patient_name)}</td>
                      <td className="px-3 py-2"><ModalityBadge modality={t.modality} /></td>
                      <td className="px-3 py-2 text-gray-600">{t.study_description || '-'}</td>
                      <td className="px-3 py-2 text-gray-500">{t.station_name || '-'}</td>
                      <td className="px-3 py-2 text-gray-500">{t.series_count}</td>
                    </tr>
                  ))}
                  {transfers.length === 0 && (
                    <tr><td colSpan={7} className="px-4 py-12 text-center text-gray-400">전송 이력이 없습니다</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          {/* 장비 현황 */}
          {tab === 'equipment' && summary && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="bg-white rounded-lg border p-4">
                <h3 className="font-semibold mb-3">모달리티별 건수</h3>
                {Object.keys(summary.by_modality).length === 0 ? (
                  <p className="text-gray-400 text-sm">오늘 수신된 검사가 없습니다</p>
                ) : (
                  <div className="space-y-2">
                    {Object.entries(summary.by_modality).sort((a, b) => b[1] - a[1]).map(([mod, count]) => (
                      <div key={mod} className="flex items-center justify-between">
                        <span className="flex items-center gap-2">
                          <ModalityBadge modality={mod} />
                          <span className="text-sm text-gray-600">{mod}</span>
                        </span>
                        <span className="font-semibold">{count}건</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="bg-white rounded-lg border p-4">
                <h3 className="font-semibold mb-3">장비별 건수</h3>
                {Object.keys(summary.by_station).length === 0 ? (
                  <p className="text-gray-400 text-sm">장비 정보가 없습니다</p>
                ) : (
                  <div className="space-y-2">
                    {Object.entries(summary.by_station).sort((a, b) => b[1] - a[1]).map(([station, count]) => (
                      <div key={station} className="flex items-center justify-between">
                        <span className="text-sm text-gray-600">{station}</span>
                        <span className="font-semibold">{count}건</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
