'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import Breadcrumb from '@/components/ui/Breadcrumb';
import ConfirmDialog from '@/components/ConfirmDialog';

type Stage = { model: string; role: string; system?: string; on_fail?: string; retry?: number; fallback_model?: string };
type Pipeline = { name: string; stages: Stage[]; description?: string; is_builtin?: boolean; created_at?: string };
type RunResult = { run_id?: string; result?: string; stages?: any[]; total_duration_ms?: number; error?: string; detail?: string };

export default function OrchestrationPage() {
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [selected, setSelected] = useState<Pipeline | null>(null);
  const [production, setProduction] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState('');

  // Run/Test/Compare state
  const [runPipeline, setRunPipeline] = useState('');
  const [runInput, setRunInput] = useState('');
  const [runStudyUid, setRunStudyUid] = useState('');
  const [runDebug, setRunDebug] = useState(true);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<RunResult | null>(null);

  // Compare
  const [compareMode, setCompareMode] = useState(false);
  const [comparePipelines, setComparePipelines] = useState<string[]>([]);
  const [compareResult, setCompareResult] = useState<any>(null);

  // Test
  const [testMode, setTestMode] = useState('validate');
  const [testResult, setTestResult] = useState<any>(null);

  // Create
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newStages, setNewStages] = useState<Stage[]>([{ model: '', role: '' }]);

  // Study picker
  type StudyItem = { study_instance_uid: string; patient_name: string; patient_id: string; modality: string; study_description: string; study_date: string };
  const [recentStudies, setRecentStudies] = useState<StudyItem[]>([]);
  const [studiesLoaded, setStudiesLoaded] = useState(false);

  // Delete
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const [pData, prodData] = await Promise.all([
        apiFetch<{ pipelines: Pipeline[] }>('/api/v1/ai/orchestration/pipelines'),
        apiFetch<Record<string, any>>('/api/v1/ai/orchestration/production'),
      ]);
      const hiddenPipes = ['coding', 'legal', 'writing', 'blog-seo'];
      setPipelines((pData.pipelines || []).filter(p =>
        !hiddenPipes.includes(p.name) && !p.name.includes('@v')
      ));
      setProduction(prodData || {});
    } catch (e: any) {
      setMsg(`로드 실패: ${e.message}`);
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const RENDERABLE = ['CR', 'DX', 'CT', 'MR', 'US', 'MG', 'XA', 'RF', 'PT', 'NM'];
  const isRenderable = (mod: string) => RENDERABLE.some(r => (mod || '').toUpperCase().includes(r));

  // Pipeline → modality/keyword matching for smart recommendations
  const PIPELINE_HINTS: Record<string, { modalities: string[]; keywords: string[] }> = {
    'chest-xray': { modalities: ['CR', 'DX'], keywords: ['chest', 'thorax', 'lung', '흉부', '폐'] },
    'ct-abdomen': { modalities: ['CT'], keywords: ['abdomen', 'liver', 'pancreas', '복부', '간', '췌장'] },
    'emergency-triage': { modalities: ['CR', 'DX', 'CT'], keywords: ['emergency', 'trauma', 'stroke', '응급'] },
    'consensus': { modalities: ['CR', 'DX', 'CT', 'MR'], keywords: [] },
    'medical': { modalities: ['CR', 'DX', 'CT', 'MR', 'US'], keywords: [] },
  };

  const scoreStudy = (s: StudyItem, pipe: string): number => {
    const hints = PIPELINE_HINTS[pipe];
    if (!hints) return isRenderable(s.modality) ? 1 : 0;
    let score = 0;
    const mod = (s.modality || '').toUpperCase();
    if (hints.modalities.some(m => mod.includes(m))) score += 10;
    const desc = ((s.study_description || '') + ' ' + (s.patient_name || '')).toLowerCase();
    if (hints.keywords.some(k => desc.includes(k))) score += 5;
    if (isRenderable(s.modality)) score += 1;
    return score;
  };

  const loadStudies = async () => {
    if (studiesLoaded) return;
    try {
      const data = await apiFetch<{ queue: StudyItem[] }>('/api/v1/dashboard/reading-queue');
      setRecentStudies((data.queue || []).slice(0, 50));
      setStudiesLoaded(true);
    } catch { setRecentStudies([]); }
  };

  const handleRun = async () => {
    if (!runPipeline) return;
    setRunning(true); setRunResult(null);
    try {
      const body: any = { pipeline: runPipeline, debug: runDebug };
      if (runInput) body.input = runInput;
      if (runStudyUid) body.study_instance_uid = runStudyUid;
      const r = await apiFetch<RunResult>('/api/v1/ai/orchestration/run', {
        method: 'POST', body: JSON.stringify(body),
      });
      setRunResult(r);
    } catch (e: any) {
      setRunResult({ error: e.message });
    } finally { setRunning(false); }
  };

  const handleTest = async () => {
    if (!runPipeline) return;
    setRunning(true); setTestResult(null);
    try {
      const body: any = { pipeline: runPipeline, mode: testMode };
      if (runInput) body.input = runInput;
      const r = await apiFetch('/api/v1/ai/orchestration/test', {
        method: 'POST', body: JSON.stringify(body),
      });
      setTestResult(r);
    } catch (e: any) {
      setTestResult({ error: e.message });
    } finally { setRunning(false); }
  };

  const handleCompare = async () => {
    if (comparePipelines.length < 2) { setMsg('2개 이상 파이프라인을 선택하세요'); return; }
    setRunning(true); setCompareResult(null);
    try {
      const body: any = { pipelines: comparePipelines };
      if (runInput) body.input = runInput;
      if (runStudyUid) body.study_instance_uid = runStudyUid;
      const r = await apiFetch('/api/v1/ai/orchestration/compare', {
        method: 'POST', body: JSON.stringify(body),
      });
      setCompareResult(r);
    } catch (e: any) {
      setCompareResult({ error: e.message });
    } finally { setRunning(false); }
  };

  const handleCreate = async () => {
    if (!newName || newStages.some(s => !s.model || !s.role)) { setMsg('모든 필드를 입력하세요'); return; }
    try {
      await apiFetch('/api/v1/ai/orchestration/pipelines', {
        method: 'POST',
        body: JSON.stringify({ name: newName, stages: newStages }),
      });
      setMsg(`${newName} 파이프라인이 생성되었습니다`);
      setShowCreate(false); setNewName(''); setNewStages([{ model: '', role: '' }]);
      await load();
    } catch (e: any) {
      const msg = e.message || '';
      if (msg.includes('403')) setMsg(`생성 실패: Admin 권한이 필요합니다.`);
      else setMsg(`생성 실패: ${msg}`);
    }
  };

  const handleDelete = async (name: string) => {
    try {
      await apiFetch(`/api/v1/ai/orchestration/pipelines/${name}`, { method: 'DELETE' });
      setMsg(`${name} 삭제됨`); setDeleteTarget(null); setSelected(null);
      await load();
    } catch (e: any) {
      const msg = e.message || '';
      if (msg.includes('403')) setMsg(`삭제 실패: Admin 권한이 필요합니다.`);
      else setMsg(`삭제 실패: ${msg}`);
    }
  };

  const handlePromote = async (name: string, target: string) => {
    try {
      await apiFetch(`/api/v1/ai/orchestration/pipelines/${name}/promote`, {
        method: 'POST', body: JSON.stringify({ target }),
      });
      setMsg(`${name} → ${target} 프로덕션 승격`);
      await load();
    } catch (e: any) {
      const msg = e.message || '';
      if (msg.includes('403')) setMsg(`승격 실패: 권한이 없습니다. Admin 또는 영상의학과 전문의만 승격할 수 있습니다.`);
      else if (msg.includes('401')) setMsg(`승격 실패: 로그인이 만료되었습니다. 다시 로그인하세요.`);
      else if (msg.includes('404')) setMsg(`승격 실패: 파이프라인 "${name}"을 찾을 수 없습니다.`);
      else setMsg(`승격 실패: ${msg}`);
    }
  };

  const getProductionTarget = (name: string) => {
    for (const [target, val] of Object.entries(production)) {
      if (val?.pipeline === name) return target;
    }
    return null;
  };

  return (
    <div>
      <Breadcrumb items={[{ label: 'PACS', href: '/' }, { label: 'AI', href: '/ai' }, { label: '파이프라인' }]} />
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">AI 파이프라인 관리</h1>
        <button onClick={() => setShowCreate(true)} className="bg-primary text-white px-4 py-2 rounded text-sm font-semibold hover:bg-primary-dark">
          + 새 파이프라인
        </button>
      </div>

      {msg && (
        <div className="bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 px-4 py-2 rounded mb-4 text-sm">
          {msg} <button onClick={() => setMsg('')} className="ml-2">&times;</button>
        </div>
      )}

      {/* Pipeline List */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border overflow-hidden mb-6">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 dark:bg-gray-700 text-xs text-gray-500 uppercase">
            <tr>
              <th className="px-4 py-2 text-left">이름</th>
              <th className="px-4 py-2 text-left">단계</th>
              <th className="px-4 py-2 text-center">모델</th>
              <th className="px-4 py-2 text-center">타입</th>
              <th className="px-4 py-2 text-center">운영</th>
              <th className="px-4 py-2 text-center">작업</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">로딩 중...</td></tr>
            ) : pipelines.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">파이프라인이 없습니다</td></tr>
            ) : pipelines.map(p => {
              const prodTarget = getProductionTarget(p.name);
              return (
              <tr key={p.name} className={`border-t cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700 ${selected?.name === p.name ? 'bg-blue-50 dark:bg-blue-900/20' : ''}`}
                onClick={() => { setSelected(selected?.name === p.name ? null : p); setRunPipeline(p.name); }}>
                <td className="px-4 py-3">
                  <span className="font-semibold">{p.name}</span>
                  {p.description && <p className="text-xs text-gray-400 mt-0.5">{p.description}</p>}
                </td>
                <td className="px-4 py-3 text-xs text-gray-600">
                  {(p.stages || []).map((s, i) => (
                    <span key={i}>{i > 0 && ' → '}<span className="font-medium">{s.role}</span></span>
                  ))}
                </td>
                <td className="px-4 py-3 text-center">
                  <div className="flex flex-wrap gap-1 justify-center">
                    {(p.stages || []).map((s, i) => (
                      <span key={i} className="px-1.5 py-0.5 bg-gray-100 dark:bg-gray-600 rounded text-[10px]">{s.model.split(':')[0]}</span>
                    ))}
                  </div>
                </td>
                <td className="px-4 py-3 text-center">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${p.is_builtin ? 'bg-blue-100 text-blue-700' : 'bg-purple-100 text-purple-700'}`}>
                    {p.is_builtin ? 'Built-in' : 'Custom'}
                  </span>
                </td>
                <td className="px-4 py-3 text-center">
                  {prodTarget ? (
                    <span className="text-[10px] px-1.5 py-0.5 rounded font-medium bg-green-100 text-green-700">{prodTarget}</span>
                  ) : (
                    <span className="text-[10px] text-gray-400">—</span>
                  )}
                </td>
                <td className="px-4 py-3 text-center" onClick={e => e.stopPropagation()}>
                  <div className="flex gap-1 justify-center">
                    <button onClick={() => { setRunPipeline(p.name); setRunResult(null); setTestResult(null); }}
                      className="text-blue-600 hover:text-blue-800 text-xs font-semibold">실행</button>
                    {!p.is_builtin && (
                      <button onClick={() => setDeleteTarget(p.name)}
                        className="text-red-500 hover:text-red-700 text-xs font-semibold">삭제</button>
                    )}
                  </div>
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Selected Pipeline Detail */}
      {selected && (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border p-4 mb-6">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-bold">{selected.name} <span className="text-gray-400 font-normal text-sm">{selected.stages?.length}단계</span></h3>
            <div className="flex gap-2">
              <select onChange={e => e.target.value && handlePromote(selected.name, e.target.value)} defaultValue=""
                className="border rounded px-2 py-1 text-xs dark:bg-gray-700 dark:border-gray-600">
                <option value="">운영 승격...</option>
                <option value="reading">판독</option>
                <option value="emergency">응급</option>
                <option value="auto_draft">자동 초안</option>
              </select>
              <button onClick={() => setSelected(null)} className="text-gray-400 text-xs">닫기</button>
            </div>
          </div>
          <div className="flex gap-2 items-center">
            {(selected.stages || []).map((s, i) => (
              <div key={i} className="flex items-center gap-1">
                {i > 0 && <span className="text-gray-300">→</span>}
                <div className="border rounded px-3 py-2 text-xs bg-gray-50 dark:bg-gray-700">
                  <p className="font-semibold">{s.role}</p>
                  <p className="text-gray-500">{s.model}</p>
                  {s.on_fail && s.on_fail !== 'abort' && <p className="text-orange-500 text-[10px]">실패:{s.on_fail}</p>}
                  {s.fallback_model && <p className="text-blue-500 text-[10px]">대체:{s.fallback_model}</p>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Run / Test / Compare Panel */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border p-4 mb-6">
        <h3 className="font-bold mb-3">실험 실행</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
          <div>
            <label className="text-xs text-gray-500 font-semibold">파이프라인</label>
            <select value={runPipeline} onChange={e => setRunPipeline(e.target.value)}
              className="w-full border rounded px-3 py-2 text-sm mt-1 dark:bg-gray-700 dark:border-gray-600">
              <option value="">선택...</option>
              {pipelines.map(p => <option key={p.name} value={p.name}>{p.name} ({p.stages?.length}단계)</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 font-semibold">검사 선택 (선택)</label>
            <select value={runStudyUid} onChange={e => setRunStudyUid(e.target.value)} onFocus={loadStudies}
              className="w-full border rounded px-3 py-2 text-sm mt-1 dark:bg-gray-700 dark:border-gray-600">
              <option value="">텍스트 직접 입력</option>
              {recentStudies.length > 0 && (() => {
                const scored = recentStudies.map(s => ({ ...s, score: scoreStudy(s, runPipeline) }));
                const best = scored.filter(s => s.score >= 10).sort((a, b) => b.score - a.score);
                const good = scored.filter(s => s.score >= 1 && s.score < 10).sort((a, b) => b.score - a.score);
                const other = scored.filter(s => s.score < 1);
                const fmt = (s: StudyItem) => `${s.patient_name || s.patient_id} · ${s.modality} · ${s.study_description || '-'} · ${s.study_date?.replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3')}`;
                return (<>
                  {best.length > 0 && <optgroup label={`★ 추천 — ${runPipeline || 'AI'} 최적 (${best.length}건)`}>
                    {best.map(s => <option key={s.study_instance_uid} value={s.study_instance_uid}>{fmt(s)}</option>)}
                  </optgroup>}
                  {good.length > 0 && <optgroup label={`영상 검사 (${good.length}건)`}>
                    {good.map(s => <option key={s.study_instance_uid} value={s.study_instance_uid}>{fmt(s)}</option>)}
                  </optgroup>}
                  {other.length > 0 && <optgroup label={`기타 — 비영상 (${other.length}건)`}>
                    {other.map(s => <option key={s.study_instance_uid} value={s.study_instance_uid}>{fmt(s)}</option>)}
                  </optgroup>}
                </>);
              })()}
            </select>
          </div>
        </div>
        <div className="mb-3">
          <label className="text-xs text-gray-500 font-semibold">입력 텍스트</label>
          <textarea value={runInput} onChange={e => setRunInput(e.target.value)} rows={3}
            placeholder="분석할 텍스트 입력 (Study UID 지정 시 자동 추출)"
            className="w-full border rounded px-3 py-2 text-sm mt-1 dark:bg-gray-700 dark:border-gray-600" />
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1 text-sm">
            <input type="checkbox" checked={runDebug} onChange={e => setRunDebug(e.target.checked)} /> 디버그
          </label>
          <button onClick={handleRun} disabled={running || !runPipeline}
            className="bg-blue-600 text-white px-4 py-2 rounded text-sm font-semibold hover:bg-blue-700 disabled:opacity-50">
            {running ? '실행 중...' : '실행'}
          </button>
          <select value={testMode} onChange={e => setTestMode(e.target.value)}
            className="border rounded px-2 py-1.5 text-xs dark:bg-gray-700 dark:border-gray-600">
            <option value="validate">검증</option>
            <option value="dry_run">드라이런</option>
            <option value="full_test">전체 테스트</option>
          </select>
          <button onClick={handleTest} disabled={running || !runPipeline}
            className="bg-yellow-500 text-white px-4 py-2 rounded text-sm font-semibold hover:bg-yellow-600 disabled:opacity-50">
            테스트
          </button>
          <button onClick={() => { setCompareMode(!compareMode); setComparePipelines(runPipeline ? [runPipeline] : []); }}
            className={`px-4 py-2 rounded text-sm font-semibold ${compareMode ? 'bg-purple-600 text-white' : 'border text-gray-600 hover:bg-gray-50'}`}>
            A/B 비교
          </button>
        </div>

        {compareMode && (
          <div className="mt-3 p-3 bg-purple-50 dark:bg-purple-900/20 rounded">
            <p className="text-xs font-semibold text-purple-700 mb-2">비교할 파이프라인 선택 (2~3개)</p>
            <div className="flex flex-wrap gap-2">
              {pipelines.map(p => (
                <label key={p.name} className="flex items-center gap-1 text-sm">
                  <input type="checkbox" checked={comparePipelines.includes(p.name)}
                    onChange={e => {
                      if (e.target.checked) setComparePipelines([...comparePipelines, p.name].slice(0, 3));
                      else setComparePipelines(comparePipelines.filter(n => n !== p.name));
                    }} />
                  {p.name}
                </label>
              ))}
            </div>
            <button onClick={handleCompare} disabled={running || comparePipelines.length < 2}
              className="mt-2 bg-purple-600 text-white px-4 py-2 rounded text-sm font-semibold disabled:opacity-50">
              {running ? '비교 중...' : `${comparePipelines.length}개 비교 실행`}
            </button>
          </div>
        )}
      </div>

      {/* Results */}
      {(runResult || testResult || compareResult) && (() => {
        const data = runResult || testResult || compareResult;
        const hasError = data?.error;
        return (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border p-4 mb-6">
          <div className="flex justify-between items-center mb-3">
            <h3 className="font-bold">
              결과
              {data?.pipeline && <span className="text-gray-400 font-normal text-sm ml-2">{data.pipeline}</span>}
              {data?.total_duration_ms && <span className="text-blue-500 font-normal text-sm ml-2">{(data.total_duration_ms / 1000).toFixed(1)}초</span>}
            </h3>
            <button onClick={() => { setRunResult(null); setTestResult(null); setCompareResult(null); }}
              className="text-gray-400 text-xs">닫기</button>
          </div>

          {hasError ? (
            <div className="bg-red-50 dark:bg-red-900/20 rounded p-4 text-sm text-red-700 dark:text-red-300">
              {data.error} {data.detail && <p className="text-xs mt-1 opacity-70">{data.detail}</p>}
            </div>
          ) : (
            <div className="space-y-4">
              {/* Final Result */}
              {data?.result && (
                <div>
                  <p className="text-xs font-semibold text-gray-500 mb-1">종합 결과</p>
                  <div className="bg-blue-50 dark:bg-blue-900/20 rounded p-4 text-sm leading-relaxed whitespace-pre-wrap">
                    {data.result}
                  </div>
                </div>
              )}

              {/* Stages */}
              {data?.stages && data.stages.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-gray-500 mb-2">단계별 결과</p>
                  <div className="space-y-2">
                    {data.stages.map((s: any, i: number) => (
                      <details key={i} className="border rounded">
                        <summary className="px-3 py-2 bg-gray-50 dark:bg-gray-700 cursor-pointer text-sm flex items-center gap-2">
                          <span className="bg-blue-100 text-blue-700 dark:bg-blue-800 dark:text-blue-200 px-1.5 py-0.5 rounded text-[10px] font-bold">S{i+1}</span>
                          <span className="font-medium">{s.role || s.model}</span>
                          <span className="text-gray-400 text-xs">{s.model}</span>
                          {s.duration_ms && <span className="text-gray-400 text-xs ml-auto">{(s.duration_ms / 1000).toFixed(1)}초</span>}
                        </summary>
                        <div className="px-3 py-3 text-sm whitespace-pre-wrap leading-relaxed max-h-60 overflow-y-auto">
                          {s.output || s.result || s.content || JSON.stringify(s, null, 2)}
                        </div>
                      </details>
                    ))}
                  </div>
                </div>
              )}

              {/* Run ID */}
              {data?.run_id && (
                <p className="text-xs text-gray-400">Run ID: {data.run_id}</p>
              )}
            </div>
          )}
        </div>
        );
      })()}

      {/* Create Dialog */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={() => setShowCreate(false)}>
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl p-6 w-full max-w-lg max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-4">새 파이프라인 생성</h2>
            <div className="space-y-3">
              <div>
                <label className="text-xs font-semibold text-gray-600">이름</label>
                <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="my-pipeline"
                  className="w-full border rounded px-3 py-2 text-sm mt-1 dark:bg-gray-700 dark:border-gray-600" />
              </div>
              {newStages.map((s, i) => (
                <div key={i} className="border rounded p-3 bg-gray-50 dark:bg-gray-700">
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-xs font-bold">Stage {i + 1}</span>
                    {newStages.length > 1 && (
                      <button onClick={() => setNewStages(newStages.filter((_, j) => j !== i))}
                        className="text-red-500 text-xs">제거</button>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <input value={s.model} onChange={e => { const ns = [...newStages]; ns[i] = { ...s, model: e.target.value }; setNewStages(ns); }}
                      placeholder="모델명 (e.g. medgemma:4b)" className="border rounded px-2 py-1.5 text-xs dark:bg-gray-600 dark:border-gray-500" />
                    <input value={s.role} onChange={e => { const ns = [...newStages]; ns[i] = { ...s, role: e.target.value }; setNewStages(ns); }}
                      placeholder="역할 (e.g. 소견 추출)" className="border rounded px-2 py-1.5 text-xs dark:bg-gray-600 dark:border-gray-500" />
                  </div>
                </div>
              ))}
              {newStages.length < 5 && (
                <button onClick={() => setNewStages([...newStages, { model: '', role: '' }])}
                  className="text-blue-600 text-xs font-semibold">+ 단계 추가</button>
              )}
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setShowCreate(false)} className="px-4 py-2 border rounded text-sm">취소</button>
              <button onClick={handleCreate} className="px-4 py-2 bg-primary text-white rounded text-sm font-semibold">생성</button>
            </div>
          </div>
        </div>
      )}

      {/* Usage Guide */}
      <div className="bg-gray-50 dark:bg-gray-800/50 rounded-lg border p-5 mb-6">
        <h3 className="font-bold text-sm mb-3">사용 가이드</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs text-gray-600 dark:text-gray-400">
          <div>
            <p className="font-semibold text-gray-800 dark:text-gray-200 mb-1">1. 파이프라인 선택/생성</p>
            <p>목록에서 파이프라인을 클릭하면 단계별 모델 구성을 확인할 수 있습니다. <span className="text-primary font-semibold">+ 새 파이프라인</span>으로 커스텀 파이프라인을 최대 5단계까지 생성하세요.</p>
          </div>
          <div>
            <p className="font-semibold text-gray-800 dark:text-gray-200 mb-1">2. 실험 실행</p>
            <p>파이프라인을 선택 후 <span className="text-blue-600 font-semibold">실행</span>하면 다중 모델이 순차적으로 분석합니다. Study UID를 입력하면 Orthanc 영상을 자동 추출합니다. <span className="text-yellow-600 font-semibold">테스트</span>로 VRAM/모델 사전 검증도 가능합니다.</p>
          </div>
          <div>
            <p className="font-semibold text-gray-800 dark:text-gray-200 mb-1">3. A/B 비교 & 운영 승격</p>
            <p><span className="text-purple-600 font-semibold">A/B 비교</span>로 2~3개 파이프라인을 동일 입력으로 비교하세요. 최적 파이프라인은 <span className="text-green-600 font-semibold">운영 승격</span>하여 판독/응급/자동초안에 적용합니다.</p>
          </div>
        </div>
        <div className="mt-3 pt-3 border-t text-xs text-gray-500 dark:text-gray-400">
          <span className="font-semibold">Builtin 파이프라인:</span> AI 서버 기본 제공 (수정 불가, 복제 후 커스텀 생성 가능) &nbsp;|&nbsp;
          <span className="font-semibold">Custom 파이프라인:</span> 자유롭게 생성/수정/삭제, 버전 자동 관리 &nbsp;|&nbsp;
          <span className="font-semibold">에러 정책:</span> 단계별 abort(중단) / continue(계속) / skip(건너뜀) + fallback 모델 지정 가능
        </div>
      </div>

      <ConfirmDialog open={!!deleteTarget} title="파이프라인 삭제" description={`"${deleteTarget}" 파이프라인을 삭제하시겠습니까?`}
        confirmLabel="삭제" onConfirm={() => deleteTarget && handleDelete(deleteTarget)} onCancel={() => setDeleteTarget(null)} />
    </div>
  );
}
