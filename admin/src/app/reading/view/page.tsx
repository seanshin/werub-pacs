'use client';

import Link from 'next/link';
import { Suspense, useState, useEffect } from 'react';
import ConsultPanel from '@/components/ConsultPanel';
import { getModalityRenderability } from '@/lib/dicom-renderability';
import Breadcrumb from '@/components/ui/Breadcrumb';
import { apiFetch } from '@/lib/api';
import { useReadingView } from './useReadingView';
import { Template } from './types';
import StudyInfoBar from './StudyInfoBar';
import ReportEditor from './ReportEditor';

/* ─── Entry ─── */
export default function ReadingViewWrapper() {
  return <Suspense fallback={<LoadingScreen />}><ReadingViewPage /></Suspense>;
}

function LoadingScreen() {
  return (
    <div className="flex items-center justify-center h-screen bg-slate-50">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p className="text-sm text-slate-500">판독 화면 로딩 중...</p>
      </div>
    </div>
  );
}

/* ─── Main Page ─── */
function ReadingViewPage() {
  const hook = useReadingView();
  const {
    studyUID, mode, user, loginForm, setLoginForm, handleLogin,
    report, templates, studyInfo, priorStudies,
    findings, setFindings, impression, setImpression,
    recommendation, setRecommendation, urgency, setUrgency,
    dirty, setDirty, activeTab, setActiveTab, findingsRef,
    saving, handleSave, handleSign, showToast,
    applyTemplate, insertMacro,
    viewerOpened, viewerWarning, setViewerWarning, openViewer, doOpenViewer, viewerUrl,
    nextStudyUID, showNextModal, setShowNextModal, goToNextStudy,
    consultOpen, setConsultOpen,
    showShortcuts, setShowShortcuts,
    toast, isFinal, allMacros,
  } = hook;

  // Login screen
  if (!user) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="w-full max-w-sm">
          <div className="text-center mb-6">
            <div className="w-12 h-12 bg-blue-600 rounded-xl flex items-center justify-center mx-auto mb-3">
              <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
            </div>
            <h1 className="text-xl font-bold text-slate-900">판독 시스템</h1>
            <p className="text-sm text-slate-500 mt-1">OpenPACS Reading Station</p>
          </div>
          <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm space-y-4">
            <input type="text" placeholder="사용자명" className="w-full border border-slate-200 rounded-xl px-4 py-3 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-200 outline-none"
              value={loginForm.username} onChange={e => setLoginForm(p => ({ ...p, username: e.target.value }))}
              onKeyDown={e => e.key === 'Enter' && handleLogin()} />
            <input type="password" placeholder="비밀번호" className="w-full border border-slate-200 rounded-xl px-4 py-3 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-200 outline-none"
              value={loginForm.password} onChange={e => setLoginForm(p => ({ ...p, password: e.target.value }))}
              onKeyDown={e => e.key === 'Enter' && handleLogin()} />
            <button onClick={handleLogin} className="w-full bg-blue-600 text-white py-3 rounded-xl font-semibold hover:bg-blue-700 transition">로그인</button>
          </div>
          <div className="text-center mt-4 text-xs text-slate-400">
            <button onClick={() => setLoginForm({ username: 'admin', password: '' })} className="hover:text-blue-600 transition">admin</button>
            <span className="mx-2">|</span>
            <button onClick={() => setLoginForm({ username: 'dr.kim', password: '' })} className="hover:text-blue-600 transition">dr.kim</button>
          </div>
        </div>
      </div>
    );
  }

  if (!studyUID) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="text-center">
          <svg className="w-16 h-16 text-slate-300 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m6.75 12H9.75m3 0h.008v.008H12.75V14.25zm0 3H9.75m3 0h.008v.008H12.75v-.008zM6 6.75A.75.75 0 016.75 6h.008a.75.75 0 01.75.75v.008a.75.75 0 01-.75.75H6.75A.75.75 0 016 7.508V6.75z" /></svg>
          <p className="text-slate-500 mb-2">Study UID가 필요합니다</p>
          <Link href="/reading" className="text-blue-600 hover:underline text-sm font-medium">판독 큐에서 선택</Link>
        </div>
      </div>
    );
  }

  // Single mode
  if (mode === 'single') {
    return (
      <div className="fixed inset-0 z-[9999] flex bg-black">
        <div className="flex-1"><iframe src={viewerUrl} className="w-full h-full border-0" allow="fullscreen" /></div>
        <SingleModePanel {...{
          isFinal, report, templates, findings, setFindings, impression, setImpression,
          recommendation, setRecommendation, urgency, setUrgency, saving, handleSave, handleSign,
          applyTemplate, insertMacro, viewerUrl, studyUID, studyInfo, mode, showToast,
        }} />
      </div>
    );
  }

  // Dual mode
  return (
    <div className="flex min-h-[calc(100vh-64px)]">
      <div className={`flex-1 min-w-0 transition-all duration-300 ${consultOpen ? '' : 'max-w-5xl mx-auto'}`}>
        <Breadcrumb items={[
          { label: '판독 큐', href: '/reading' },
          { label: studyInfo ? `${studyInfo.patient_name?.replace(/\^/g, ' ') || '...'} (${studyInfo.modality || ''})` : '판독' },
        ]} />

        {/* Study Info Bar */}
        <StudyInfoBar
          studyInfo={studyInfo}
          studyUID={studyUID}
          viewerOpened={viewerOpened}
          onOpenViewer={openViewer}
          onOpenWithPrior={() => doOpenViewer('werub', true)}
          priorCount={priorStudies.length}
          mode={mode}
        />

        {/* Main Content */}
        <div className="mt-4 space-y-4">
          {/* AI Toolbar + Urgency */}
          {!isFinal && (
            <AIToolbar studyUID={studyUID} modality={studyInfo?.modality || ''} findings={findings} impression={impression}
              setFindings={setFindings} setImpression={setImpression} setRecommendation={setRecommendation}
              urgency={urgency} setUrgency={setUrgency} showToast={showToast} setDirty={setDirty} />
          )}

          {/* Templates & Macros */}
          {!isFinal && templates.length > 0 && (
            <TemplateBar templates={templates} macros={allMacros} applyTemplate={applyTemplate} insertMacro={insertMacro} />
          )}

          {/* Report Editor */}
          <ReportEditor
            report={report} findings={findings} setFindings={setFindings}
            impression={impression} setImpression={setImpression}
            recommendation={recommendation} setRecommendation={setRecommendation}
            dirty={dirty} setDirty={setDirty}
            activeTab={activeTab} setActiveTab={setActiveTab}
            findingsRef={findingsRef} isFinal={isFinal}
            saving={saving} handleSave={handleSave} handleSign={handleSign}
            studyUID={studyUID} studyInfo={studyInfo}
            nextStudyUID={nextStudyUID} goToNextStudy={goToNextStudy}
            consultOpen={consultOpen} setConsultOpen={setConsultOpen}
          />
        </div>

        {/* Toast */}
        {toast && (
          <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50">
            <div className="bg-slate-900 text-white px-6 py-3 rounded-xl shadow-2xl text-sm font-medium flex items-center gap-2">
              <svg className="w-4 h-4 text-emerald-400 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" /></svg>
              {toast}
            </div>
          </div>
        )}

        {/* Viewer non-renderable warning */}
        {viewerWarning && (() => {
          const ri = getModalityRenderability(studyInfo?.modality);
          return (
            <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center">
              <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-sm mx-4">
                <div className="text-center mb-4">
                  <div className="w-12 h-12 bg-amber-100 rounded-full flex items-center justify-center mx-auto mb-3">
                    <svg className="w-6 h-6 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                    </svg>
                  </div>
                  <h3 className="text-lg font-bold text-slate-900">영상 표시 불가</h3>
                  <div className="mt-2 space-y-1">
                    <p className="text-sm font-semibold text-slate-700">
                      모달리티: <span className="text-amber-700">{studyInfo?.modality}</span>
                      {ri.label && <span className="text-slate-500 font-normal"> ({ri.label})</span>}
                    </p>
                    <p className="text-sm text-slate-500">{ri.description}</p>
                    {ri.action && <p className="text-xs text-blue-600 mt-1">{ri.action}</p>}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => setViewerWarning(null)}
                    className="flex-1 px-4 py-2.5 border border-slate-300 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 transition">닫기</button>
                  <button onClick={() => doOpenViewer(viewerWarning.type)}
                    className="flex-1 px-4 py-2.5 bg-slate-600 text-white rounded-xl text-sm font-medium hover:bg-slate-700 transition">그래도 열기</button>
                </div>
              </div>
            </div>
          );
        })()}

        {/* Next Study Modal */}
        {showNextModal && (
          <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center">
            <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-sm mx-4">
              <div className="text-center mb-4">
                <div className="w-12 h-12 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-3">
                  <svg className="w-6 h-6 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
                </div>
                <h3 className="text-lg font-bold text-slate-900">판독 서명 완료</h3>
                <p className="text-sm text-slate-500 mt-1">
                  {nextStudyUID ? '다음 대기 Study로 이동하시겠습니까?' : '모든 대기 Study를 판독했습니다.'}
                </p>
              </div>
              <div className="flex gap-2">
                <button onClick={() => setShowNextModal(false)}
                  className="flex-1 px-4 py-2.5 border border-slate-300 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 transition">
                  현재 유지
                </button>
                <button onClick={goToNextStudy} autoFocus
                  className="flex-1 px-4 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-bold hover:bg-blue-700 transition">
                  {nextStudyUID ? '다음 Study →' : '판독 큐 →'}
                </button>
              </div>
              <p className="text-center text-[10px] text-slate-400 mt-3">
                <kbd className="px-1 py-0.5 bg-slate-100 rounded text-[10px] font-mono">N</kbd> 다음 이동 &middot; <kbd className="px-1 py-0.5 bg-slate-100 rounded text-[10px] font-mono">Esc</kbd> 닫기
              </p>
            </div>
          </div>
        )}

        {/* Shortcuts Help Modal */}
        {showShortcuts && (
          <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center" onClick={() => setShowShortcuts(false)}>
            <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-md mx-4" onClick={e => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-bold text-slate-900">키보드 단축키</h3>
                <button onClick={() => setShowShortcuts(false)} className="text-slate-400 hover:text-slate-600 text-xl">&times;</button>
              </div>
              <div className="space-y-1 text-sm">
                {[
                  { section: '판독', items: [
                    ['Ctrl+S', '임시 저장'],
                    ['Ctrl+Enter', '서명 완료'],
                    ['F', '소견 입력 포커스'],
                  ]},
                  { section: '네비게이션', items: [
                    ['N', '다음 Study 이동'],
                    ['Q', '판독 큐로 돌아가기'],
                    ['V', 'WeRU.B 뷰어 열기'],
                  ]},
                  { section: '템플릿', items: [
                    ['1-9', '템플릿 번호로 적용'],
                  ]},
                  { section: '기타', items: [
                    ['?', '단축키 도움말 토글'],
                    ['Esc', '모달 닫기'],
                  ]},
                ].map(s => (
                  <div key={s.section}>
                    <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mt-3 mb-1.5">{s.section}</div>
                    {s.items.map(([key, desc]) => (
                      <div key={key} className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-slate-50">
                        <span className="text-slate-600">{desc}</span>
                        <kbd className="px-2 py-0.5 bg-slate-100 border border-slate-200 rounded text-xs font-mono text-slate-600">{key}</kbd>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Consult Panel */}
      {consultOpen && (
        <ConsultPanel studyUID={studyUID} reportId={report?.id} findings={findings} impression={impression} onClose={() => setConsultOpen(false)} />
      )}
    </div>
  );
}

/* ─── AI Toolbar ─── */
function AIToolbar({ studyUID, modality, findings, impression, setFindings, setImpression, setRecommendation, urgency, setUrgency, showToast, setDirty }: {
  studyUID: string; modality: string; findings: string; impression: string;
  setFindings: (v: string | ((prev: string) => string)) => void;
  setImpression: (v: string | ((prev: string) => string)) => void;
  setRecommendation: (v: string | ((prev: string) => string)) => void;
  urgency: string; setUrgency: (v: string) => void;
  showToast: (msg: string) => void; setDirty: (v: boolean) => void;
}) {
  const [loading, setLoading] = useState<string | null>(null);
  const [prodPipeline, setProdPipeline] = useState<string | null>(null);

  const PIPE_MODALITIES: Record<string, string[]> = {
    'chest-xray': ['CR', 'DX'],
    'ct-abdomen': ['CT'],
    'emergency-triage': ['CR', 'DX', 'CT'],
    'medical': ['CR', 'DX', 'CT', 'MR', 'US'],
    'consensus': ['CR', 'DX', 'CT', 'MR'],
  };

  useEffect(() => {
    apiFetch<Record<string, any>>('/api/v1/ai/orchestration/production').then(d => {
      if (d?.reading?.pipeline) setProdPipeline(d.reading.pipeline);
    }).catch(() => {});
  }, []);

  const pipelineAvailable = prodPipeline && (() => {
    const mods = PIPE_MODALITIES[prodPipeline];
    if (!mods) return true;
    return mods.some(m => (modality || '').toUpperCase().includes(m));
  })();

  const aiActions = [
    {
      key: 'analyze', label: '영상 분석', color: 'bg-violet-600 hover:bg-violet-700',
      action: async () => {
        setLoading('analyze'); showToast('MedGemma 분석 중...');
        try {
          const res = await apiFetch<any>('/api/v1/ai/analyze-and-draft', {
            method: 'POST', body: JSON.stringify({ study_instance_uid: studyUID, auto_create_report: false }),
          });
          if (res?.ai_analysis) {
            setFindings(res.ai_analysis.findings || '');
            setImpression(res.ai_analysis.impression || '');
            setRecommendation(() => res.ai_analysis.recommendations || '');
            setDirty(true);
            showToast(`AI 분석 완료 (${res.ai_analysis.duration_ms}ms)`);
          }
        } catch (e: any) { showToast(e.message); }
        setLoading(null);
      },
    },
    {
      key: 'compare', label: '이전 비교', color: 'bg-indigo-500 hover:bg-indigo-600',
      action: async () => {
        setLoading('compare'); showToast('이전 검사 비교 중...');
        try {
          const res = await apiFetch<any>('/api/v1/ai/compare-studies', {
            method: 'POST', body: JSON.stringify({ current_study_uid: studyUID }),
          });
          if (res?.comparison?.text) {
            setFindings(prev => prev + '\n\n--- 이전 검사 비교 ---\n' + res.comparison.text);
            setDirty(true); showToast('비교 완료');
          } else showToast(res?.message || '이전 검사 없음');
        } catch (e: any) { showToast(e.message); }
        setLoading(null);
      },
    },
    {
      key: 'soap', label: 'SOAP', color: 'bg-teal-600 hover:bg-teal-700',
      action: async () => {
        if (!findings) { showToast('소견을 먼저 입력하세요'); return; }
        setLoading('soap'); showToast('SOAP 요약 중...');
        try {
          const res = await apiFetch<any>('/api/v1/ai/soap-summary', {
            method: 'POST', body: JSON.stringify({ findings, impression, clinical_info: '' }),
          });
          if (res?.summary) {
            const s = res.summary;
            setRecommendation(prev => (prev ? prev + '\n\n' : '') + `[SOAP]\nS: ${s.subjective || '-'}\nO: ${s.objective || '-'}\nA: ${s.assessment || '-'}\nP: ${s.plan || '-'}`);
            setDirty(true); showToast('SOAP 완료');
          } else showToast(res?.error || 'SOAP 실패');
        } catch (e: any) { showToast(e.message); }
        setLoading(null);
      },
    },
    {
      key: 'ddx', label: '감별진단', color: 'bg-amber-600 hover:bg-amber-700',
      action: async () => {
        if (!findings) { showToast('소견을 먼저 입력하세요'); return; }
        setLoading('ddx'); showToast('감별진단 분석 중...');
        try {
          const res = await apiFetch<any>('/api/v1/ai/differential-diagnosis', {
            method: 'POST', body: JSON.stringify({ symptoms: findings, findings: impression }),
          });
          if (res?.differential_diagnosis?.length) {
            const ddx = res.differential_diagnosis.map((d: any, i: number) =>
              `${i + 1}. ${d.condition || d.name || d.diagnosis} (${d.icd_code || d.icd10 || ''}) ${d.probability || d.confidence || ''}`
            ).join('\n');
            setImpression(prev => prev ? prev + '\n\n--- 감별진단 ---\n' + ddx : ddx);
            setDirty(true); showToast(`감별진단 ${res.differential_diagnosis.length}건`);
          } else showToast(res?.error || '감별진단 없음');
        } catch (e: any) { showToast(e.message); }
        setLoading(null);
      },
    },
  ];

  return (
    <div className="flex items-center gap-2 bg-white rounded-xl border border-slate-200 shadow-sm px-4 py-2.5">
      <div className="flex items-center gap-1.5 pr-3 border-r border-slate-200">
        <svg className="w-4 h-4 text-violet-500" fill="currentColor" viewBox="0 0 20 20"><path d="M13 6a3 3 0 11-6 0 3 3 0 016 0zM18 8a2 2 0 11-4 0 2 2 0 014 0zM14 15a4 4 0 00-8 0v1h8v-1zM6 8a2 2 0 11-4 0 2 2 0 014 0zM16 18v-1a5.972 5.972 0 00-.75-2.906A3.005 3.005 0 0119 17v1h-3zM4.75 14.094A5.973 5.973 0 004 17v1H1v-1a3 3 0 013.75-2.906z" /></svg>
        <span className="text-xs font-semibold text-slate-500">AI</span>
      </div>

      {aiActions.map(a => (
        <button key={a.key} onClick={a.action} disabled={loading !== null}
          className={`${a.color} text-white px-3.5 py-1.5 rounded-lg text-xs font-semibold transition disabled:opacity-50 flex items-center gap-1.5`}>
          {loading === a.key && <span className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
          {a.label}
        </button>
      ))}

      {pipelineAvailable && (
        <>
          <div className="w-px h-6 bg-slate-200 mx-1" />
          <button onClick={async () => {
            setLoading('pipeline'); showToast(`🔗 ${prodPipeline} 파이프라인 실행 중...`);
            try {
              const res = await apiFetch<any>('/api/v1/ai/orchestration/run', {
                method: 'POST',
                body: JSON.stringify({ pipeline: prodPipeline, study_instance_uid: studyUID, debug: false }),
              });
              if (res && !res.error && res.result) {
                setFindings(res.result);
                setDirty(true);
                showToast(`🔗 ${prodPipeline} 완료 (${((res.total_duration_ms || 0) / 1000).toFixed(1)}초)`);
              } else {
                showToast(res?.error || '파이프라인 실행 실패');
              }
            } catch (e: any) { showToast(e.message); }
            setLoading(null);
          }} disabled={loading !== null}
            className="bg-green-600 hover:bg-green-700 text-white px-3.5 py-1.5 rounded-lg text-xs font-semibold transition disabled:opacity-50 flex items-center gap-1.5">
            {loading === 'pipeline' && <span className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
            🔗 {prodPipeline}
          </button>
        </>
      )}

      <div className="flex-1" />

      {/* Urgency Selector */}
      <div className="flex items-center gap-1.5">
        <span className="text-xs text-slate-400">긴급도</span>
        {[
          { value: 'normal', label: '일반', cls: '' },
          { value: 'non_urgent', label: '비긴급 이상', cls: 'text-amber-700 border-amber-300 bg-amber-50' },
          { value: 'urgent', label: '긴급', cls: 'text-red-700 border-red-300 bg-red-50' },
        ].map(u => (
          <button key={u.value} onClick={() => setUrgency(u.value)}
            className={`px-2.5 py-1 rounded-lg text-xs font-medium border transition ${
              urgency === u.value
                ? (u.cls || 'bg-slate-100 text-slate-700 border-slate-300')
                : 'border-transparent text-slate-400 hover:text-slate-600'
            }`}>
            {u.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ─── Template & Macro Bar ─── */
function TemplateBar({ templates, macros, applyTemplate, insertMacro }: {
  templates: Template[]; macros: { key: string; value: string; templateId: string }[];
  applyTemplate: (t: Template) => void; insertMacro: (text: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
      <button onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-2.5 text-sm hover:bg-slate-50 transition rounded-xl">
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h7" /></svg>
          <span className="font-medium text-slate-600">템플릿 & 단축어</span>
          <span className="text-xs text-slate-400">({templates.length}개 템플릿, {macros.length}개 단축어)</span>
        </div>
        <svg className={`w-4 h-4 text-slate-400 transition-transform ${expanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-slate-100">
          {/* Templates */}
          <div className="mt-3">
            <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2">템플릿</div>
            <div className="flex flex-wrap gap-1.5">
              {templates.map(t => (
                <button key={t.id} onClick={() => applyTemplate(t)}
                  className="inline-flex items-center gap-1 bg-slate-50 hover:bg-blue-50 text-slate-600 hover:text-blue-700 px-3 py-1.5 rounded-lg text-xs font-medium transition border border-slate-200 hover:border-blue-300">
                  <span className="text-[10px] text-slate-400">{t.modality}</span>
                  {t.name.split('(')[0].trim()}
                </button>
              ))}
            </div>
          </div>

          {/* Macros */}
          {macros.length > 0 && (
            <div className="mt-3">
              <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2">단축어</div>
              <div className="flex flex-wrap gap-1">
                {macros.map((m, i) => (
                  <button key={`${m.templateId}-${m.key}-${i}`} onClick={() => insertMacro(m.value)}
                    className="text-xs text-slate-500 hover:text-blue-700 hover:bg-blue-50 px-2 py-1 rounded-lg transition border border-transparent hover:border-blue-200"
                    title={m.value}>
                    {m.key}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ─── Single Mode Panel ─── */
function SingleModePanel({ isFinal, report, templates, findings, setFindings, impression, setImpression,
  recommendation, setRecommendation, urgency, setUrgency, saving, handleSave, handleSign,
  applyTemplate, insertMacro, viewerUrl, studyUID, studyInfo, mode, showToast }: any) {

  return (
    <div className="w-[400px] bg-white border-l border-slate-200 flex flex-col h-full">
      <div className="px-4 py-3 bg-slate-50 border-b border-slate-200 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <h2 className="font-bold text-sm text-slate-800">판독 리포트</h2>
          <SingleModeStatusBadge report={report} />
        </div>
        <div className="flex gap-2 text-xs">
          <a href={`/pacs-admin/reading/view?study=${studyUID}&mode=dual`} className="text-slate-500 hover:text-blue-600 transition">듀얼</a>
          <a href={viewerUrl} target="_blank" className="text-blue-600 hover:underline">뷰어 ↗</a>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4" style={{ maxHeight: 'calc(100vh - 120px)' }}>
        {/* AI Buttons (compact for single mode) */}
        {!isFinal && (
          <SingleModeAI studyUID={studyUID} modality={studyInfo?.modality || findings} setFindings={setFindings} setImpression={setImpression} setRecommendation={setRecommendation} showToast={showToast} />
        )}
        {/* Templates */}
        {!isFinal && templates.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {templates.map((t: Template) => (
              <button key={t.id} onClick={() => applyTemplate(t)}
                className="text-xs bg-slate-100 hover:bg-blue-50 hover:text-blue-700 px-2.5 py-1 rounded-lg transition">{t.modality}</button>
            ))}
          </div>
        )}

        {/* Findings */}
        <div>
          <label className="text-xs font-semibold text-slate-500 mb-1.5 flex items-center gap-1">
            소견 <span className="text-red-400">*</span>
          </label>
          {isFinal ? <div className="bg-slate-50 rounded-xl p-3 text-sm border border-slate-200">{findings}</div> :
            <textarea rows={8} value={findings} onChange={(e: any) => setFindings(e.target.value)}
              className="w-full border border-slate-200 rounded-xl p-3 text-sm resize-y outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-200" />}
        </div>

        {/* Impression */}
        <div>
          <label className="text-xs font-semibold text-slate-500 mb-1.5 flex items-center gap-1">
            결론 <span className="text-red-400">*</span>
          </label>
          {isFinal ? <div className="bg-emerald-50 rounded-xl p-3 text-sm text-emerald-900 border border-emerald-200">{impression}</div> :
            <textarea rows={4} value={impression} onChange={(e: any) => setImpression(e.target.value)}
              className="w-full border border-slate-200 rounded-xl p-3 text-sm resize-y outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-200" />}
        </div>

        {/* Recommendation */}
        <div>
          <label className="text-xs font-semibold text-slate-500 block mb-1.5">권고</label>
          {isFinal ? <div className="bg-slate-50 rounded-xl p-3 text-sm border border-slate-200">{recommendation || '-'}</div> :
            <textarea rows={2} value={recommendation} onChange={(e: any) => setRecommendation(e.target.value)}
              className="w-full border border-slate-200 rounded-xl p-3 text-sm outline-none" />}
        </div>
      </div>

      {!isFinal && (
        <div className="px-4 py-3 border-t border-slate-200 flex gap-2 shrink-0">
          <button onClick={handleSave} className="flex-1 bg-blue-600 text-white py-2.5 rounded-xl text-sm font-semibold hover:bg-blue-700 transition">{saving ? '...' : '저장'}</button>
          <button onClick={handleSign} className="flex-1 bg-emerald-600 text-white py-2.5 rounded-xl text-sm font-semibold hover:bg-emerald-700 transition">서명</button>
        </div>
      )}
    </div>
  );
}

/* ─── Single Mode Status Badge (inline) ─── */
function SingleModeStatusBadge({ report }: { report: any }) {
  if (!report) return <span className="px-2.5 py-1 rounded-lg text-xs font-semibold bg-blue-50 text-blue-600 border border-blue-100">새 리포트</span>;
  const config: Record<string, { bg: string; text: string; label: string }> = {
    final: { bg: 'bg-emerald-50 border-emerald-200', text: 'text-emerald-700', label: '판독 완료' },
    preliminary: { bg: 'bg-violet-50 border-violet-200', text: 'text-violet-700', label: '예비 판독' },
    draft: { bg: 'bg-amber-50 border-amber-200', text: 'text-amber-700', label: '작성 중' },
  };
  const c = config[report.status] || { bg: 'bg-slate-50 border-slate-200', text: 'text-slate-600', label: report.status };
  return <span className={`px-2.5 py-1 rounded-lg text-xs font-semibold border ${c.bg} ${c.text}`}>{c.label}</span>;
}

/* ─── Single Mode AI Buttons (compact) ─── */
function SingleModeAI({ studyUID, modality, setFindings, setImpression, setRecommendation, showToast }: any) {
  const [loading, setLoading] = useState<string | null>(null);
  const [prodPipeline, setProdPipeline] = useState<string | null>(null);

  const PIPE_MODS: Record<string, string[]> = {
    'chest-xray': ['CR', 'DX'], 'ct-abdomen': ['CT'], 'emergency-triage': ['CR', 'DX', 'CT'],
    'medical': ['CR', 'DX', 'CT', 'MR', 'US'], 'consensus': ['CR', 'DX', 'CT', 'MR'],
  };

  useEffect(() => {
    apiFetch<Record<string, any>>('/api/v1/ai/orchestration/production').then(d => {
      if (d?.reading?.pipeline) setProdPipeline(d.reading.pipeline);
    }).catch(() => {});
  }, []);

  const pipelineMatch = prodPipeline && (() => {
    const mods = PIPE_MODS[prodPipeline];
    return !mods || mods.some(m => (modality || '').toUpperCase().includes(m));
  })();

  const run = async (key: string, path: string, body: any, apply: (res: any) => void) => {
    setLoading(key);
    try {
      const res = await apiFetch<any>(path, { method: 'POST', body: JSON.stringify(body) });
      apply(res);
    } catch (e: any) { showToast?.(e.message); }
    setLoading(null);
  };

  return (
    <div className="flex flex-wrap gap-1.5">
      <button disabled={loading !== null} onClick={() => run('ai', '/api/v1/ai/analyze-and-draft',
        { study_instance_uid: studyUID, auto_create_report: false },
        (res) => { if (res?.ai_analysis) { setFindings(res.ai_analysis.findings || ''); setImpression(res.ai_analysis.impression || ''); setRecommendation(() => res.ai_analysis.recommendations || ''); showToast?.('AI 완료'); } }
      )} className="bg-violet-600 text-white px-2.5 py-1 rounded text-xs font-semibold disabled:opacity-50">
        {loading === 'ai' ? '...' : 'AI 분석'}
      </button>

      {pipelineMatch && (
        <button disabled={loading !== null} onClick={() => run('pipe', '/api/v1/ai/orchestration/run',
          { pipeline: prodPipeline, study_instance_uid: studyUID, debug: false },
          (res) => { if (res?.result) { setFindings(res.result); showToast?.('파이프라인 완료'); } }
        )} className="bg-green-600 text-white px-2.5 py-1 rounded text-xs font-semibold disabled:opacity-50">
          {loading === 'pipe' ? '...' : `🔗 ${prodPipeline}`}
        </button>
      )}

      <button disabled={loading !== null} onClick={() => run('cmp', '/api/v1/ai/compare-studies',
        { current_study_uid: studyUID },
        (res) => { if (res?.comparison?.text) { setFindings((prev: string) => prev + '\n\n--- 비교 ---\n' + res.comparison.text); showToast?.('비교 완료'); } }
      )} className="bg-indigo-500 text-white px-2.5 py-1 rounded text-xs font-semibold disabled:opacity-50">
        {loading === 'cmp' ? '...' : '비교'}
      </button>
    </div>
  );
}
