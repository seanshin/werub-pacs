'use client';

import Link from 'next/link';
import { useState, useRef, useEffect, RefObject } from 'react';
import { apiFetch } from '@/lib/api';
import { Report, Template } from './types';
import ExternalEsign from './ExternalEsign';

/* ─── Status Badge ─── */
function StatusBadge({ report }: { report: Report | null }) {
  if (!report) return <span className="px-2.5 py-1 rounded-lg text-xs font-semibold bg-blue-50 text-blue-600 border border-blue-100">새 리포트</span>;
  const config: Record<string, { bg: string; text: string; label: string }> = {
    final: { bg: 'bg-emerald-50 border-emerald-200', text: 'text-emerald-700', label: '판독 완료' },
    preliminary: { bg: 'bg-violet-50 border-violet-200', text: 'text-violet-700', label: '예비 판독' },
    draft: { bg: 'bg-amber-50 border-amber-200', text: 'text-amber-700', label: '작성 중' },
  };
  const c = config[report.status] || { bg: 'bg-slate-50 border-slate-200', text: 'text-slate-600', label: report.status };
  return (
    <div className="flex items-center gap-2">
      <span className={`px-2.5 py-1 rounded-lg text-xs font-semibold border ${c.bg} ${c.text}`}>{c.label}</span>
      {report.author_name?.startsWith('AI') && (
        <span className="px-2 py-1 rounded-lg text-xs font-semibold bg-violet-50 text-violet-600 border border-violet-200">AI 초안</span>
      )}
    </div>
  );
}

/* ─── Shortcut Hints ─── */
function ShortcutHints() {
  return (
    <div className="hidden lg:flex items-center gap-3 text-[10px] text-slate-400">
      <span><kbd className="px-1.5 py-0.5 bg-slate-100 rounded text-[10px] font-mono">Ctrl+S</kbd> 저장</span>
      <span><kbd className="px-1.5 py-0.5 bg-slate-100 rounded text-[10px] font-mono">Ctrl+Enter</kbd> 서명</span>
      <span><kbd className="px-1.5 py-0.5 bg-slate-100 rounded text-[10px] font-mono">N</kbd> 다음</span>
      <span><kbd className="px-1.5 py-0.5 bg-slate-100 rounded text-[10px] font-mono">?</kbd> 단축키</span>
    </div>
  );
}

/* ─── Field Section ─── */
function FieldSection({ label, required, children, className }: {
  label: string; required?: boolean; children: React.ReactNode; className?: string;
}) {
  return (
    <div className={className}>
      <label className="flex items-center gap-1.5 text-xs font-semibold text-slate-500 mb-2">
        {label}
        {required && <span className="text-red-400">*</span>}
      </label>
      {children}
    </div>
  );
}

/* ─── ReadOnly Field ─── */
function ReadOnlyField({ value, accent, className }: { value: string; accent?: boolean; className?: string }) {
  return (
    <div className={`rounded-xl p-4 text-sm whitespace-pre-wrap leading-relaxed border ${className || ''} ${
      accent ? 'bg-emerald-50/50 border-emerald-200 text-emerald-900' : 'bg-slate-50 border-slate-200 text-slate-700'
    }`}>
      {value || '-'}
    </div>
  );
}

/* ─── Dictation Button ─── */
function DictationButton({ targetField, setter, currentValue }: {
  targetField: string; setter: (v: string) => void; currentValue: string;
}) {
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<any>(null);

  const toggle = () => {
    if (listening) {
      recognitionRef.current?.stop(); recognitionRef.current = null; setListening(false); return;
    }
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) { alert('Chrome 또는 Edge 브라우저가 필요합니다.'); return; }
    const r = new SR();
    r.lang = 'ko-KR'; r.continuous = true; r.interimResults = false;
    r.onresult = (e: any) => {
      let text = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) text += e.results[i][0].transcript;
      }
      if (text) setter(currentValue + (currentValue ? ' ' : '') + text);
    };
    r.onerror = () => { setListening(false); recognitionRef.current = null; };
    r.onend = () => { if (recognitionRef.current) try { r.start(); } catch {} };
    recognitionRef.current = r; r.start(); setListening(true);
  };

  return (
    <button onClick={toggle} title={listening ? '음성 입력 중지' : `${targetField} 음성 입력`}
      className={`absolute top-2 right-2 px-2 py-1 rounded-lg text-xs transition ${
        listening ? 'bg-red-500 text-white animate-pulse shadow-lg' : 'bg-slate-100 text-slate-500 hover:bg-red-50 hover:text-red-600'
      }`}>
      {listening ? '중지' : '음성'}
    </button>
  );
}

/* ─── Report History ─── */
function ReportHistory({ studyUID, patientId }: { studyUID: string; patientId: string }) {
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [studyReports, patientStudies] = await Promise.all([
          apiFetch<{ results: any[] }>(`/api/v1/reports?study_uid=${studyUID}`).catch(() => ({ results: [] })),
          patientId ? apiFetch<{ results: any[] }>(`/api/v1/reports?patient_id=${patientId}&limit=20`).catch(() => ({ results: [] })) : Promise.resolve({ results: [] }),
        ]);
        const allReports = [...(studyReports.results || []), ...(patientStudies.results || [])];
        const unique = allReports.reduce((acc: any[], r: any) => {
          if (!acc.find((a: any) => a.id === r.id)) acc.push(r);
          return acc;
        }, []);
        unique.sort((a: any, b: any) => new Date(b.updated_at || b.created_at || 0).getTime() - new Date(a.updated_at || a.created_at || 0).getTime());
        setHistory(unique);
      } catch {}
      setLoading(false);
    })();
  }, [studyUID, patientId]);

  if (loading) return (
    <div className="p-6 text-center">
      <div className="w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto" />
    </div>
  );

  if (!history.length) return (
    <div className="p-6 text-center text-sm text-slate-400">
      <svg className="w-10 h-10 text-slate-200 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
      판독 이력이 없습니다
    </div>
  );

  const statusConfig: Record<string, { bg: string; label: string }> = {
    final: { bg: 'bg-emerald-100 text-emerald-700', label: '완료' },
    preliminary: { bg: 'bg-violet-100 text-violet-700', label: '예비' },
    draft: { bg: 'bg-amber-100 text-amber-700', label: '임시' },
  };

  return (
    <div className="p-4 space-y-3 max-h-[500px] overflow-y-auto">
      {history.map((r: any) => {
        const sc = statusConfig[r.status] || { bg: 'bg-slate-100 text-slate-600', label: r.status };
        const isCurrent = r.study_instance_uid === studyUID;
        return (
          <div key={r.id} className={`rounded-xl border p-3 text-sm transition ${isCurrent ? 'border-blue-300 bg-blue-50/50' : 'border-slate-200 hover:border-slate-300'}`}>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className={`px-2 py-0.5 rounded text-xs font-semibold ${sc.bg}`}>{sc.label}</span>
                {isCurrent && <span className="text-[10px] text-blue-600 font-semibold">현재 Study</span>}
              </div>
              <span className="text-xs text-slate-400">
                {r.signed_at ? new Date(r.signed_at).toLocaleString('ko-KR') : r.updated_at ? new Date(r.updated_at).toLocaleString('ko-KR') : '-'}
              </span>
            </div>
            {r.signed_by_name && <div className="text-xs text-slate-500 mb-1">판독의: {r.signed_by_name}</div>}
            {r.impression && (
              <div className="text-xs text-slate-600 bg-white rounded-lg p-2 border border-slate-100 line-clamp-3">
                {r.impression}
              </div>
            )}
            {!isCurrent && r.study_instance_uid && (
              <a href={`/pacs-admin/reading/view?study=${r.study_instance_uid}`}
                className="text-xs text-blue-600 hover:underline mt-1 inline-block">이 Study 보기 →</a>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ─── Main ReportEditor Component ─── */
export default function ReportEditor({
  report, findings, setFindings, impression, setImpression,
  recommendation, setRecommendation, dirty, setDirty,
  activeTab, setActiveTab, findingsRef, isFinal,
  saving, handleSave, handleSign, studyUID, studyInfo,
  nextStudyUID, goToNextStudy, consultOpen, setConsultOpen,
}: {
  report: Report | null;
  findings: string; setFindings: (v: string) => void;
  impression: string; setImpression: (v: string) => void;
  recommendation: string; setRecommendation: (v: string) => void;
  dirty: boolean; setDirty: (v: boolean) => void;
  activeTab: 'report' | 'history'; setActiveTab: (v: 'report' | 'history') => void;
  findingsRef: RefObject<HTMLTextAreaElement | null>;
  isFinal: boolean;
  saving: boolean; handleSave: () => void; handleSign: () => void;
  studyUID: string; studyInfo: { patient_id: string } | null;
  nextStudyUID: string | null; goToNextStudy: () => void;
  consultOpen: boolean; setConsultOpen: (v: boolean) => void;
}) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-6 py-3 border-b border-slate-100 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <button onClick={() => setActiveTab('report')}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition ${activeTab === 'report' ? 'bg-blue-50 text-blue-700' : 'text-slate-500 hover:text-slate-700'}`}>
              판독 리포트
            </button>
            <button onClick={() => setActiveTab('history')}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition ${activeTab === 'history' ? 'bg-blue-50 text-blue-700' : 'text-slate-500 hover:text-slate-700'}`}>
              이력
            </button>
          </div>
          <StatusBadge report={report} />
          {dirty && <span className="w-2 h-2 bg-amber-400 rounded-full" title="변경사항 있음" />}
        </div>
        <ShortcutHints />
      </div>

      {activeTab === 'report' ? (
        <div className="p-6">
          {/* Findings */}
          <FieldSection label="소견 (Findings)" required>
            {isFinal ? (
              <ReadOnlyField value={findings} className="min-h-[200px]" />
            ) : (
              <div className="relative">
                <textarea ref={findingsRef} rows={10} value={findings}
                  onChange={e => { setFindings(e.target.value); setDirty(true); }}
                  className="w-full border border-slate-200 rounded-xl p-4 text-sm resize-y focus:border-blue-400 focus:ring-2 focus:ring-blue-100 outline-none leading-relaxed font-mono"
                  placeholder="소견을 입력하세요..." />
                <DictationButton targetField="소견" setter={v => { setFindings(v); setDirty(true); }} currentValue={findings} />
              </div>
            )}
          </FieldSection>

          {/* Impression */}
          <FieldSection label="결론 (Impression)" required className="mt-5">
            {isFinal ? (
              <ReadOnlyField value={impression} accent className="min-h-[80px]" />
            ) : (
              <div className="relative">
                <textarea rows={5} value={impression}
                  onChange={e => { setImpression(e.target.value); setDirty(true); }}
                  className="w-full border border-slate-200 rounded-xl p-4 text-sm resize-y focus:border-blue-400 focus:ring-2 focus:ring-blue-100 outline-none leading-relaxed"
                  placeholder="결론을 입력하세요..." />
                <DictationButton targetField="결론" setter={v => { setImpression(v); setDirty(true); }} currentValue={impression} />
              </div>
            )}
          </FieldSection>

          {/* Recommendation */}
          <FieldSection label="권고 사항" className="mt-5">
            {isFinal ? (
              <ReadOnlyField value={recommendation} className="min-h-[40px]" />
            ) : (
              <textarea rows={3} value={recommendation}
                onChange={e => { setRecommendation(e.target.value); setDirty(true); }}
                className="w-full border border-slate-200 rounded-xl p-4 text-sm resize-y focus:border-slate-300 outline-none leading-relaxed"
                placeholder="권고 사항 (선택)" />
            )}
          </FieldSection>

          {/* Signed Info */}
          {isFinal && report && (
            <div className="mt-5 bg-slate-50 rounded-xl p-4 text-sm text-slate-600 flex items-center gap-4 border border-slate-100">
              <svg className="w-5 h-5 text-green-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
              <div>
                <span className="font-semibold text-slate-800">{report.signed_by_name}</span>
                <span className="mx-2 text-slate-300">|</span>
                <span className="text-slate-500">{report.signed_at ? new Date(report.signed_at).toLocaleString('ko-KR') : '-'}</span>
              </div>
            </div>
          )}

          {/* 외부 PKI 전자서명 (sign.example.org, FINAL 보고서) */}
          {isFinal && report?.id && <ExternalEsign reportId={report.id} />}
        </div>
      ) : (
        <ReportHistory studyUID={studyUID} patientId={studyInfo?.patient_id || ''} />
      )}

      {/* Action Bar */}
      <div className="px-6 py-4 border-t border-slate-100 bg-slate-50/50 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/reading" className="text-sm text-slate-500 hover:text-slate-700 transition">
            ← 판독 큐 <kbd className="ml-1 px-1 py-0.5 bg-slate-100 rounded text-[10px] font-mono text-slate-400">Q</kbd>
          </Link>
          {nextStudyUID && (
            <button onClick={goToNextStudy} className="text-sm text-blue-600 hover:text-blue-800 font-medium transition">
              다음 Study → <kbd className="ml-1 px-1 py-0.5 bg-blue-50 rounded text-[10px] font-mono text-blue-400">N</kbd>
            </button>
          )}
        </div>
        <div className="flex items-center gap-3">
          {!isFinal && (
            <>
              <button onClick={handleSave} disabled={saving}
                className="px-6 py-2.5 rounded-xl text-sm font-semibold border border-slate-300 text-slate-700 hover:bg-slate-100 disabled:opacity-50 transition">
                {saving ? '저장 중...' : '임시 저장'}
              </button>
              <button onClick={handleSign}
                className="px-8 py-2.5 rounded-xl text-sm font-bold bg-emerald-600 text-white hover:bg-emerald-700 transition shadow-sm">
                서명 완료
              </button>
            </>
          )}
          <button onClick={() => setConsultOpen(!consultOpen)}
            className={`px-4 py-2.5 rounded-xl text-sm font-medium transition ${consultOpen ? 'bg-blue-100 text-blue-700 border border-blue-200' : 'border border-slate-300 text-slate-600 hover:bg-slate-100'}`}>
            협진/의뢰
          </button>
        </div>
      </div>
    </div>
  );
}
