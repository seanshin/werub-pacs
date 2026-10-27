import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useViewportGrid } from '@ohif/ui-next';
import StatusBadge from '../components/StatusBadge';
import TemplateSelector from '../components/TemplateSelector';
import MacroBar from '../components/MacroBar';
import ReportForm from '../components/ReportForm';
import KeyImagesBar from '../components/KeyImagesBar';
import { PreliminaryInfo, PreliminaryDiff } from '../components/PreliminaryDiff';
import type { Report, Template } from '../services/ReportService';

function ReportPanel({ servicesManager }) {
  const { reportService, displaySetService, uiNotificationService } = servicesManager?.services || {};

  const [viewportGrid] = useViewportGrid();
  const [authenticated, setAuthenticated] = useState(reportService?.isAuthenticated ?? false);
  const [report, setReport] = useState<Report | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(false);
  const [findings, setFindings] = useState('');
  const [impression, setImpression] = useState('');
  const [recommendation, setRecommendation] = useState('');
  const [urgency, setUrgency] = useState('normal');
  const studyOpenTime = useRef<number>(Date.now());
  const [readingTime, setReadingTime] = useState<number>(0);
  const [loginForm, setLoginForm] = useState({ username: '', password: '' });

  // --- Study UID detection from active viewport ---
  const studyUID = (() => {
    try {
      const { viewports, activeViewportId } = viewportGrid;
      const vp = viewports?.get(activeViewportId);
      if (!vp?.displaySetInstanceUIDs?.length) return null;
      const ds = displaySetService.getDisplaySetByUID(vp.displaySetInstanceUIDs[0]);
      return ds?.StudyInstanceUID || null;
    } catch {
      return null;
    }
  })();

  // --- Load report when study changes ---
  useEffect(() => {
    if (studyUID && authenticated) {
      reportService.loadReport(studyUID);
      reportService.loadTemplates();
      studyOpenTime.current = Date.now();
      setReadingTime(0);
    }
  }, [studyUID, authenticated]);

  // --- Subscribe to service events ---
  useEffect(() => {
    if (!reportService?.subscribe) return;
    const subs = [
      reportService.subscribe('reportLoaded', ({ report: r }) => {
        setReport(r);
        if (r) {
          setFindings(r.findings || '');
          setImpression(r.impression || '');
          setRecommendation(r.recommendation || '');
          setUrgency(r.urgency || 'normal');
        } else {
          setFindings(''); setImpression(''); setRecommendation(''); setUrgency('normal');
        }
      }),
      reportService.subscribe('reportSaved', () => {
        uiNotificationService.show({ title: '저장', message: '임시 저장됨', type: 'success', duration: 2000 });
      }),
      reportService.subscribe('reportSigned', ({ report: r }) => {
        setReport(r);
        uiNotificationService.show({ title: '서명', message: '판독 서명 완료!', type: 'success', duration: 3000 });
      }),
      reportService.subscribe('templatesLoaded', ({ templates: t }) => {
        setTemplates(t);
      }),
      reportService.subscribe('authChanged', ({ authenticated: a }) => {
        setAuthenticated(a);
      }),
      reportService.subscribe('loadingChanged', ({ loading: l }) => {
        setLoading(l);
      }),
    ];
    return () => subs.forEach(s => s.unsubscribe());
  }, []);

  // --- Measurement auto-insert ---
  useEffect(() => {
    const { measurementService } = servicesManager?.services || {};
    if (!measurementService?.subscribe) return;
    const sub = measurementService.subscribe(
      measurementService.EVENTS?.MEASUREMENT_ADDED || 'event::measurementService:measurementAdded',
      ({ measurement }) => {
        if (!measurement) return;
        const label = measurement.label || measurement.type || 'Measurement';
        const value = measurement.displayText?.join(', ') || measurement.text || '';
        if (value) {
          setFindings(prev => prev + (prev ? '\n' : '') + `[${label}] ${value}`);
        }
      }
    );
    return () => sub.unsubscribe();
  }, [servicesManager]);

  // --- Keyboard shortcuts ---
  // Attach the listener ONCE (empty deps) and call the latest handleSign via a
  // ref. Previously the effect had no deps array, so it re-added the listener on
  // every render/keystroke. (A [handleSign] dep wouldn't help — handleSign's
  // identity changes on each keystroke — and would also TDZ-reference it before
  // its declaration below.)
  const handleSignRef = useRef<(asPreliminary?: boolean) => void>(() => {});
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); handleSignRef.current(false); }
      if (e.ctrlKey && e.key === 'p') { e.preventDefault(); handleSignRef.current(true); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // --- Actions ---
  const handleSave = useCallback(async () => {
    await reportService.save({ findings, impression, recommendation, urgency });
  }, [findings, impression, recommendation, urgency]);

  const handleSign = useCallback(async (asPreliminary = false) => {
    if (!findings || !impression) {
      uiNotificationService.show({ title: '오류', message: '소견과 결론을 입력하세요', type: 'warning', duration: 3000 });
      return;
    }
    await reportService.save({ findings, impression, recommendation, urgency });
    await reportService.sign(asPreliminary);
    const tat = Math.round((Date.now() - studyOpenTime.current) / 1000);
    setReadingTime(tat);
  }, [findings, impression, recommendation, urgency]);
  handleSignRef.current = handleSign;  // keep the keydown handler calling the latest

  const handleFinalize = useCallback(async () => {
    if (!findings || !impression) {
      uiNotificationService.show({ title: '오류', message: '소견과 결론을 입력하세요', type: 'warning', duration: 3000 });
      return;
    }
    await reportService.finalize({ findings, impression, recommendation } as any);
    const tat = Math.round((Date.now() - studyOpenTime.current) / 1000);
    setReadingTime(tat);
    uiNotificationService.show({ title: '확정', message: '최종 서명 완료!', type: 'success', duration: 3000 });
  }, [findings, impression, recommendation]);

  const handleLogin = async () => {
    const ok = await reportService.login(loginForm.username, loginForm.password);
    if (!ok) {
      uiNotificationService.show({ title: '로그인 실패', message: '사용자명 또는 비밀번호를 확인하세요', type: 'error', duration: 3000 });
    }
  };

  const applyTemplate = (t: Template) => {
    if (t.normal_template) setFindings(t.normal_template);
    if (t.impression_template) setImpression(t.impression_template);
  };

  const insertMacro = (text: string) => {
    setFindings(prev => prev + text);
  };

  const handleChange = (field: string, value: string) => {
    if (field === 'findings') setFindings(value);
    else if (field === 'impression') setImpression(value);
    else if (field === 'recommendation') setRecommendation(value);
    else if (field === 'urgency') setUrgency(value);
  };

  // --- Login Form ---
  if (!authenticated) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-4">
        <div className="w-full max-w-[280px] space-y-3">
          <h3 className="text-center text-sm font-semibold text-gray-200">판독 로그인</h3>
          <input
            type="text"
            placeholder="사용자명"
            value={loginForm.username}
            onChange={e => setLoginForm(p => ({ ...p, username: e.target.value }))}
            className="w-full rounded bg-[#0f1629] border border-[#333] p-2 text-sm text-gray-200"
          />
          <input
            type="password"
            placeholder="비밀번호"
            value={loginForm.password}
            onChange={e => setLoginForm(p => ({ ...p, password: e.target.value }))}
            onKeyDown={e => e.key === 'Enter' && handleLogin()}
            className="w-full rounded bg-[#0f1629] border border-[#333] p-2 text-sm text-gray-200"
          />
          <button
            onClick={handleLogin}
            className="w-full rounded bg-blue-600 py-2 text-sm font-semibold text-white hover:bg-blue-700"
          >
            로그인
          </button>
          {/* Test account buttons removed for security — use proper credentials */}
        </div>
      </div>
    );
  }

  // --- No study selected ---
  if (!studyUID) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-sm text-gray-500">
        Study를 선택하세요
      </div>
    );
  }

  // --- Loading ---
  if (loading && !report) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-sm text-gray-500">
        로딩 중...
      </div>
    );
  }

  const isFinal = report?.status === 'final';
  const isPreliminary = report?.status === 'preliminary';
  const isReadOnly = isFinal;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#333] px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-gray-200">판독 리포트</span>
          {report?.author_name?.startsWith('AI') && (
            <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold bg-purple-700/40 text-purple-400">AI 초안</span>
          )}
        </div>
        <StatusBadge status={report?.status} />
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {!isReadOnly && <TemplateSelector templates={templates} onApply={applyTemplate} />}

        {/* Preliminary original content (collapsible) */}
        {isPreliminary && report?.preliminary_by_name && (
          <PreliminaryInfo report={report} />
        )}

        <ReportForm
          findings={findings}
          impression={impression}
          recommendation={recommendation}
          urgency={urgency}
          readOnly={isReadOnly}
          onChange={handleChange}
        />

        {!isReadOnly && <MacroBar templates={templates} onInsert={insertMacro} />}

        {/* Signing info */}
        {(isFinal || isPreliminary) && (
          <div className="rounded bg-[#0f1629] p-2 text-xs text-gray-500 space-y-0.5">
            {report?.signed_by_name && (
              <div>
                판독의: <span className="text-gray-300">{report.signed_by_name}</span>
                {report.signed_at && <> · {new Date(report.signed_at).toLocaleString('ko-KR')}</>}
              </div>
            )}
            {report?.preliminary_by_name && (
              <div>
                예비판독: <span className="text-blue-400">{report.preliminary_by_name}</span>
                {report.preliminary_at && <> · {new Date(report.preliminary_at).toLocaleString('ko-KR')}</>}
              </div>
            )}
          </div>
        )}

        {/* Final-only: show preliminary original if available */}
        {isFinal && report?.preliminary_content && (
          <PreliminaryDiff content={report.preliminary_content} />
        )}

        {/* Reading time */}
        {readingTime > 0 && (
          <div className="rounded bg-[#0f1629] p-2 text-[11px] text-gray-500">
            판독 소요: <span className="text-blue-400 font-semibold">{Math.floor(readingTime / 60)}분 {readingTime % 60}초</span>
          </div>
        )}

        {/* Key images (KOS) + measurement persistence */}
        <KeyImagesBar
          servicesManager={servicesManager}
          reportService={reportService}
          studyUID={studyUID}
          readOnly={isReadOnly}
        />

        {/* Today's reading stats */}
        <TodayStats />
      </div>

      {/* Footer — Draft: 3 buttons / Preliminary: 2 buttons / Final: addendum */}
      {!isFinal && !isPreliminary && (
        <div className="flex gap-2 border-t border-[#333] px-3 py-2">
          <button onClick={handleSave} disabled={loading}
            className="flex-1 rounded bg-blue-600 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50">
            임시 저장
          </button>
          <button onClick={() => handleSign(true)} disabled={loading}
            className="flex-1 rounded bg-purple-600 py-2 text-sm font-semibold text-white hover:bg-purple-700 disabled:opacity-50">
            예비 서명
          </button>
          <button onClick={() => handleSign(false)} disabled={loading}
            className="flex-1 rounded bg-green-600 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50">
            최종 서명
          </button>
        </div>
      )}
      {isPreliminary && (
        <div className="flex gap-2 border-t border-[#333] px-3 py-2">
          <button onClick={handleSave} disabled={loading}
            className="flex-1 rounded bg-blue-600 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50">
            임시 저장
          </button>
          <button onClick={handleFinalize} disabled={loading}
            className="flex-1 rounded bg-green-600 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50">
            최종 서명 (확정)
          </button>
        </div>
      )}
      {isFinal && (
        <div className="border-t border-[#333] px-3 py-2">
          <button onClick={() => reportService.addendum()}
            className="w-full rounded border border-[#444] py-2 text-sm text-gray-400 hover:text-gray-200">
            수정본 추가
          </button>
        </div>
      )}
    </div>
  );
}

function TodayStats() {
  const [stats, setStats] = useState<any>(null);
  useEffect(() => {
    const token = typeof localStorage !== 'undefined' ? localStorage.getItem('pacs_token') : null;
    if (!token) return;
    const today = new Date().toISOString().split('T')[0];
    fetch(`/pacs-api/api/v1/reports/statistics?from_date=${today}&to_date=${today}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setStats(d); })
      .catch(() => {});
  }, []);

  if (!stats) return null;
  const total = stats.total_reports || stats.total || 0;
  const signed = stats.signed_reports || stats.signed || 0;

  return (
    <div className="mt-2 rounded bg-[#0f1629] p-2">
      <div className="text-[10px] text-gray-500 mb-1">오늘 판독</div>
      <div className="flex gap-3 text-xs">
        <span className="text-gray-300">{total}건</span>
        <span className="text-green-400">{signed} 완료</span>
        <span className="text-yellow-400">{total - signed} 대기</span>
      </div>
    </div>
  );
}

export default ReportPanel;
