'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import ConfirmDialog from '@/components/ConfirmDialog';

type AIModel = {
  id: string;
  name: string;
  version: string;
  description: string | null;
  model_type: string;
  clinical_use: string;
  manufacturer: string | null;
  modalities: string | null;
  body_parts: string | null;
  certification: string | null;
  is_active: boolean;
  total_jobs: number;
  completed: number;
  failed: number;
  avg_inference_ms: number;
  critical_findings: number;
};

type AIData = {
  total_models: number;
  active_models: number;
  total_jobs: number;
  jobs_by_status: Record<string, number>;
  models: AIModel[];
};

type ServerStatus = {
  server_url: string;
  healthy: boolean;
  ollama_running?: boolean;
  checks?: Record<string, any>;
  error?: string;
};

const typeLabel: Record<string, string> = {
  onnx: 'ONNX',
  external_api: 'Ollama/API',
  docker: 'Docker',
  triton: 'Triton',
};

const modalityColors: Record<string, string> = {
  CR: 'bg-blue-100 text-blue-700',
  DX: 'bg-blue-100 text-blue-700',
  CT: 'bg-purple-100 text-purple-700',
  MR: 'bg-green-100 text-green-700',
  US: 'bg-yellow-100 text-yellow-700',
};

export default function AIPage() {
  const [data, setData] = useState<AIData | null>(null);
  const [server, setServer] = useState<ServerStatus | null>(null);
  const [selected, setSelected] = useState<AIModel | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ status: string; model?: string; duration?: number; message?: string } | null>(null);
  const [testing, setTesting] = useState(false);

  const loadData = async () => {
    setLoading(true);
    setError('');
    try {
      // Try /api/v1/ai/models first, fall back to /api/v1/ai/dashboard
      let modelsData: AIData;
      try {
        modelsData = await apiFetch<AIData>('/api/v1/ai/models?active_only=false');
      } catch {
        modelsData = await apiFetch<AIData>('/api/v1/ai/dashboard');
      }
      // Normalize model fields (API may return status instead of is_active)
      if (modelsData.models) {
        modelsData.models = modelsData.models.map(m => ({
          ...m,
          is_active: m.is_active ?? (m as any).status?.includes?.('ACTIVE') ?? true,
          model_type: (m.model_type || '').replace('ModelType.', '').toLowerCase(),
          clinical_use: m.clinical_use || ((m as any).status?.includes?.('ACTIVE') ? 'research' : 'research'),
          total_jobs: m.total_jobs || 0,
          completed: m.completed || 0,
          failed: m.failed || 0,
          avg_inference_ms: m.avg_inference_ms || 0,
          critical_findings: m.critical_findings || 0,
        }));
        modelsData.total_models = modelsData.total_models || (modelsData as any).count || modelsData.models.length;
        modelsData.active_models = modelsData.active_models || modelsData.models.filter(m => m.is_active).length;
      }
      setData(modelsData);
    } catch (e: any) {
      setError(e.message || 'AI 모델 데이터를 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
    apiFetch<ServerStatus>('/api/v1/ai/server-status').then(setServer).catch(() => {});
  };

  useEffect(() => {
    loadData();
  }, []);

  const showMsg = (text: string) => {
    setMsg(text);
    setTimeout(() => setMsg(''), 3000);
  };

  const handleToggleActive = async (model: AIModel) => {
    setTogglingId(model.id);
    try {
      await apiFetch(`/api/v1/ai/models/${model.id}/toggle`, { method: 'PATCH' });
      const newState = !model.is_active;
      showMsg(`${model.name} 모델이 ${newState ? '활성화' : '비활성화'}되었습니다. ${newState ? '추론 대상에 포함됩니다.' : '추론 대상에서 제외됩니다.'}`);
      await loadData();
    } catch (e: any) {
      showMsg(`모델 상태 변경 실패: ${(e as Error).message || '알 수 없는 오류'}`);
    } finally {
      setTogglingId(null);
    }
  };

  const handleDelete = async (model: AIModel) => {
    setDeletingId(model.id);
    setConfirmDeleteId(null);
    try {
      await apiFetch(`/api/v1/ai/models/${model.id}`, { method: 'DELETE' });
      showMsg(`${model.name} 모델이 삭제되었습니다.`);
      if (selected?.id === model.id) setSelected(null);
      await loadData();
    } catch (e: any) {
      showMsg(`모델 삭제는 현재 지원되지 않습니다. (GPU 서버 관리자에게 문의)`);
    } finally {
      setDeletingId(null);
    }
  };

  if (loading && !data) return (
    <div className="space-y-4">
      <div className="h-8 bg-gray-200 rounded w-48 animate-pulse" />
      <div className="grid grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => <div key={i} className="h-24 bg-gray-200 rounded-lg animate-pulse" />)}
      </div>
      <div className="h-64 bg-gray-200 rounded-lg animate-pulse" />
    </div>
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">AI 모델 관리</h1>
        <Link href="/ai/orchestration" className="bg-purple-600 text-white px-4 py-2 rounded text-sm font-semibold hover:bg-purple-700">
          파이프라인 관리 →
        </Link>
      </div>

      {msg && (
        <div className="mb-4 p-3 bg-blue-50 text-blue-800 rounded text-sm">{msg}</div>
      )}

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={loadData} className="ml-4 px-3 py-1 bg-red-100 hover:bg-red-200 rounded text-xs font-medium">
            재시도
          </button>
        </div>
      )}

      {/* Server Status + API Key + Test */}
      {server && (
        <div className={`mb-6 rounded-lg border ${server.healthy ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'}`}>
          <div className="flex items-center justify-between p-4">
            <div className="flex items-center gap-2">
              <span className={`w-3 h-3 rounded-full ${server.healthy ? 'bg-green-500' : 'bg-red-500'}`} />
              <span className="font-semibold text-sm">GPU AI Server</span>
              <span className="text-xs text-gray-500">{server.server_url}</span>
            </div>
            <span className={`text-xs font-medium ${server.healthy ? 'text-green-700' : 'text-red-700'}`}>
              {server.healthy ? 'Ollama Running' : server.error || 'Offline'}
            </span>
          </div>
          <div className="px-4 pb-4 flex items-center gap-3 flex-wrap">
            {/* API 키 평문 노출 제거(번들에 자격 일부가 박히던 보안 스멜) — 상태는 server-status로 판단 */}
            <button
              onClick={async () => {
                setTesting(true); setTestResult(null);
                try {
                  const res = await apiFetch<any>('/api/v1/ai/server-status');
                  if (res.healthy) {
                    setTestResult({ status: 'ok', message: 'AI 서버 연결 정상' });
                  } else {
                    setTestResult({ status: 'fail', message: res.error || 'AI 서버 응답 없음' });
                  }
                } catch (e: any) {
                  setTestResult({ status: 'fail', message: e.message });
                } finally { setTesting(false); }
              }}
              disabled={testing}
              className="px-3 py-1.5 bg-blue-600 text-white rounded text-xs font-medium hover:bg-blue-700 disabled:opacity-50"
            >
              {testing ? '테스트 중...' : '연동 테스트'}
            </button>
            {testResult && (
              <span className={`text-xs font-medium ${testResult.status === 'ok' ? 'text-green-600' : 'text-red-600'}`}>
                {testResult.status === 'ok' ? 'OK' : 'FAIL'} {testResult.message}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Stats Cards */}
      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
          <div className="bg-white border rounded-lg p-4 text-center">
            <p className="text-sm text-gray-500">등록 모델</p>
            <p className="text-3xl font-bold">{data.total_models || (data as any).count || (data.models || []).length}</p>
            <p className="text-xs text-gray-400">활성: {data.active_models || (data.models || []).filter(m => m.is_active).length}</p>
          </div>
          <div className="bg-white border rounded-lg p-4 text-center">
            <p className="text-sm text-gray-500">전체 추론</p>
            <p className="text-3xl font-bold">{data.total_jobs || (data.models || []).reduce((s, m) => s + (m.total_jobs || 0), 0)}</p>
          </div>
          <div className="bg-white border rounded-lg p-4 text-center">
            <p className="text-sm text-gray-500">완료</p>
            <p className="text-3xl font-bold text-green-600">{(data.jobs_by_status || {})['completed'] || (data.models || []).reduce((s, m) => s + (m.completed || 0), 0)}</p>
          </div>
          <div className="bg-white border rounded-lg p-4 text-center">
            <p className="text-sm text-gray-500">긴급 소견</p>
            <p className="text-3xl font-bold text-red-600">
              {(data.models || []).reduce((s, m) => s + (m.critical_findings || 0), 0)}
            </p>
          </div>
        </div>
      )}

      {/* Model Table */}
      {data && (
        <div className="bg-white rounded-lg border shadow-sm mb-6">
          <div className="p-4 border-b flex items-center justify-between">
            <h3 className="font-semibold">AI 모델 현황</h3>
            <span className="text-xs text-gray-400">{data.models?.length || 0}개 모델</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-500">
                <tr>
                  <th className="px-3 py-2 text-left">모델명</th>
                  <th className="px-3 py-2 text-left">설명</th>
                  <th className="px-3 py-2 text-left">모달리티</th>
                  <th className="px-3 py-2 text-center">타입</th>
                  <th className="px-3 py-2 text-center">용도</th>
                  <th className="px-3 py-2 text-center" title="ON: 추론 대상 포함 / OFF: 추론 대상 제외">사용</th>
                  <th className="px-3 py-2 text-center">추론</th>
                </tr>
              </thead>
              <tbody>
                {(data.models || []).length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-gray-400">
                      등록된 AI 모델이 없습니다
                    </td>
                  </tr>
                ) : (() => {
                  const medicalNames = ['medgemma','medllama','meditron','med42','werub-medical','werubmedv2','medichat','openbiollm','biomistral','llava-med','chest-xray','minicpm-v'];
                  const isMedical = (name: string) => medicalNames.some(k => name.toLowerCase().includes(k));
                  const medical = (data.models || []).filter(m => isMedical(m.name));
                  const general = (data.models || []).filter(m => !isMedical(m.name));
                  const groupHeader = (label: string, count: number) => (
                    <tr key={`header-${label}`} className="bg-slate-100 dark:bg-slate-700">
                      <td colSpan={7} className="px-3 py-1.5 text-xs font-bold text-gray-600 dark:text-gray-300 uppercase tracking-wider">
                        {label} <span className="font-normal text-gray-400">({count})</span>
                      </td>
                    </tr>
                  );
                  return [...(medical.length ? [groupHeader('🏥 의료 모델', medical.length), ...medical.flatMap(renderRow)] : []),
                          ...(general.length ? [groupHeader('⚙️ 범용 모델', general.length), ...general.flatMap(renderRow)] : [])].filter(Boolean);
                  function renderRow(m: AIModel) { return [
                    <tr
                      key={m.id || m.name}
                      className={`border-t cursor-pointer transition-opacity ${selected?.id === m.id ? 'bg-blue-50' : m.is_active ? 'hover:bg-blue-50' : 'opacity-50 bg-gray-50 hover:bg-gray-100'}`}
                      onClick={() => setSelected(selected?.id === m.id ? null : m)}
                    >
                      <td className="px-3 py-2">
                        <span className="font-semibold">{m.name}</span>
                        <span className="text-gray-400 text-xs ml-1">v{m.version}</span>
                      </td>
                      <td className="px-3 py-2 text-gray-600 text-xs max-w-[180px] truncate">
                        {m.description || '-'}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap gap-0.5">
                          {(m.modalities || '').split(',').filter(Boolean).map(mod => (
                            <span key={mod} className={`px-1 py-0 rounded text-[10px] font-medium ${modalityColors[mod.trim()] || 'bg-gray-100 text-gray-600'}`}>
                              {mod.trim()}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-center">
                        <span className="text-[10px] bg-gray-100 px-1.5 py-0.5 rounded">
                          {typeLabel[m.model_type] || m.model_type}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-center">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${m.clinical_use === 'clinical' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'}`}>
                          {m.clinical_use === 'clinical' ? '임상' : '연구'}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-center" onClick={e => e.stopPropagation()}>
                        <button
                          onClick={() => handleToggleActive(m)}
                          disabled={togglingId === (m.id || m.name)}
                          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none disabled:opacity-50 ${m.is_active ? 'bg-green-500' : 'bg-gray-300'}`}
                          title={m.is_active ? 'OFF: 추론 대상에서 제외' : 'ON: 추론 대상에 포함'}
                        >
                          <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${m.is_active ? 'translate-x-4' : 'translate-x-0.5'}`} />
                        </button>
                      </td>
                      <td className="px-3 py-2 text-center">
                        <span className="text-green-600 font-medium">{m.completed}</span>
                        <span className="text-gray-400">/{m.total_jobs}</span>
                        {m.failed > 0 && <span className="text-red-500 text-xs ml-1">({m.failed}실패)</span>}
                      </td>
                    </tr>,
                    selected?.id === m.id && (
                      <tr key={`detail-${m.id}`} className="border-t bg-blue-50/50 dark:bg-blue-900/10">
                        <td colSpan={7} className="px-4 py-4">
                          <div className="flex items-center justify-between mb-3">
                            <span className="text-sm font-bold">{m.name} <span className="text-gray-400 font-normal">v{m.version}</span></span>
                            <div className="flex items-center gap-2">
                              <button onClick={() => handleToggleActive(m)} disabled={togglingId === (m.id || m.name)}
                                className={`px-2 py-1 rounded text-xs font-medium ${m.is_active ? 'bg-orange-100 text-orange-700' : 'bg-green-100 text-green-700'} disabled:opacity-50`}>
                                {m.is_active ? '비활성화' : '활성화'}
                              </button>
                              <button onClick={() => setSelected(null)} className="text-gray-400 hover:text-gray-600 text-xs">닫기</button>
                            </div>
                          </div>
                          <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-3 text-xs">
                            <div><span className="text-gray-500 block">설명</span><p className="font-medium">{m.description || '-'}</p></div>
                            <div><span className="text-gray-500 block">제조사</span><p className="font-medium">{m.manufacturer || '-'}</p></div>
                            <div><span className="text-gray-500 block">타입</span><p className="font-medium">{typeLabel[m.model_type] || m.model_type}</p></div>
                            <div><span className="text-gray-500 block">검사 부위</span><p className="font-medium">{m.body_parts || '전체'}</p></div>
                            <div><span className="text-gray-500 block">추론</span><p className="font-medium">{m.total_jobs}회 (완료 {m.completed})</p></div>
                            <div><span className="text-gray-500 block">평균 시간</span><p className="font-medium">{m.avg_inference_ms ? `${m.avg_inference_ms}ms` : '측정 전'}</p></div>
                          </div>
                          {m.clinical_use !== 'clinical' && (
                            <div className="mt-2 bg-yellow-50 border border-yellow-200 rounded px-3 py-1.5 text-[11px] text-yellow-800">
                              연구 목적 전용 · 임상 판독 근거 불가 · 최종 판단은 의료진 책임
                            </div>
                          )}
                        </td>
                      </tr>
                    ),
                  ] as React.ReactNode[]; }
                })()}
              </tbody>
            </table>
          </div>
        </div>
      )}


      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        open={!!confirmDeleteId}
        title="모델 삭제 확인"
        description="정말로 이 AI 모델을 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다."
        confirmLabel="삭제"
        onConfirm={() => {
          const model = data?.models.find(m => (m.id || m.name) === confirmDeleteId);
          if (model) handleDelete(model);
        }}
        onCancel={() => setConfirmDeleteId(null)}
      />
    </div>
  );
}
