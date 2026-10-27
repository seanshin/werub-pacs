'use client';

import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import ViewerButton from '@/components/ViewerButton';

const API = '/pacs-api/api/v1/consult-portal';

async function portalFetch<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...opts?.headers },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Error ${res.status}`);
  }
  return res.json();
}

type ConsultData = {
  consult_kind: string;
  study_instance_uid: string;
  reason?: string; question?: string;
  institution_name?: string; physician_name?: string;
  requested_by_name?: string; requester?: string;
  urgency?: string; consult_type?: string;
  clinical_info?: string; external_email?: string;
  status: string; consent_given: boolean;
  created_at: string;
};

export default function ConsultPortalWrapper() {
  return <Suspense fallback={<Loading />}><ConsultPortalPage /></Suspense>;
}

function Loading() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center">
      <div className="text-gray-400">로딩 중...</div>
    </div>
  );
}

function ConsultPortalPage() {
  const params = useSearchParams();
  const token = params.get('token') || '';
  const [data, setData] = useState<ConsultData | null>(null);
  const [error, setError] = useState('');
  const [step, setStep] = useState<'loading' | 'consent' | 'respond' | 'done' | 'error'>('loading');
  const [consent, setConsent] = useState<Record<string, boolean>>({});
  const [name, setName] = useState('');
  const [institution, setInstitution] = useState('');
  const [opinion, setOpinion] = useState('');
  const [findings, setFindings] = useState('');
  const [impression, setImpression] = useState('');

  useEffect(() => {
    if (!token) { setError('토큰이 없습니다.'); setStep('error'); return; }
    portalFetch<ConsultData>(`/view?token=${token}`)
      .then(d => {
        setData(d);
        if (d.status === 'completed') setStep('done');
        else if (d.consent_given) setStep('respond');
        else setStep('consent');
      })
      .catch(e => { setError(e.message); setStep('error'); });
  }, [token]);

  const TERMS = [
    { key: 'phi', title: '개인정보 취급 동의', text: '본 시스템을 통해 접근하는 환자 영상 및 의료 정보는 개인정보보호법에 따른 민감정보에 해당합니다. 본인은 해당 정보를 의뢰 목적으로만 사용하며, 무단 복제/저장/유출하지 않을 것을 동의합니다.' },
    { key: 'confidentiality', title: '비밀유지 서약', text: '본인은 열람한 환자 정보 및 영상에 대해 비밀을 유지하며, 의뢰 목적 외 제3자에게 공개하지 않을 것을 서약합니다.' },
    { key: 'medical_law', title: '의료법 준수', text: '본인은 의료법에 따라 적법한 자격을 갖춘 의료인으로서 의견을 제공하며, 원격판독에 관한 법적 책임을 이해합니다.' },
    { key: 'data_policy', title: '데이터 보관/삭제 정책', text: '본 시스템에서 제공하는 영상 접근 권한은 의뢰일로부터 7일간 유효하며, 만료 후 접근이 자동 차단됩니다. 열람 이력은 감사 로그에 기록됩니다.' },
    { key: 'legal_scope', title: '판독 결과 법적 효력', text: '본 의뢰를 통한 판독 의견은 참고용(second opinion)이며, 최종 진단 및 치료 결정의 법적 책임은 의뢰 기관의 담당 의료진에게 있습니다.' },
  ];

  const allAgreed = TERMS.every(t => consent[t.key]);

  if (step === 'error') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center">
        <div className="bg-white rounded-2xl shadow-xl p-8 max-w-md text-center">
          <div className="text-4xl mb-4">!</div>
          <h2 className="text-xl font-bold text-red-600 mb-2">접근 오류</h2>
          <p className="text-gray-600">{error}</p>
        </div>
      </div>
    );
  }

  if (step === 'loading' || !data) return <Loading />;

  const isSecondOpinion = data.consult_kind === 'second_opinion';
  const questionText = data.question || data.reason || '';
  const requesterName = data.requester || data.requested_by_name || '';

  // ── CONSENT SCREEN ──
  if (step === 'consent') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 py-8 px-4">
        <div className="max-w-2xl mx-auto">
          <div className="text-center mb-8">
            <div className="inline-flex items-center gap-2 mb-2">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center shadow">
                <span className="text-white text-lg font-bold">W</span>
              </div>
              <span className="text-xl font-bold text-gray-900">WeRU.B PACS</span>
            </div>
            <h1 className="text-2xl font-bold text-gray-900 mt-4">
              {isSecondOpinion ? '세컨드 오피니언 요청' : '외부 판독 의뢰'}
            </h1>
            <p className="text-gray-500 mt-1">영상 열람 전 법적 동의가 필요합니다</p>
          </div>

          {/* 의뢰 요약 */}
          <div className="bg-white rounded-xl border shadow-sm p-5 mb-6">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div><span className="text-gray-500">의뢰자</span><p className="font-medium">{requesterName}</p></div>
              <div><span className="text-gray-500">긴급도</span><p className="font-medium">{data.urgency === 'stat' ? 'STAT' : data.urgency === 'urgent' ? '긴급' : '일반'}</p></div>
            </div>
            <div className="mt-3 text-sm">
              <span className="text-gray-500">{isSecondOpinion ? '질문' : '의뢰 사유'}</span>
              <p className="font-medium mt-1 bg-blue-50 rounded-lg p-3 border border-blue-100">{questionText}</p>
            </div>
          </div>

          {/* 법적 동의 항목 */}
          <div className="bg-white rounded-xl border shadow-sm p-5 mb-6">
            <h3 className="font-bold text-gray-900 mb-4">법적 동의 사항</h3>
            <div className="space-y-4">
              {TERMS.map(t => (
                <label key={t.key} className={`block p-4 rounded-lg border cursor-pointer transition ${consent[t.key] ? 'border-blue-500 bg-blue-50/50' : 'border-gray-200 hover:bg-gray-50'}`}>
                  <div className="flex items-start gap-3">
                    <input type="checkbox" checked={!!consent[t.key]}
                      onChange={e => setConsent({ ...consent, [t.key]: e.target.checked })}
                      className="mt-1 w-4 h-4 text-blue-600 rounded" />
                    <div>
                      <div className="font-semibold text-sm text-gray-900">{t.title}</div>
                      <div className="text-xs text-gray-500 mt-1 leading-relaxed">{t.text}</div>
                    </div>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* 서명 */}
          <div className="bg-white rounded-xl border shadow-sm p-5 mb-6">
            <h3 className="font-bold text-gray-900 mb-3">서명</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm text-gray-600">성명 *</label>
                <input type="text" value={name} onChange={e => setName(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 mt-1 text-sm" placeholder="홍길동" />
              </div>
              <div>
                <label className="text-sm text-gray-600">소속 기관</label>
                <input type="text" value={institution} onChange={e => setInstitution(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 mt-1 text-sm" placeholder="OO병원 영상의학과" />
              </div>
            </div>
          </div>

          <button
            disabled={!allAgreed || !name.trim()}
            onClick={async () => {
              await portalFetch('/consent', {
                method: 'POST',
                body: JSON.stringify({
                  consult_token: token,
                  agreed_terms: TERMS.map(t => t.key),
                  respondent_name: name,
                  respondent_institution: institution,
                }),
              });
              setStep('respond');
            }}
            className="w-full bg-blue-600 text-white py-3 rounded-xl font-semibold hover:bg-blue-700 transition disabled:opacity-40 disabled:cursor-not-allowed text-lg shadow-lg">
            동의 및 영상 열람
          </button>
        </div>
      </div>
    );
  }

  // ── RESPOND SCREEN ──
  if (step === 'respond') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 py-8 px-4">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-center justify-between mb-6">
            <h1 className="text-2xl font-bold">{isSecondOpinion ? '세컨드 오피니언' : '외부 판독'}</h1>
            <span className="px-3 py-1 rounded-full text-xs font-semibold bg-yellow-100 text-yellow-800">응답 대기</span>
          </div>

          {/* 의뢰 정보 */}
          <div className="bg-white rounded-xl border shadow-sm p-5 mb-4">
            <div className="text-sm mb-3">
              <span className="text-gray-500">{isSecondOpinion ? '질문' : '의뢰 사유'}</span>
              <p className="mt-1 bg-blue-50 rounded-lg p-3 border border-blue-100">{questionText}</p>
            </div>
            {data.clinical_info && (
              <div className="text-sm">
                <span className="text-gray-500">임상 정보</span>
                <p className="mt-1 bg-gray-50 rounded-lg p-3 border">{data.clinical_info}</p>
              </div>
            )}
          </div>

          {/* 영상 보기 */}
          <div className="bg-white rounded-xl border shadow-sm p-5 mb-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="font-semibold">영상 열람</h3>
                <p className="text-xs text-gray-500 mt-1">Study: {data.study_instance_uid?.substring(0, 40)}...</p>
              </div>
              <ViewerButton url={`/werub-viewer/viewer?StudyInstanceUIDs=${data.study_instance_uid}`} label="영상 보기" />
            </div>
          </div>

          {/* 의견 작성 */}
          <div className="bg-white rounded-xl border shadow-sm p-5 mb-4">
            <h3 className="font-semibold mb-3">의견 작성</h3>
            {isSecondOpinion ? (
              <textarea rows={8} value={opinion} onChange={e => setOpinion(e.target.value)}
                className="w-full border rounded-lg px-4 py-3 text-sm" placeholder="전문의 의견을 작성하세요..." />
            ) : (
              <div className="space-y-3">
                <div>
                  <label className="text-sm text-gray-600">소견 (Findings)</label>
                  <textarea rows={5} value={findings} onChange={e => setFindings(e.target.value)}
                    className="w-full border rounded-lg px-4 py-3 text-sm mt-1" placeholder="소견..." />
                </div>
                <div>
                  <label className="text-sm text-gray-600">결론 (Impression)</label>
                  <textarea rows={3} value={impression} onChange={e => setImpression(e.target.value)}
                    className="w-full border rounded-lg px-4 py-3 text-sm mt-1" placeholder="결론..." />
                </div>
              </div>
            )}
          </div>

          <button
            disabled={isSecondOpinion ? !opinion.trim() : !findings.trim()}
            onClick={async () => {
              await portalFetch('/respond', {
                method: 'POST',
                body: JSON.stringify({
                  consult_token: token,
                  findings: findings || undefined,
                  impression: impression || undefined,
                  opinion: opinion || undefined,
                  respondent_name: name || 'External',
                }),
              });
              setStep('done');
            }}
            className="w-full bg-green-600 text-white py-3 rounded-xl font-semibold hover:bg-green-700 transition disabled:opacity-40 text-lg shadow-lg">
            의견 제출
          </button>
        </div>
      </div>
    );
  }

  // ── DONE SCREEN ──
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center">
      <div className="bg-white rounded-2xl shadow-xl p-8 max-w-md text-center">
        <div className="text-5xl mb-4">OK</div>
        <h2 className="text-xl font-bold text-green-700 mb-2">의견 제출 완료</h2>
        <p className="text-gray-600">응답이 의뢰 기관에 전달되었습니다.<br />감사합니다.</p>
      </div>
    </div>
  );
}
