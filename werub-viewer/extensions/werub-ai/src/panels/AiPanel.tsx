import React, { useState, useEffect, useCallback } from 'react';
import { useViewportGrid } from '@ohif/ui-next';
import AiActionButton from '../components/AiActionButton';
import AiResultCard from '../components/AiResultCard';
import ServerStatus from '../components/ServerStatus';

/** Parse **소견** / **결론** / **권고사항** sections from pipeline result text */
function parsePipelineSections(text: string): { findings: string; impression: string; recommendation: string } {
  const sectionMap: Record<string, 'findings' | 'impression' | 'recommendation'> = {
    '소견': 'findings', 'findings': 'findings',
    '결론': 'impression', 'impression': 'impression', '판독소견': 'impression',
    '권고사항': 'recommendation', 'recommendation': 'recommendation', '권고': 'recommendation',
  };
  const result: { findings: string; impression: string; recommendation: string } = { findings: '', impression: '', recommendation: '' };
  // Try to split by markdown headers: **소견**, **결론**, **권고사항**
  const regex = /\*\*([^*]+)\*\*/g;
  const parts: { key: string; start: number }[] = [];
  let m: RegExpExecArray | null;
  while ((m = regex.exec(text)) !== null) {
    const label = m[1].trim().toLowerCase().replace(/[:\s]/g, '');
    const mapped = Object.entries(sectionMap).find(([k]) => label.includes(k));
    if (mapped) parts.push({ key: mapped[1], start: m.index + m[0].length });
  }
  if (parts.length >= 2) {
    for (let i = 0; i < parts.length; i++) {
      const end = i + 1 < parts.length ? text.lastIndexOf('**', parts[i + 1].start - 2) : text.length;
      result[parts[i].key] = text.slice(parts[i].start, end).trim().replace(/^\n+|\n+$/g, '');
    }
    return result;
  }
  // Fallback: entire text as findings
  result.findings = text;
  return result;
}

function AiPanel({ servicesManager }) {
  const { aiService, reportService, displaySetService, uiNotificationService } = servicesManager?.services || {};

  const [viewportGrid] = useViewportGrid();
  const [loading, setLoading] = useState<string | null>(null); // which action is loading
  const [result, setResult] = useState<{ type: string; content: string; raw?: any } | null>(null);
  const [models, setModels] = useState<any[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>(''); // '' → server default (MedGemma)

  // Study UID from active viewport
  const studyUID = (() => {
    try {
      const { viewports, activeViewportId } = viewportGrid;
      const vp = viewports?.get(activeViewportId);
      if (!vp?.displaySetInstanceUIDs?.length) return null;
      const ds = displaySetService?.getDisplaySetByUID(vp.displaySetInstanceUIDs[0]);
      return ds?.StudyInstanceUID || null;
    } catch { return null; }
  })();

  // Get current findings from reportService
  const currentFindings = reportService?.currentReport?.findings || '';
  const currentImpression = reportService?.currentReport?.impression || '';

  // Load available AI models for the picker (active only)
  useEffect(() => {
    let cancelled = false;
    if (!aiService?.getModels) return;
    aiService.getModels().then((m: any[]) => { if (!cancelled) setModels(m || []); }).catch(() => {});
    return () => { cancelled = true; };
  }, [aiService]);

  // Subscribe to loading events
  useEffect(() => {
    if (!aiService?.subscribe) return;
    const sub = aiService.subscribe('loadingChanged', ({ loading: l }) => {
      if (!l) setLoading(null);
    });
    return () => sub.unsubscribe();
  }, [aiService]);

  // 저장된 표준 추론 결과 (TID 1500 SR) — OHIF SR 뷰포트가 렌더 못하므로 패널에 표시
  const [storedJob, setStoredJob] = useState<any>(null);
  useEffect(() => {
    let cancelled = false;
    if (!studyUID || !aiService?.getStudyResult) { setStoredJob(null); return; }
    aiService.getStudyResult(studyUID).then((j: any) => { if (!cancelled) setStoredJob(j); });
    return () => { cancelled = true; };
  }, [studyUID, aiService]);

  // --- Actions ---
  const handleAnalyze = useCallback(async () => {
    if (!studyUID || !aiService) return;
    setLoading('analyze');
    const res = await aiService.analyzeStudy(studyUID, selectedModel || null);
    if (res) {
      setResult({
        type: 'analyze',
        content: `소견: ${res.findings || '-'}\n\n결론: ${res.impression || '-'}${res.recommendations ? '\n\n권고: ' + res.recommendations : ''}`,
        raw: res,
      });
      uiNotificationService?.show({ title: 'AI 분석', message: `완료 (${res.duration_ms}ms)`, type: 'success', duration: 2000 });
    } else {
      uiNotificationService?.show({ title: 'AI 분석', message: '분석 실패', type: 'error', duration: 3000 });
    }
    setLoading(null);
  }, [studyUID, aiService, selectedModel]);

  const handleCompare = useCallback(async () => {
    if (!studyUID || !aiService) return;
    setLoading('compare');
    const res = await aiService.compareStudies(studyUID);
    if (res?.comparison?.text || res?.text) {
      const text = res.comparison?.text || res.text;
      setResult({ type: 'compare', content: text, raw: res });
      uiNotificationService?.show({ title: '비교', message: `완료 (${res.comparison?.progression || ''})`, type: 'success', duration: 2000 });
    } else {
      setResult({ type: 'compare', content: res?.message || '이전 검사 없음' });
    }
    setLoading(null);
  }, [studyUID, aiService]);

  const handleSoap = useCallback(async () => {
    if (!aiService || !currentFindings) return;
    setLoading('soap');
    const res = await aiService.soapSummary(currentFindings, currentImpression);
    if (res?.summary) {
      const s = res.summary;
      const text = `S: ${s.subjective || '-'}\nO: ${s.objective || '-'}\nA: ${s.assessment || '-'}\nP: ${s.plan || '-'}${res.icd_codes?.length ? '\n\nICD-10: ' + res.icd_codes.join(', ') : ''}`;
      setResult({ type: 'soap', content: text, raw: res });
    } else {
      uiNotificationService?.show({ title: 'SOAP', message: res?.error || '실패', type: 'error', duration: 3000 });
    }
    setLoading(null);
  }, [aiService, currentFindings, currentImpression]);

  const handleDdx = useCallback(async () => {
    if (!aiService || !currentFindings) return;
    setLoading('ddx');
    const res = await aiService.differentialDiagnosis(currentFindings, currentImpression);
    if (res?.differential_diagnosis?.length) {
      const text = res.differential_diagnosis.map((d, i) =>
        `${i + 1}. ${d.condition || d.name || d.diagnosis} (${d.icd_code || d.icd10 || ''}) — ${d.probability || d.confidence || ''}`
      ).join('\n');
      setResult({ type: 'ddx', content: text, raw: res });
    } else {
      uiNotificationService?.show({ title: '감별진단', message: res?.error || '결과 없음', type: 'error', duration: 3000 });
    }
    setLoading(null);
  }, [aiService, currentFindings, currentImpression]);

  const [applying, setApplying] = useState(false);

  const handleApplyToReport = useCallback(async () => {
    if (!result?.raw || !aiService || applying) return;
    setApplying(true);
    const raw = result.raw;
    const data: any = {};
    if (result.type === 'analyze') {
      data.findings = raw.findings || '';
      data.impression = raw.impression || '';
      if (raw.recommendations) data.recommendation = raw.recommendations;
    } else if (result.type === 'compare' && raw.text) {
      data.findings = (currentFindings ? currentFindings + '\n\n' : '') + '--- 이전 검사 비교 ---\n' + raw.text;
    } else if (result.type === 'soap' && raw.summary) {
      const s = raw.summary;
      data.recommendation = `[SOAP]\nS: ${s.subjective || '-'}\nO: ${s.objective || '-'}\nA: ${s.assessment || '-'}\nP: ${s.plan || '-'}`;
    } else if (result.type === 'ddx' && raw.differential_diagnosis) {
      data.impression = (currentImpression ? currentImpression + '\n\n' : '') + '--- 감별진단 ---\n' + result.content;
    } else if (result.type === 'pipeline') {
      data.findings = raw.findings || result.content || '';
      if (raw.impression) data.impression = raw.impression;
      if (raw.recommendation) data.recommendation = raw.recommendation;
    }
    console.log('[AiPanel] applyToReport', { studyUID, data: Object.keys(data) });
    await aiService.applyToReport(data, studyUID || undefined);
    uiNotificationService?.show({ title: 'AI 결과', message: studyUID ? '판독 리포트에 적용됨' : '뷰어에만 적용됨 (Study UID 없음)', type: studyUID ? 'success' : 'warning', duration: 3000 });
    setApplying(false);
  }, [result, aiService, studyUID, currentFindings, currentImpression, applying]);

  const handleSaveSR = useCallback(async () => {
    if (!result?.raw || !studyUID || !aiService || applying) return;
    setApplying(true);
    const raw = result.raw;
    const findings = raw.findings || result.content || '';
    const impression = raw.impression || '';
    const res = await aiService.saveAsSR(studyUID, findings, impression);
    if (res) {
      uiNotificationService?.show({ title: 'DICOM SR', message: 'SR 저장 완료', type: 'success', duration: 2000 });
    } else {
      uiNotificationService?.show({ title: 'DICOM SR', message: 'SR 저장 실패', type: 'error', duration: 3000 });
    }
    setApplying(false);
  }, [result, studyUID, aiService, applying]);

  const handleCopy = useCallback(() => {
    if (result?.content) {
      navigator.clipboard.writeText(result.content).catch(() => {});
      uiNotificationService?.show({ title: '복사', message: '클립보드에 복사됨', type: 'info', duration: 1500 });
    }
  }, [result]);

  // Pipeline (hooks must be before any conditional return)
  const [prodPipeline, setProdPipeline] = useState<string | null>(null);
  const [pipelineResult, setPipelineResult] = useState<string | null>(null);

  useEffect(() => {
    if (!aiService?.getProductionPipeline) return;
    aiService.getProductionPipeline().then(p => {
      if (p?.pipeline) setProdPipeline(p.pipeline);
    });
  }, [aiService]);

  // --- No study ---
  if (!studyUID) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-sm text-gray-500">
        Study를 선택하세요
      </div>
    );
  }

  const handlePipeline = useCallback(async () => {
    if (!studyUID || !aiService || !prodPipeline) return;
    setLoading('pipeline');
    const res = await aiService.runPipeline(prodPipeline, studyUID);
    if (res?.result) {
      // Parse structured sections from pipeline result text
      const parsed = parsePipelineSections(res.result);
      setResult({
        type: 'pipeline',
        content: res.result,
        raw: { ...parsed, duration_ms: res.total_duration_ms },
      });
      uiNotificationService?.show({
        title: `🔗 ${prodPipeline}`,
        message: `완료 (${((res.total_duration_ms || 0) / 1000).toFixed(1)}초)`,
        type: 'success', duration: 3000,
      });
    } else {
      uiNotificationService?.show({ title: '파이프라인', message: '실행 실패', type: 'error', duration: 3000 });
    }
    setLoading(null);
  }, [studyUID, aiService, prodPipeline]);

  const needsFindings = !currentFindings;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#333] px-3 py-2">
        <span className="text-sm font-semibold text-gray-200">AI 분석</span>
        <ServerStatus aiService={aiService} />
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {/* 저장된 표준 AI 판독 (TID 1500 SR) — OHIF SR 뷰포트가 렌더 못하므로 패널에 표시 */}
        {storedJob && Array.isArray(storedJob?.results?.findings) && storedJob.results.findings.length > 0 && (
          <div className="rounded border border-blue-700/40 bg-blue-950/30 p-2.5">
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-xs font-semibold text-blue-300">🤖 저장된 AI 판독</span>
              <span className="rounded bg-blue-700/40 px-1.5 py-0.5 text-[10px] text-blue-200">
                {storedJob.result_dicom_uids?.sr_orthanc_id ? '표준 SR' : '결과'} · {storedJob.model_name || 'AI'}
              </span>
            </div>
            <div className="space-y-1">
              {storedJob.results.findings.map((f: any, i: number) => (
                <div key={i} className="text-xs text-gray-300">
                  <span className={
                    f.severity === 'critical' ? 'text-red-400' :
                    f.severity === 'warning' ? 'text-yellow-400' : 'text-gray-300'
                  }>•</span>{' '}
                  {f.description || f.type}
                  {typeof f.confidence === 'number' && (
                    <span className="ml-1 text-blue-400">({Math.round(f.confidence * 100)}%)</span>
                  )}
                </div>
              ))}
            </div>
            {storedJob.is_critical && (
              <div className="mt-1.5 rounded bg-red-900/40 px-1.5 py-0.5 text-[10px] font-semibold text-red-300">
                ⚠ 긴급 소견 감지
              </div>
            )}
            <div className="mt-1 text-[10px] text-gray-500">
              {storedJob.completed_at ? new Date(storedJob.completed_at).toLocaleString('ko-KR') : ''}
              {storedJob.inference_time_ms ? ` · ${storedJob.inference_time_ms}ms` : ''}
            </div>
          </div>
        )}

        {/* AI 모델 선택 */}
        {models.length > 0 && (
          <div className="mb-1">
            <label className="mb-0.5 block text-[10px] font-medium text-gray-400">AI 모델</label>
            <select
              value={selectedModel}
              onChange={e => setSelectedModel(e.target.value)}
              className="w-full rounded border border-gray-600 bg-gray-800 px-2 py-1 text-xs text-gray-200 focus:border-blue-500 focus:outline-none"
              title="영상 분석에 사용할 AI 모델을 선택합니다"
            >
              <option value="">기본 (MedGemma)</option>
              {models.map((m: any) => (
                <option key={m.id || m.name} value={m.name}>
                  {m.name}{m.clinical_use === 'research' ? ' · 연구용' : ''}
                  {m.modalities ? ` · ${m.modalities}` : ''}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Action Buttons */}
        <AiActionButton
          label="AI 영상 분석"
          description="Study 영상을 AI로 분석하여 판독 초안을 생성합니다"
          loading={loading === 'analyze'}
          variant="primary"
          onClick={handleAnalyze}
        />
        <AiActionButton
          label="이전 검사 비교"
          description="동일 환자의 이전 검사와 변화를 비교합니다"
          loading={loading === 'compare'}
          onClick={handleCompare}
        />
        <AiActionButton
          label="SOAP 요약"
          description="소견을 SOAP 형식으로 정리합니다"
          loading={loading === 'soap'}
          disabled={needsFindings}
          disabledReason="소견을 먼저 입력하세요 (판독 패널)"
          onClick={handleSoap}
        />
        <AiActionButton
          label="감별진단"
          description="가능한 진단명과 확률을 제안합니다"
          loading={loading === 'ddx'}
          disabled={needsFindings}
          disabledReason="소견을 먼저 입력하세요 (판독 패널)"
          onClick={handleDdx}
        />

        {/* Pipeline Button */}
        {prodPipeline && (
          <>
            <div className="border-t border-[#333] my-2 pt-2">
              <span className="text-[10px] text-gray-500 uppercase tracking-wider">파이프라인</span>
            </div>
            <AiActionButton
              label={`🔗 ${prodPipeline}`}
              description="다중 모델 파이프라인으로 종합 분석합니다"
              loading={loading === 'pipeline'}
              variant="primary"
              onClick={handlePipeline}
            />
          </>
        )}

        {/* Result Card */}
        {result && (
          <AiResultCard
            title={
              result.type === 'analyze' ? 'AI 분석 결과' :
              result.type === 'compare' ? '이전 검사 비교' :
              result.type === 'soap' ? 'SOAP 요약' :
              result.type === 'ddx' ? '감별진단' :
              result.type === 'pipeline' ? `🔗 ${prodPipeline || '파이프라인'}` : '결과'
            }
            content={result.content}
            duration_ms={result.raw?.duration_ms}
            disabled={applying}
            onApply={result.raw ? handleApplyToReport : undefined}
            onSaveSR={(result.type === 'analyze' || result.type === 'pipeline') && result.raw ? handleSaveSR : undefined}
            onCopy={handleCopy}
          />
        )}
      </div>
    </div>
  );
}

export default AiPanel;
