'use client';

import { StudyInfo } from './types';

function InfoChip({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div>
      <div className="text-[10px] text-slate-400 uppercase tracking-wider">{label}</div>
      <div className={`font-medium ${accent ? 'text-blue-700' : 'text-slate-700'}`}>{value}</div>
    </div>
  );
}

export default function StudyInfoBar({ studyInfo, studyUID, viewerOpened, onOpenViewer, onOpenWithPrior, priorCount, mode }: {
  studyInfo: StudyInfo | null; studyUID: string; viewerOpened: boolean;
  onOpenViewer: (type: 'werub' | 'ohif') => void; onOpenWithPrior?: () => void;
  priorCount?: number; mode: string;
}) {
  const formatName = (name: string) => name?.replace(/\^+/g, ' ').replace(/\s+/g, ' ').trim() || '(이름 없음)';
  const formatDate = (d: string) => {
    if (!d) return '-';
    const s = d.replace(/[^0-9]/g, '');
    return s.length === 8 ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}` : d;
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4">
      <div className="flex items-center justify-between">
        {/* Patient Info */}
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-slate-100 rounded-full flex items-center justify-center">
              <svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" /></svg>
            </div>
            <div>
              <h2 className="font-bold text-slate-900 text-lg leading-tight">
                {studyInfo ? formatName(studyInfo.patient_name) : '...'}
              </h2>
              <span className="text-xs text-slate-500">{studyInfo?.patient_id || '-'}</span>
            </div>
          </div>

          <div className="h-8 w-px bg-slate-200" />

          <div className="flex items-center gap-5 text-sm">
            {studyInfo?.modality && (
              <InfoChip label="모달리티" value={studyInfo.modality} accent />
            )}
            <InfoChip label="검사일" value={studyInfo ? formatDate(studyInfo.study_date) : '-'} />
            {studyInfo?.study_description && (
              <InfoChip label="검사" value={studyInfo.study_description} />
            )}
            {studyInfo?.accession_number && (
              <InfoChip label="접수번호" value={studyInfo.accession_number} />
            )}
            {studyInfo?.sla_level && studyInfo.sla_level !== 'normal' && (
              <div className={`px-2.5 py-1 rounded-lg text-xs font-bold ${
                studyInfo.sla_level === 'critical' ? 'bg-red-100 text-red-700 animate-pulse' : 'bg-amber-100 text-amber-700'
              }`}>
                SLA {studyInfo.sla_minutes}분
              </div>
            )}
          </div>
        </div>

        {/* Viewer Buttons */}
        <div className="flex items-center gap-2">
          <button onClick={() => onOpenViewer('werub')}
            className="bg-blue-600 text-white pl-4 pr-5 py-2.5 rounded-xl text-sm font-semibold hover:bg-blue-700 transition shadow-sm flex items-center gap-2">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" /></svg>
            {viewerOpened ? 'WeRU.B 다시 열기' : 'WeRU.B 뷰어'}
          </button>
          {priorCount && priorCount > 0 && onOpenWithPrior ? (
            <button onClick={onOpenWithPrior}
              className="bg-indigo-600 text-white px-4 py-2.5 rounded-xl text-sm font-semibold hover:bg-indigo-700 transition flex items-center gap-1.5">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" /></svg>
              이전 비교 ({priorCount})
            </button>
          ) : null}
          <button onClick={() => onOpenViewer('ohif')}
            className="bg-white text-slate-600 px-4 py-2.5 rounded-xl text-sm font-medium border border-slate-200 hover:bg-slate-50 transition">
            OHIF
          </button>
          <a href={`/pacs-admin/reading/view?study=${studyUID}&mode=${mode === 'dual' ? 'single' : 'dual'}`}
            className="bg-white text-slate-500 px-3 py-2.5 rounded-xl text-sm border border-slate-200 hover:bg-slate-50 transition" title={mode === 'dual' ? '단일 화면' : '듀얼 화면'}>
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" /></svg>
          </a>
        </div>
      </div>
    </div>
  );
}
