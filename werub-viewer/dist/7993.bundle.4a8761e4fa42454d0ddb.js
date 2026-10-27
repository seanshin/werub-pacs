"use strict";
(globalThis["webpackChunk"] = globalThis["webpackChunk"] || []).push([[7993],{

/***/ 7993:
/***/ ((__unused_webpack_module, __webpack_exports__, __webpack_require__) => {

// ESM COMPAT FLAG
__webpack_require__.r(__webpack_exports__);

// EXPORTS
__webpack_require__.d(__webpack_exports__, {
  "default": () => (/* binding */ panels_AiPanel)
});

// EXTERNAL MODULE: ../../../node_modules/react/index.js
var react = __webpack_require__(86326);
// EXTERNAL MODULE: ../../ui-next/src/index.ts + 3075 modules
var src = __webpack_require__(12517);
;// ../../../extensions/werub-ai/src/components/AiActionButton.tsx

function AiActionButton({
  label,
  description,
  loading,
  disabled,
  disabledReason,
  variant = 'secondary',
  onClick
}) {
  const isPrimary = variant === 'primary';
  const isDisabled = disabled || loading;
  return /*#__PURE__*/react.createElement("button", {
    onClick: onClick,
    disabled: isDisabled,
    title: disabled ? disabledReason : undefined,
    className: `w-full rounded-lg px-3 py-2.5 text-left transition ${isDisabled ? 'opacity-40 cursor-not-allowed' : isPrimary ? 'bg-purple-600/20 border border-purple-500/40 hover:bg-purple-600/30' : 'bg-[#1e293b] border border-[#334155] hover:bg-[#334155]'}`
  }, /*#__PURE__*/react.createElement("div", {
    className: "flex items-center justify-between"
  }, /*#__PURE__*/react.createElement("span", {
    className: `text-sm font-semibold ${isPrimary ? 'text-purple-300' : 'text-gray-200'}`
  }, label), loading && /*#__PURE__*/react.createElement("span", {
    className: "text-xs text-gray-400 animate-pulse"
  }, "\uBD84\uC11D \uC911...")), /*#__PURE__*/react.createElement("div", {
    className: "text-xs text-gray-500 mt-0.5"
  }, description));
}
;// ../../../extensions/werub-ai/src/components/AiResultCard.tsx

function AiResultCard({
  title,
  content,
  duration_ms,
  disabled,
  onApply,
  onCopy,
  onSaveSR
}) {
  if (!content) return null;
  return /*#__PURE__*/react.createElement("div", {
    className: "rounded-lg border border-purple-500/30 bg-purple-900/10 p-3"
  }, /*#__PURE__*/react.createElement("div", {
    className: "flex items-center justify-between mb-2"
  }, /*#__PURE__*/react.createElement("span", {
    className: "text-xs font-semibold text-purple-300"
  }, title), duration_ms && /*#__PURE__*/react.createElement("span", {
    className: "text-[10px] text-gray-500"
  }, duration_ms, "ms")), /*#__PURE__*/react.createElement("div", {
    className: "text-sm text-gray-300 whitespace-pre-wrap mb-2 max-h-[200px] overflow-y-auto"
  }, content), /*#__PURE__*/react.createElement("div", {
    className: "flex gap-2"
  }, onApply && /*#__PURE__*/react.createElement("button", {
    onClick: onApply,
    disabled: disabled,
    className: "rounded bg-purple-600 px-3 py-1 text-xs font-semibold text-white hover:bg-purple-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
  }, disabled ? '적용 중...' : '판독에 적용'), onSaveSR && /*#__PURE__*/react.createElement("button", {
    onClick: onSaveSR,
    disabled: disabled,
    className: "rounded bg-teal-600 px-3 py-1 text-xs font-semibold text-white hover:bg-teal-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
  }, disabled ? '저장 중...' : 'SR 저장'), onCopy && /*#__PURE__*/react.createElement("button", {
    onClick: onCopy,
    className: "rounded border border-[#444] px-3 py-1 text-xs text-gray-400 hover:text-gray-200 transition"
  }, "\uBCF5\uC0AC")));
}
;// ../../../extensions/werub-ai/src/components/ServerStatus.tsx

function ServerStatus({
  aiService
}) {
  const [status, setStatus] = (0,react.useState)('checking');
  (0,react.useEffect)(() => {
    if (!aiService) return;
    let mounted = true;
    aiService.getServerStatus().then(res => {
      if (!mounted) return;
      setStatus(res?.healthy || res?.ollama_running || res?.status === 'ok' ? 'online' : 'offline');
    }).catch(() => mounted && setStatus('offline'));
    return () => {
      mounted = false;
    };
  }, [aiService]);
  const colors = {
    checking: 'text-gray-500',
    online: 'text-green-400',
    offline: 'text-red-400'
  };
  const labels = {
    checking: '확인 중',
    online: '정상',
    offline: '오프라인'
  };
  return /*#__PURE__*/react.createElement("span", {
    className: `text-[11px] font-medium ${colors[status]}`
  }, status === 'online' ? '●' : status === 'offline' ? '●' : '○', " ", labels[status]);
}
;// ../../../extensions/werub-ai/src/panels/AiPanel.tsx






/** Parse **소견** / **결론** / **권고사항** sections from pipeline result text */
function parsePipelineSections(text) {
  const sectionMap = {
    '소견': 'findings',
    'findings': 'findings',
    '결론': 'impression',
    'impression': 'impression',
    '판독소견': 'impression',
    '권고사항': 'recommendation',
    'recommendation': 'recommendation',
    '권고': 'recommendation'
  };
  const result = {
    findings: '',
    impression: '',
    recommendation: ''
  };
  // Try to split by markdown headers: **소견**, **결론**, **권고사항**
  const regex = /\*\*([^*]+)\*\*/g;
  const parts = [];
  let m;
  while ((m = regex.exec(text)) !== null) {
    const label = m[1].trim().toLowerCase().replace(/[:\s]/g, '');
    const mapped = Object.entries(sectionMap).find(([k]) => label.includes(k));
    if (mapped) parts.push({
      key: mapped[1],
      start: m.index + m[0].length
    });
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
function AiPanel({
  servicesManager
}) {
  const {
    aiService,
    reportService,
    displaySetService,
    uiNotificationService
  } = servicesManager?.services || {};
  const [viewportGrid] = (0,src/* useViewportGrid */.ihW)();
  const [loading, setLoading] = (0,react.useState)(null); // which action is loading
  const [result, setResult] = (0,react.useState)(null);
  const [models, setModels] = (0,react.useState)([]);
  const [selectedModel, setSelectedModel] = (0,react.useState)(''); // '' → server default (MedGemma)

  // Study UID from active viewport
  const studyUID = (() => {
    try {
      const {
        viewports,
        activeViewportId
      } = viewportGrid;
      const vp = viewports?.get(activeViewportId);
      if (!vp?.displaySetInstanceUIDs?.length) return null;
      const ds = displaySetService?.getDisplaySetByUID(vp.displaySetInstanceUIDs[0]);
      return ds?.StudyInstanceUID || null;
    } catch {
      return null;
    }
  })();

  // Get current findings from reportService
  const currentFindings = reportService?.currentReport?.findings || '';
  const currentImpression = reportService?.currentReport?.impression || '';

  // Load available AI models for the picker (active only)
  (0,react.useEffect)(() => {
    let cancelled = false;
    if (!aiService?.getModels) return;
    aiService.getModels().then(m => {
      if (!cancelled) setModels(m || []);
    }).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [aiService]);

  // Subscribe to loading events
  (0,react.useEffect)(() => {
    if (!aiService?.subscribe) return;
    const sub = aiService.subscribe('loadingChanged', ({
      loading: l
    }) => {
      if (!l) setLoading(null);
    });
    return () => sub.unsubscribe();
  }, [aiService]);

  // 저장된 표준 추론 결과 (TID 1500 SR) — OHIF SR 뷰포트가 렌더 못하므로 패널에 표시
  const [storedJob, setStoredJob] = (0,react.useState)(null);
  (0,react.useEffect)(() => {
    let cancelled = false;
    if (!studyUID || !aiService?.getStudyResult) {
      setStoredJob(null);
      return;
    }
    aiService.getStudyResult(studyUID).then(j => {
      if (!cancelled) setStoredJob(j);
    });
    return () => {
      cancelled = true;
    };
  }, [studyUID, aiService]);

  // --- Actions ---
  const handleAnalyze = (0,react.useCallback)(async () => {
    if (!studyUID || !aiService) return;
    setLoading('analyze');
    const res = await aiService.analyzeStudy(studyUID, selectedModel || null);
    if (res) {
      setResult({
        type: 'analyze',
        content: `소견: ${res.findings || '-'}\n\n결론: ${res.impression || '-'}${res.recommendations ? '\n\n권고: ' + res.recommendations : ''}`,
        raw: res
      });
      uiNotificationService?.show({
        title: 'AI 분석',
        message: `완료 (${res.duration_ms}ms)`,
        type: 'success',
        duration: 2000
      });
    } else {
      uiNotificationService?.show({
        title: 'AI 분석',
        message: '분석 실패',
        type: 'error',
        duration: 3000
      });
    }
    setLoading(null);
  }, [studyUID, aiService, selectedModel]);
  const handleCompare = (0,react.useCallback)(async () => {
    if (!studyUID || !aiService) return;
    setLoading('compare');
    const res = await aiService.compareStudies(studyUID);
    if (res?.comparison?.text || res?.text) {
      const text = res.comparison?.text || res.text;
      setResult({
        type: 'compare',
        content: text,
        raw: res
      });
      uiNotificationService?.show({
        title: '비교',
        message: `완료 (${res.comparison?.progression || ''})`,
        type: 'success',
        duration: 2000
      });
    } else {
      setResult({
        type: 'compare',
        content: res?.message || '이전 검사 없음'
      });
    }
    setLoading(null);
  }, [studyUID, aiService]);
  const handleSoap = (0,react.useCallback)(async () => {
    if (!aiService || !currentFindings) return;
    setLoading('soap');
    const res = await aiService.soapSummary(currentFindings, currentImpression);
    if (res?.summary) {
      const s = res.summary;
      const text = `S: ${s.subjective || '-'}\nO: ${s.objective || '-'}\nA: ${s.assessment || '-'}\nP: ${s.plan || '-'}${res.icd_codes?.length ? '\n\nICD-10: ' + res.icd_codes.join(', ') : ''}`;
      setResult({
        type: 'soap',
        content: text,
        raw: res
      });
    } else {
      uiNotificationService?.show({
        title: 'SOAP',
        message: res?.error || '실패',
        type: 'error',
        duration: 3000
      });
    }
    setLoading(null);
  }, [aiService, currentFindings, currentImpression]);
  const handleDdx = (0,react.useCallback)(async () => {
    if (!aiService || !currentFindings) return;
    setLoading('ddx');
    const res = await aiService.differentialDiagnosis(currentFindings, currentImpression);
    if (res?.differential_diagnosis?.length) {
      const text = res.differential_diagnosis.map((d, i) => `${i + 1}. ${d.condition || d.name || d.diagnosis} (${d.icd_code || d.icd10 || ''}) — ${d.probability || d.confidence || ''}`).join('\n');
      setResult({
        type: 'ddx',
        content: text,
        raw: res
      });
    } else {
      uiNotificationService?.show({
        title: '감별진단',
        message: res?.error || '결과 없음',
        type: 'error',
        duration: 3000
      });
    }
    setLoading(null);
  }, [aiService, currentFindings, currentImpression]);
  const [applying, setApplying] = (0,react.useState)(false);
  const handleApplyToReport = (0,react.useCallback)(async () => {
    if (!result?.raw || !aiService || applying) return;
    setApplying(true);
    const raw = result.raw;
    const data = {};
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
    console.log('[AiPanel] applyToReport', {
      studyUID,
      data: Object.keys(data)
    });
    await aiService.applyToReport(data, studyUID || undefined);
    uiNotificationService?.show({
      title: 'AI 결과',
      message: studyUID ? '판독 리포트에 적용됨' : '뷰어에만 적용됨 (Study UID 없음)',
      type: studyUID ? 'success' : 'warning',
      duration: 3000
    });
    setApplying(false);
  }, [result, aiService, studyUID, currentFindings, currentImpression, applying]);
  const handleSaveSR = (0,react.useCallback)(async () => {
    if (!result?.raw || !studyUID || !aiService || applying) return;
    setApplying(true);
    const raw = result.raw;
    const findings = raw.findings || result.content || '';
    const impression = raw.impression || '';
    const res = await aiService.saveAsSR(studyUID, findings, impression);
    if (res) {
      uiNotificationService?.show({
        title: 'DICOM SR',
        message: 'SR 저장 완료',
        type: 'success',
        duration: 2000
      });
    } else {
      uiNotificationService?.show({
        title: 'DICOM SR',
        message: 'SR 저장 실패',
        type: 'error',
        duration: 3000
      });
    }
    setApplying(false);
  }, [result, studyUID, aiService, applying]);
  const handleCopy = (0,react.useCallback)(() => {
    if (result?.content) {
      navigator.clipboard.writeText(result.content).catch(() => {});
      uiNotificationService?.show({
        title: '복사',
        message: '클립보드에 복사됨',
        type: 'info',
        duration: 1500
      });
    }
  }, [result]);

  // Pipeline (hooks must be before any conditional return)
  const [prodPipeline, setProdPipeline] = (0,react.useState)(null);
  const [pipelineResult, setPipelineResult] = (0,react.useState)(null);
  (0,react.useEffect)(() => {
    if (!aiService?.getProductionPipeline) return;
    aiService.getProductionPipeline().then(p => {
      if (p?.pipeline) setProdPipeline(p.pipeline);
    });
  }, [aiService]);

  // --- No study ---
  if (!studyUID) {
    return /*#__PURE__*/react.createElement("div", {
      className: "flex h-full items-center justify-center p-4 text-sm text-gray-500"
    }, "Study\uB97C \uC120\uD0DD\uD558\uC138\uC694");
  }
  const handlePipeline = (0,react.useCallback)(async () => {
    if (!studyUID || !aiService || !prodPipeline) return;
    setLoading('pipeline');
    const res = await aiService.runPipeline(prodPipeline, studyUID);
    if (res?.result) {
      // Parse structured sections from pipeline result text
      const parsed = parsePipelineSections(res.result);
      setResult({
        type: 'pipeline',
        content: res.result,
        raw: {
          ...parsed,
          duration_ms: res.total_duration_ms
        }
      });
      uiNotificationService?.show({
        title: `🔗 ${prodPipeline}`,
        message: `완료 (${((res.total_duration_ms || 0) / 1000).toFixed(1)}초)`,
        type: 'success',
        duration: 3000
      });
    } else {
      uiNotificationService?.show({
        title: '파이프라인',
        message: '실행 실패',
        type: 'error',
        duration: 3000
      });
    }
    setLoading(null);
  }, [studyUID, aiService, prodPipeline]);
  const needsFindings = !currentFindings;
  return /*#__PURE__*/react.createElement("div", {
    className: "flex h-full flex-col"
  }, /*#__PURE__*/react.createElement("div", {
    className: "flex items-center justify-between border-b border-[#333] px-3 py-2"
  }, /*#__PURE__*/react.createElement("span", {
    className: "text-sm font-semibold text-gray-200"
  }, "AI \uBD84\uC11D"), /*#__PURE__*/react.createElement(ServerStatus, {
    aiService: aiService
  })), /*#__PURE__*/react.createElement("div", {
    className: "flex-1 overflow-y-auto p-3 space-y-2"
  }, storedJob && Array.isArray(storedJob?.results?.findings) && storedJob.results.findings.length > 0 && /*#__PURE__*/react.createElement("div", {
    className: "rounded border border-blue-700/40 bg-blue-950/30 p-2.5"
  }, /*#__PURE__*/react.createElement("div", {
    className: "mb-1.5 flex items-center justify-between"
  }, /*#__PURE__*/react.createElement("span", {
    className: "text-xs font-semibold text-blue-300"
  }, "\uD83E\uDD16 \uC800\uC7A5\uB41C AI \uD310\uB3C5"), /*#__PURE__*/react.createElement("span", {
    className: "rounded bg-blue-700/40 px-1.5 py-0.5 text-[10px] text-blue-200"
  }, storedJob.result_dicom_uids?.sr_orthanc_id ? '표준 SR' : '결과', " \xB7 ", storedJob.model_name || 'AI')), /*#__PURE__*/react.createElement("div", {
    className: "space-y-1"
  }, storedJob.results.findings.map((f, i) => /*#__PURE__*/react.createElement("div", {
    key: i,
    className: "text-xs text-gray-300"
  }, /*#__PURE__*/react.createElement("span", {
    className: f.severity === 'critical' ? 'text-red-400' : f.severity === 'warning' ? 'text-yellow-400' : 'text-gray-300'
  }, "\u2022"), ' ', f.description || f.type, typeof f.confidence === 'number' && /*#__PURE__*/react.createElement("span", {
    className: "ml-1 text-blue-400"
  }, "(", Math.round(f.confidence * 100), "%)")))), storedJob.is_critical && /*#__PURE__*/react.createElement("div", {
    className: "mt-1.5 rounded bg-red-900/40 px-1.5 py-0.5 text-[10px] font-semibold text-red-300"
  }, "\u26A0 \uAE34\uAE09 \uC18C\uACAC \uAC10\uC9C0"), /*#__PURE__*/react.createElement("div", {
    className: "mt-1 text-[10px] text-gray-500"
  }, storedJob.completed_at ? new Date(storedJob.completed_at).toLocaleString('ko-KR') : '', storedJob.inference_time_ms ? ` · ${storedJob.inference_time_ms}ms` : '')), models.length > 0 && /*#__PURE__*/react.createElement("div", {
    className: "mb-1"
  }, /*#__PURE__*/react.createElement("label", {
    className: "mb-0.5 block text-[10px] font-medium text-gray-400"
  }, "AI \uBAA8\uB378"), /*#__PURE__*/react.createElement("select", {
    value: selectedModel,
    onChange: e => setSelectedModel(e.target.value),
    className: "w-full rounded border border-gray-600 bg-gray-800 px-2 py-1 text-xs text-gray-200 focus:border-blue-500 focus:outline-none",
    title: "\uC601\uC0C1 \uBD84\uC11D\uC5D0 \uC0AC\uC6A9\uD560 AI \uBAA8\uB378\uC744 \uC120\uD0DD\uD569\uB2C8\uB2E4"
  }, /*#__PURE__*/react.createElement("option", {
    value: ""
  }, "\uAE30\uBCF8 (MedGemma)"), models.map(m => /*#__PURE__*/react.createElement("option", {
    key: m.id || m.name,
    value: m.name
  }, m.name, m.clinical_use === 'research' ? ' · 연구용' : '', m.modalities ? ` · ${m.modalities}` : '')))), /*#__PURE__*/react.createElement(AiActionButton, {
    label: "AI \uC601\uC0C1 \uBD84\uC11D",
    description: "Study \uC601\uC0C1\uC744 AI\uB85C \uBD84\uC11D\uD558\uC5EC \uD310\uB3C5 \uCD08\uC548\uC744 \uC0DD\uC131\uD569\uB2C8\uB2E4",
    loading: loading === 'analyze',
    variant: "primary",
    onClick: handleAnalyze
  }), /*#__PURE__*/react.createElement(AiActionButton, {
    label: "\uC774\uC804 \uAC80\uC0AC \uBE44\uAD50",
    description: "\uB3D9\uC77C \uD658\uC790\uC758 \uC774\uC804 \uAC80\uC0AC\uC640 \uBCC0\uD654\uB97C \uBE44\uAD50\uD569\uB2C8\uB2E4",
    loading: loading === 'compare',
    onClick: handleCompare
  }), /*#__PURE__*/react.createElement(AiActionButton, {
    label: "SOAP \uC694\uC57D",
    description: "\uC18C\uACAC\uC744 SOAP \uD615\uC2DD\uC73C\uB85C \uC815\uB9AC\uD569\uB2C8\uB2E4",
    loading: loading === 'soap',
    disabled: needsFindings,
    disabledReason: "\uC18C\uACAC\uC744 \uBA3C\uC800 \uC785\uB825\uD558\uC138\uC694 (\uD310\uB3C5 \uD328\uB110)",
    onClick: handleSoap
  }), /*#__PURE__*/react.createElement(AiActionButton, {
    label: "\uAC10\uBCC4\uC9C4\uB2E8",
    description: "\uAC00\uB2A5\uD55C \uC9C4\uB2E8\uBA85\uACFC \uD655\uB960\uC744 \uC81C\uC548\uD569\uB2C8\uB2E4",
    loading: loading === 'ddx',
    disabled: needsFindings,
    disabledReason: "\uC18C\uACAC\uC744 \uBA3C\uC800 \uC785\uB825\uD558\uC138\uC694 (\uD310\uB3C5 \uD328\uB110)",
    onClick: handleDdx
  }), prodPipeline && /*#__PURE__*/react.createElement(react.Fragment, null, /*#__PURE__*/react.createElement("div", {
    className: "border-t border-[#333] my-2 pt-2"
  }, /*#__PURE__*/react.createElement("span", {
    className: "text-[10px] text-gray-500 uppercase tracking-wider"
  }, "\uD30C\uC774\uD504\uB77C\uC778")), /*#__PURE__*/react.createElement(AiActionButton, {
    label: `🔗 ${prodPipeline}`,
    description: "\uB2E4\uC911 \uBAA8\uB378 \uD30C\uC774\uD504\uB77C\uC778\uC73C\uB85C \uC885\uD569 \uBD84\uC11D\uD569\uB2C8\uB2E4",
    loading: loading === 'pipeline',
    variant: "primary",
    onClick: handlePipeline
  })), result && /*#__PURE__*/react.createElement(AiResultCard, {
    title: result.type === 'analyze' ? 'AI 분석 결과' : result.type === 'compare' ? '이전 검사 비교' : result.type === 'soap' ? 'SOAP 요약' : result.type === 'ddx' ? '감별진단' : result.type === 'pipeline' ? `🔗 ${prodPipeline || '파이프라인'}` : '결과',
    content: result.content,
    duration_ms: result.raw?.duration_ms,
    disabled: applying,
    onApply: result.raw ? handleApplyToReport : undefined,
    onSaveSR: (result.type === 'analyze' || result.type === 'pipeline') && result.raw ? handleSaveSR : undefined,
    onCopy: handleCopy
  })));
}
/* harmony default export */ const panels_AiPanel = (AiPanel);

/***/ })

}]);