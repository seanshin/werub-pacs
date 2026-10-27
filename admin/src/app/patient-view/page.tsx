'use client';

import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';

const API_BASE = '/pacs-api';

type Study = {
  study_instance_uid: string;
  study_date: string;
  study_description: string;
  modalities: string;
  series_count: number;
  has_final_report: boolean;
};

type ReportView = {
  study_instance_uid: string;
  study_description: string | null;
  modality: string | null;
  study_date: string | null;
  status: string;
  findings: string | null;
  impression: string | null;
  recommendation: string | null;
  signed_by: string | null;
  signed_at: string | null;
};

function fmtDate(d?: string | null): string {
  if (!d || d.length !== 8) return d || '-';
  return `${d.slice(0, 4)}.${d.slice(4, 6)}.${d.slice(6, 8)}`;
}

export default function PatientViewPage() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center">불러오는 중...</div>}>
      <PatientViewInner />
    </Suspense>
  );
}

function PatientViewInner() {
  const searchParams = useSearchParams();
  const token = searchParams.get('token') || '';

  const [step, setStep] = useState<'loading' | 'list' | 'report' | 'error'>('loading');
  const [error, setError] = useState('');
  const [patientName, setPatientName] = useState('');
  const [studies, setStudies] = useState<Study[]>([]);
  const [report, setReport] = useState<ReportView | null>(null);
  const [reportLoading, setReportLoading] = useState(false);

  useEffect(() => {
    if (!token) { setStep('error'); setError('열람 링크가 유효하지 않습니다.'); return; }
    loadStudies();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const loadStudies = async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/v1/patient-view/portal/studies?token=${encodeURIComponent(token)}`);
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        setStep('error');
        setError(
          resp.status === 503 ? '열람 서비스가 현재 이용 불가합니다.' :
          (body?.error?.message || body?.detail || '링크가 만료되었거나 유효하지 않습니다.'));
        return;
      }
      const data = await resp.json();
      setPatientName(String(data.patient_name || '').replace(/\^/g, ' ').trim());
      setStudies(data.studies || []);
      setStep('list');
    } catch {
      setStep('error');
      setError('서버 연결에 실패했습니다.');
    }
  };

  const openReport = async (uid: string) => {
    setReportLoading(true);
    try {
      const resp = await fetch(
        `${API_BASE}/api/v1/patient-view/portal/report?token=${encodeURIComponent(token)}&study_uid=${encodeURIComponent(uid)}`);
      if (!resp.ok) { setError('판독 결과를 불러오지 못했습니다.'); setReportLoading(false); return; }
      setReport(await resp.json());
      setError('');
      setStep('report');
    } catch {
      setError('서버 연결에 실패했습니다.');
    }
    setReportLoading(false);
  };

  const previewUrl = (uid: string) =>
    `${API_BASE}/api/v1/patient-view/portal/preview?token=${encodeURIComponent(token)}&study_uid=${encodeURIComponent(uid)}`;

  return (
    <div className="min-h-screen bg-gradient-to-b from-teal-50 to-white flex items-start justify-center p-4">
      <div className="bg-white rounded-3xl shadow-xl w-full max-w-lg overflow-hidden my-6">
        <div className="bg-teal-600 text-white p-6 text-center">
          <h1 className="text-xl font-bold">WeRU.B PACS</h1>
          <p className="text-teal-100 text-sm mt-1">검사 결과 열람</p>
        </div>

        <div className="p-6">
          {step === 'error' && (
            <div className="text-center py-8">
              <div className="text-5xl mb-4">⚠️</div>
              <p className="text-gray-700 font-medium">{error}</p>
              <p className="text-sm text-gray-400 mt-2">병원 접수 데스크에서 새 링크를 발급받으세요.</p>
            </div>
          )}

          {step === 'loading' && (
            <div className="text-center py-8">
              <div className="animate-spin text-3xl mb-4">⏳</div>
              <p className="text-gray-500">확인 중...</p>
            </div>
          )}

          {step === 'list' && (
            <div>
              <p className="text-lg font-medium mb-1">{patientName ? `${patientName}님의 검사 결과` : '검사 결과'}</p>
              <p className="text-xs text-gray-400 mb-4">
                본 화면은 참고용이며, 정확한 내용은 담당 의료진의 설명을 따르세요.
              </p>
              {error && <p className="text-red-500 text-sm mb-3 bg-red-50 p-2 rounded">{error}</p>}

              {studies.length === 0 && (
                <div className="text-center py-8 text-gray-400 text-sm">등록된 검사가 없습니다.</div>
              )}

              <div className="space-y-3">
                {studies.map(s => (
                  <div key={s.study_instance_uid} className="border rounded-2xl p-3 flex gap-3 items-center">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={previewUrl(s.study_instance_uid)} alt=""
                      className="w-16 h-16 rounded-xl object-cover bg-gray-100 shrink-0"
                      onError={e => { (e.target as HTMLImageElement).style.visibility = 'hidden'; }} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">
                        {s.study_description || '검사'} <span className="text-gray-400">({s.modalities || '-'})</span>
                      </div>
                      <div className="text-xs text-gray-400">{fmtDate(s.study_date)}</div>
                    </div>
                    {s.has_final_report ? (
                      <button onClick={() => openReport(s.study_instance_uid)} disabled={reportLoading}
                        className="px-3 py-2 bg-teal-600 text-white rounded-xl text-xs font-medium hover:bg-teal-700 disabled:opacity-50 shrink-0">
                        결과 보기
                      </button>
                    ) : (
                      <span className="px-3 py-2 bg-gray-100 text-gray-400 rounded-xl text-xs shrink-0">판독 중</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {step === 'report' && report && (
            <div>
              <button onClick={() => { setStep('list'); setReport(null); }}
                className="text-sm text-teal-600 mb-3">← 목록으로</button>
              <p className="text-lg font-medium">{report.study_description || '검사 결과'}</p>
              <p className="text-xs text-gray-400 mb-4">
                {fmtDate(report.study_date)} · {report.modality || '-'}
                {report.status === 'addendum' && ' · 추가 소견 포함'}
              </p>

              {report.findings && (
                <div className="mb-3">
                  <div className="text-xs font-bold text-gray-500 mb-1">검사 소견</div>
                  <div className="bg-gray-50 rounded-xl p-3 text-sm whitespace-pre-wrap">{report.findings}</div>
                </div>
              )}
              {report.impression && (
                <div className="mb-3">
                  <div className="text-xs font-bold text-gray-500 mb-1">판독 결론</div>
                  <div className="bg-teal-50 rounded-xl p-3 text-sm whitespace-pre-wrap">{report.impression}</div>
                </div>
              )}
              {report.recommendation && (
                <div className="mb-3">
                  <div className="text-xs font-bold text-gray-500 mb-1">권고 사항</div>
                  <div className="bg-gray-50 rounded-xl p-3 text-sm whitespace-pre-wrap">{report.recommendation}</div>
                </div>
              )}

              <div className="text-xs text-gray-400 mt-4">
                {report.signed_by && <div>판독의: {report.signed_by}</div>}
                {report.signed_at && <div>확정일: {new Date(report.signed_at).toLocaleDateString('ko-KR')}</div>}
                <div className="mt-2 bg-amber-50 text-amber-700 rounded-xl p-2">
                  본 결과지는 환자 열람용 사본입니다. 내용에 대한 문의는 진료과에 해주세요.
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
