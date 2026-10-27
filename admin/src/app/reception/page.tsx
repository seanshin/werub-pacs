'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch, getUser } from '@/lib/api';

type Reception = {
  study_uid: string | null;
  orthanc_id: string | null;
  received_at: string | null;
  is_stable: boolean | null;
  patient_name: string;
  patient_id: string;
  study_date: string;
  study_description: string;
  modality: string;
  series_count: number;
  origin: string;
  upload_method: string | null;
  source_ae_title: string | null;
  source_institution: string | null;
  source_device: string | null;
};

const originLabel: Record<string, { label: string; cls: string }> = {
  modality: { label: '모달리티', cls: 'bg-blue-100 text-blue-700' },
  external_pacs: { label: '외부PACS', cls: 'bg-purple-100 text-purple-700' },
  cd_import: { label: 'CD', cls: 'bg-amber-100 text-amber-700' },
  patient_portal: { label: '환자포털', cls: 'bg-emerald-100 text-emerald-700' },
  kiosk: { label: '키오스크', cls: 'bg-teal-100 text-teal-700' },
  upload: { label: '업로드', cls: 'bg-slate-100 text-slate-700' },
  migration: { label: '마이그레이션', cls: 'bg-slate-100 text-slate-500' },
  unknown: { label: '미상', cls: 'bg-slate-100 text-slate-400' },
};

function fmtTime(iso: string | null) {
  if (!iso) return '-';
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return iso;
  }
}

export default function ReceptionMonitorPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [studies, setStudies] = useState<Reception[]>([]);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [auto, setAuto] = useState(true);
  const [err, setErr] = useState(false);
  const timer = useRef<any>(null);

  useEffect(() => {
    const u = getUser();
    if (!u || !['admin', 'radiologist', 'technologist'].includes(u.role)) { router.replace('/'); return; }
    setUser(u);
  }, []);

  const load = useCallback(() => {
    apiFetch<{ studies: Reception[]; error?: string }>(`/api/v1/reception/recent?limit=40`)
      .then(d => { setStudies(d.studies || []); setErr(!!d.error); setUpdatedAt(new Date()); })
      .catch(() => setErr(true));
  }, []);

  useEffect(() => {
    if (!user) return;
    load();
  }, [user, load]);

  useEffect(() => {
    if (!user) return;
    if (auto) {
      timer.current = setInterval(load, 15000);
      return () => clearInterval(timer.current);
    }
  }, [user, auto, load]);

  if (!user) return <div className="text-center py-20 text-slate-400">로딩 중...</div>;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold">수신 모니터</h1>
          <p className="text-sm text-slate-500 mt-1">최근 도착한 DICOM 영상 (C-STORE · 업로드 · 외부 PACS)</p>
        </div>
        <div className="flex items-center gap-3 text-sm">
          {updatedAt && <span className="text-slate-400">갱신 {updatedAt.toLocaleTimeString('ko-KR')}</span>}
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} />
            <span className={auto ? 'text-emerald-600 font-medium' : 'text-slate-400'}>
              자동 새로고침{auto && <span className="ml-1 inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />}
            </span>
          </label>
          <button onClick={load} className="px-3 py-1.5 rounded-xl border bg-white hover:bg-slate-50">새로고침</button>
        </div>
      </div>

      {err && (
        <div className="bg-amber-50 border border-amber-200 text-amber-700 rounded-xl px-4 py-3 text-sm">
          Orthanc에서 수신 현황을 가져오지 못했습니다. 잠시 후 다시 시도됩니다.
        </div>
      )}

      <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left">수신 시각</th>
                <th className="px-4 py-3 text-left">환자</th>
                <th className="px-4 py-3 text-left">검사</th>
                <th className="px-3 py-3 text-center">모달리티</th>
                <th className="px-3 py-3 text-right">시리즈</th>
                <th className="px-4 py-3 text-left">출처</th>
                <th className="px-3 py-3 text-center">상태</th>
                <th className="px-3 py-3 text-center">뷰어</th>
              </tr>
            </thead>
            <tbody>
              {studies.length === 0 ? (
                <tr><td colSpan={8} className="text-center py-12 text-slate-400">수신된 영상 없음</td></tr>
              ) : studies.map(s => {
                const o = originLabel[s.origin] || originLabel.unknown;
                return (
                  <tr key={s.orthanc_id || s.study_uid || Math.random()} className="border-t hover:bg-slate-50">
                    <td className="px-4 py-3 whitespace-nowrap font-medium text-slate-700">{fmtTime(s.received_at)}</td>
                    <td className="px-4 py-3">
                      <div className="font-medium">{s.patient_name || '(미상)'}</div>
                      <div className="text-xs text-slate-400">{s.patient_id}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-600 max-w-[220px] truncate">{s.study_description || '-'}</td>
                    <td className="px-3 py-3 text-center">
                      {s.modality ? <span className="text-xs font-bold text-blue-700 bg-blue-100 px-2 py-0.5 rounded">{s.modality}</span> : '-'}
                    </td>
                    <td className="px-3 py-3 text-right text-slate-500">{s.series_count}</td>
                    <td className="px-4 py-3">
                      <span className={`text-[11px] font-medium px-2 py-0.5 rounded ${o.cls}`}>{o.label}</span>
                      {(s.source_ae_title || s.source_institution) && (
                        <span className="ml-1.5 text-xs text-slate-400">{s.source_ae_title || s.source_institution}</span>
                      )}
                    </td>
                    <td className="px-3 py-3 text-center">
                      {s.is_stable
                        ? <span className="text-[11px] text-emerald-600">완료</span>
                        : <span className="text-[11px] text-amber-600">수신 중</span>}
                    </td>
                    <td className="px-3 py-3 text-center">
                      {s.study_uid && (
                        <a href={`/pacs-admin/reading/view?study=${s.study_uid}`}
                          className="text-blue-600 hover:underline text-xs">열기</a>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      <p className="text-xs text-slate-400">※ Orthanc 최종 갱신시각(LastUpdate) 기준. 출처는 자동 감지된 분류(study_provenance)입니다.</p>
    </div>
  );
}
