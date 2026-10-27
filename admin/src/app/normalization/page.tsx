'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { apiFetch, getUser } from '@/lib/api';
import { StatCard } from '@/components/normalization/StatCard';
import type { BatchStatistics } from './types';

type AlgorithmConfig = {
  id: string; name: string; description: string;
  risk_level: 'safe' | 'medium' | 'risky';
  enabled: boolean; auto_apply: boolean;
  params: Record<string, any>;
};

type TriggerConfig = {
  on_receive: boolean; // auto on C-STORE
  scheduled: boolean;  // nightly cron
  schedule_time: string; // HH:MM
};

const DEFAULT_ALGORITHMS: AlgorithmConfig[] = [
  { id: 'jpeg_density', name: 'JPEG 밀도(DPI/DPM) 수정', description: 'JFIF 헤더 Xdensity/Ydensity vs DICOM Pixel Spacing 교차 검증 및 수정', risk_level: 'risky', enabled: true, auto_apply: false, params: { threshold: 0.01 } },
  { id: 'pixel_spacing', name: 'Pixel Spacing 정합성', description: 'ImagerPixelSpacing ↔ PixelSpacing 불일치 교정', risk_level: 'risky', enabled: true, auto_apply: false, params: {} },
  { id: 'charset_utf8', name: 'Character Set (UTF-8)', description: 'SpecificCharacterSet 누락/오류 → ISO_IR 192 자동 보정', risk_level: 'safe', enabled: true, auto_apply: true, params: {} },
  { id: 'window_level', name: 'Window Center/Width 정규화', description: '비표준 W/L 값을 모달리티별 표준 범위로 정규화', risk_level: 'safe', enabled: true, auto_apply: true, params: {} },
  { id: 'patient_name_kr', name: '환자명 한국어 인코딩', description: 'EUC-KR → UTF-8 인코딩 변환, 깨진 한글 복원', risk_level: 'safe', enabled: true, auto_apply: true, params: {} },
  { id: 'date_format', name: 'DA 날짜 형식', description: '비표준 날짜 → YYYYMMDD 형식 강제 변환', risk_level: 'safe', enabled: true, auto_apply: true, params: {} },
  { id: 'uid_normalize', name: 'UID 정규화', description: '비표준 UID 접두사 수정 (OID root 준수)', risk_level: 'medium', enabled: true, auto_apply: false, params: {} },
  { id: 'transfer_syntax', name: 'Transfer Syntax 변환', description: '비표준 전송 구문 → 표준 전송 구문으로 변환', risk_level: 'medium', enabled: true, auto_apply: false, params: {} },
];

const DEFAULT_TRIGGER: TriggerConfig = { on_receive: false, scheduled: false, schedule_time: '02:00' };

type StatsPageState = {
  loading: boolean; error: string | null; days: 7 | 30 | 90;
  stats: BatchStatistics | null; toast: { message: string; type: 'error' | 'success' } | null;
};

export default function NormalizationPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [tab, setTab] = useState<'dashboard' | 'settings' | 'ai-analysis'>('dashboard');
  const [state, setState] = useState<StatsPageState>({ loading: true, error: null, days: 7, stats: null, toast: null });
  const [algorithms, setAlgorithms] = useState<AlgorithmConfig[]>(DEFAULT_ALGORITHMS);
  const [trigger, setTrigger] = useState<TriggerConfig>(DEFAULT_TRIGGER);
  const [settingsDirty, setSettingsDirty] = useState(false);
  const [aiAnalyzing, setAiAnalyzing] = useState(false);
  const [aiResult, setAiResult] = useState<any>(null);
  const [analyzeStudyUID, setAnalyzeStudyUID] = useState('');
  const [searchType, setSearchType] = useState<'study_uid' | 'patient_name' | 'patient_id'>('study_uid');

  useEffect(() => {
    const u = getUser();
    if (!u || !['admin', 'technologist', 'radiologist', 'resident'].includes(u.role)) { router.replace('/'); return; }
    setUser(u);
    fetchStats(7);
    loadSettings();
  }, [router]);

  useEffect(() => {
    if (!state.toast) return;
    const id = setTimeout(() => setState(prev => ({ ...prev, toast: null })), 4000);
    return () => clearTimeout(id);
  }, [state.toast]);

  const showToast = (message: string, type: 'success' | 'error' = 'success') =>
    setState(prev => ({ ...prev, toast: { message, type } }));

  const fetchStats = async (days: 7 | 30 | 90) => {
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      const data = await apiFetch<{ statistics: BatchStatistics }>(`/api/v1/statistics?days=${days}`);
      setState(prev => ({ ...prev, loading: false, stats: data.statistics, days }));
    } catch (err: any) {
      setState(prev => ({ ...prev, loading: false, error: err.message, toast: { message: err.message, type: 'error' } }));
    }
  };

  const loadSettings = async () => {
    try {
      const data = await apiFetch<{ algorithms: AlgorithmConfig[]; trigger: TriggerConfig }>('/api/v1/normalization/settings');
      if (data.algorithms?.length) setAlgorithms(data.algorithms);
      if (data.trigger) setTrigger(data.trigger);
    } catch {
      // Use defaults if API not ready
    }
  };

  const saveSettings = async () => {
    try {
      await apiFetch('/api/v1/normalization/settings', {
        method: 'PUT', body: JSON.stringify({ algorithms, trigger }),
      });
      setSettingsDirty(false);
      showToast('설정이 저장되었습니다');
    } catch (e: any) {
      showToast(e.message, 'error');
    }
  };

  const toggleAlgorithm = (id: string, field: 'enabled' | 'auto_apply') => {
    setAlgorithms(prev => prev.map(a => a.id === id ? { ...a, [field]: !a[field] } : a));
    setSettingsDirty(true);
  };

  const runAiAnalysis = async () => {
    if (!analyzeStudyUID.trim()) {
      showToast(searchType === 'study_uid' ? 'Study UID를 입력하세요' : searchType === 'patient_name' ? '환자명을 입력하세요' : '환자번호를 입력하세요', 'error');
      return;
    }
    setAiAnalyzing(true); setAiResult(null);
    try {
      const body: Record<string, string> = {};
      if (searchType === 'study_uid') body.study_instance_uid = analyzeStudyUID.trim();
      else if (searchType === 'patient_name') body.patient_name = analyzeStudyUID.trim();
      else body.patient_id = analyzeStudyUID.trim();

      const res = await apiFetch<any>('/api/v1/normalization/ai-analyze', {
        method: 'POST', body: JSON.stringify(body),
      });
      setAiResult(res);
      showToast('AI 비표준 분석 완료');
    } catch (e: any) {
      showToast(e.message, 'error');
    }
    setAiAnalyzing(false);
  };

  const exportCsv = (rows: any[]) => {
    const header = 'algorithm,files_corrected,percent,avg_ms';
    const body = rows.map(r => `${r.algorithm},${r.files_corrected},${r.percent_of_total},${r.avg_ms}`).join('\n');
    const blob = new Blob([header + '\n' + body], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = `normalization-stats-${Date.now()}.csv`; a.click();
    showToast('CSV 내보내기 완료');
  };

  if (!user) return <div className="p-4 text-gray-500">인증 중...</div>;

  const stats = state.stats;
  const riskColor = { safe: 'bg-emerald-100 text-emerald-700', medium: 'bg-amber-100 text-amber-700', risky: 'bg-red-100 text-red-700' };
  const riskLabel = { safe: '안전', medium: '중간', risky: '위험' };

  return (
    <div className="space-y-6">
      {/* Toast */}
      {state.toast && (
        <div role="alert" className={`fixed bottom-4 right-4 shadow-lg z-50 px-4 py-2 rounded-lg text-sm font-medium ${
          state.toast.type === 'success' ? 'bg-emerald-100 text-emerald-800' : 'bg-red-100 text-red-800'
        }`}>{state.toast.message}</div>
      )}

      {/* Header + Tabs */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-2xl font-bold">DICOM 정규화</h1>
          <div className="flex bg-slate-100 rounded-lg p-0.5">
            {[
              { key: 'dashboard' as const, label: '현황' },
              { key: 'settings' as const, label: '설정' },
              { key: 'ai-analysis' as const, label: 'AI 분석' },
            ].map(t => (
              <button key={t.key} onClick={() => setTab(t.key)}
                className={`px-4 py-1.5 rounded-md text-sm font-medium transition ${
                  tab === t.key ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                }`}>{t.label}</button>
            ))}
          </div>
        </div>
        {tab === 'dashboard' && (
          <div className="flex gap-2">
            <select value={state.days} onChange={e => fetchStats(Number(e.target.value) as 7 | 30 | 90)}
              className="border rounded-lg px-3 py-1.5 text-sm">
              <option value={7}>지난 7일</option>
              <option value={30}>지난 30일</option>
              <option value={90}>지난 90일</option>
            </select>
            <button onClick={() => exportCsv(stats?.algorithm_breakdown || [])}
              className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition">CSV 내보내기</button>
          </div>
        )}
        {tab === 'settings' && settingsDirty && (
          <button onClick={saveSettings} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-semibold hover:bg-blue-700 transition">설정 저장</button>
        )}
      </div>

      {/* ─── Dashboard Tab ─── */}
      {tab === 'dashboard' && (
        <>
          {state.loading && !stats ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                {[...Array(4)].map((_, i) => <div key={i} className="h-24 bg-slate-100 rounded-xl animate-pulse" />)}
              </div>
            </div>
          ) : stats ? (
            <>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <StatCard label={`처리 파일 (${state.days}일)`} value={stats.total_files.toLocaleString()} />
                <StatCard label="성공률" value={`${stats.success_rate}%`} color="text-green-600" />
                <StatCard label="평균 처리시간" value={`${stats.avg_processing_ms}ms`} />
                <StatCard label="검토 대기" value={stats.pending_reviews} color="text-yellow-600" sub="승인 필요" />
              </div>

              {/* Algorithm effectiveness */}
              <div className="bg-white rounded-xl border shadow-sm p-5">
                <h2 className="text-lg font-semibold mb-4">알고리즘 효과성</h2>
                <table className="w-full text-sm">
                  <thead><tr className="border-b text-slate-500">
                    <th className="text-left py-2 px-2">알고리즘</th>
                    <th className="text-right py-2 px-2">보정 파일</th>
                    <th className="text-right py-2 px-2">비율(%)</th>
                    <th className="text-right py-2 px-2">평균(ms)</th>
                  </tr></thead>
                  <tbody>
                    {stats.algorithm_breakdown.map(algo => (
                      <tr key={algo.algorithm} className="border-b hover:bg-slate-50">
                        <td className="py-2.5 px-2">{algo.algorithm}</td>
                        <td className="text-right py-2.5 px-2">{algo.files_corrected.toLocaleString()}</td>
                        <td className="text-right py-2.5 px-2">{algo.percent_of_total.toFixed(1)}%</td>
                        <td className="text-right py-2.5 px-2">{algo.avg_ms}</td>
                      </tr>
                    ))}
                    {stats.algorithm_breakdown.length === 0 && (
                      <tr><td colSpan={4} className="text-gray-400 text-center py-8">데이터가 없습니다</td></tr>
                    )}
                  </tbody>
                </table>
              </div>

              {/* Supplier breakdown */}
              <div className="bg-white rounded-xl border shadow-sm p-5">
                <h2 className="text-lg font-semibold mb-4">공급업체별 현황</h2>
                <table className="w-full text-sm">
                  <thead><tr className="border-b text-slate-500">
                    <th className="text-left py-2 px-2">공급업체</th>
                    <th className="text-right py-2 px-2">파일 수</th>
                    <th className="text-right py-2 px-2">성공률(%)</th>
                    <th className="text-left py-2 px-2">주요 보정 유형</th>
                  </tr></thead>
                  <tbody>
                    {stats.supplier_breakdown.map(s => (
                      <tr key={s.supplier} className="border-b hover:bg-slate-50">
                        <td className="py-2.5 px-2 font-medium">{s.supplier}</td>
                        <td className="text-right py-2.5 px-2">{s.file_count.toLocaleString()}</td>
                        <td className="text-right py-2.5 px-2">{s.avg_success_rate.toFixed(1)}%</td>
                        <td className="py-2.5 px-2">{s.most_common_correction}</td>
                      </tr>
                    ))}
                    {stats.supplier_breakdown.length === 0 && (
                      <tr><td colSpan={4} className="text-gray-400 text-center py-8">데이터가 없습니다</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <div className="text-center py-12 text-gray-500">
              {state.error ? `오류: ${state.error}` : '데이터가 없습니다. 배치 작업을 완료하면 통계가 표시됩니다.'}
            </div>
          )}
        </>
      )}

      {/* ─── Settings Tab ─── */}
      {tab === 'settings' && (
        <div className="space-y-6">
          {/* Algorithm Configuration */}
          <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
            <div className="px-5 py-4 border-b bg-slate-50">
              <h2 className="font-semibold text-lg">정규화 알고리즘 설정</h2>
              <p className="text-sm text-slate-500 mt-1">각 알고리즘의 활성/비활성 및 자동 적용 여부를 설정합니다</p>
            </div>
            <div className="divide-y">
              {algorithms.map(algo => (
                <div key={algo.id} className={`px-5 py-4 flex items-center justify-between ${!algo.enabled ? 'opacity-50' : ''}`}>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm text-slate-800">{algo.name}</span>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${riskColor[algo.risk_level]}`}>
                        {riskLabel[algo.risk_level]}
                      </span>
                    </div>
                    <p className="text-xs text-slate-500 mt-0.5">{algo.description}</p>
                  </div>
                  <div className="flex items-center gap-5 shrink-0 ml-4">
                    {/* Auto Apply Toggle */}
                    <label className="flex items-center gap-2 cursor-pointer">
                      <span className="text-xs text-slate-500 w-14 text-right">자동 적용</span>
                      <button onClick={() => toggleAlgorithm(algo.id, 'auto_apply')}
                        className={`relative inline-flex h-5 w-10 items-center rounded-full transition-colors ${algo.auto_apply && algo.enabled ? 'bg-blue-500' : 'bg-slate-300'} ${!algo.enabled ? 'opacity-40 cursor-not-allowed' : ''}`}
                        disabled={!algo.enabled}>
                        <span className={`inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${algo.auto_apply && algo.enabled ? 'translate-x-[22px]' : 'translate-x-[2px]'}`} />
                      </button>
                    </label>
                    {/* Enable Toggle */}
                    <label className="flex items-center gap-2 cursor-pointer">
                      <span className="text-xs text-slate-500 w-10 text-right">활성</span>
                      <button onClick={() => toggleAlgorithm(algo.id, 'enabled')}
                        className={`relative inline-flex h-5 w-10 items-center rounded-full transition-colors ${algo.enabled ? 'bg-emerald-500' : 'bg-slate-300'}`}>
                        <span className={`inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${algo.enabled ? 'translate-x-[22px]' : 'translate-x-[2px]'}`} />
                      </button>
                    </label>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Risk Classification Rules */}
          <div className="bg-white rounded-xl border shadow-sm p-5">
            <h2 className="font-semibold text-lg mb-4">위험도별 처리 규칙</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="px-2 py-0.5 rounded text-xs font-bold bg-emerald-100 text-emerald-700">안전 (Safe)</span>
                </div>
                <p className="text-xs text-slate-600">문자셋, 날짜 형식, W/L 값 등</p>
                <div className="mt-3 text-sm font-medium text-emerald-700">자동 적용</div>
                <p className="text-xs text-slate-500 mt-1">승인 없이 즉시 정규화 실행</p>
              </div>
              <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="px-2 py-0.5 rounded text-xs font-bold bg-amber-100 text-amber-700">중간 (Medium)</span>
                </div>
                <p className="text-xs text-slate-600">UID 정규화, Transfer Syntax 변환</p>
                <div className="mt-3 text-sm font-medium text-amber-700">권장 조치 제안 + 검토 대기</div>
                <p className="text-xs text-slate-500 mt-1">수정 내용 확인 후 승인/거부</p>
              </div>
              <div className="rounded-xl border border-red-200 bg-red-50/50 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="px-2 py-0.5 rounded text-xs font-bold bg-red-100 text-red-700">위험 (Risky)</span>
                </div>
                <p className="text-xs text-slate-600">JPEG 밀도, Pixel Spacing 수정</p>
                <div className="mt-3 text-sm font-medium text-red-700">수동 승인 필수</div>
                <p className="text-xs text-slate-500 mt-1">측정값 오류 가능성 — 반드시 검토</p>
              </div>
            </div>
          </div>

          {/* Trigger Settings */}
          <div className="bg-white rounded-xl border shadow-sm p-5">
            <h2 className="font-semibold text-lg mb-4">작업 트리거 설정</h2>
            <div className="space-y-4">
              <label className="flex items-center justify-between p-4 rounded-xl border hover:bg-slate-50 transition cursor-pointer">
                <div>
                  <div className="font-medium text-sm">수신 시 자동 정규화</div>
                  <p className="text-xs text-slate-500 mt-0.5">Orthanc C-STORE 수신 시 자동으로 정규화 실행 (safe 항목만)</p>
                </div>
                <button onClick={() => { setTrigger(prev => ({ ...prev, on_receive: !prev.on_receive })); setSettingsDirty(true); }}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${trigger.on_receive ? 'bg-blue-500' : 'bg-slate-300'}`}>
                  <span className={`inline-block h-5 w-5 rounded-full bg-white shadow-sm transition-transform ${trigger.on_receive ? 'translate-x-[22px]' : 'translate-x-[2px]'}`} />
                </button>
              </label>

              <label className="flex items-center justify-between p-4 rounded-xl border hover:bg-slate-50 transition cursor-pointer">
                <div className="flex items-center gap-4">
                  <div>
                    <div className="font-medium text-sm">야간 배치 스케줄</div>
                    <p className="text-xs text-slate-500 mt-0.5">매일 지정 시간에 미처리 DICOM 일괄 정규화</p>
                  </div>
                  {trigger.scheduled && (
                    <input type="time" value={trigger.schedule_time}
                      onChange={e => { setTrigger(prev => ({ ...prev, schedule_time: e.target.value })); setSettingsDirty(true); }}
                      className="border rounded-lg px-3 py-1.5 text-sm" />
                  )}
                </div>
                <button onClick={() => { setTrigger(prev => ({ ...prev, scheduled: !prev.scheduled })); setSettingsDirty(true); }}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${trigger.scheduled ? 'bg-blue-500' : 'bg-slate-300'}`}>
                  <span className={`inline-block h-5 w-5 rounded-full bg-white shadow-sm transition-transform ${trigger.scheduled ? 'translate-x-[22px]' : 'translate-x-[2px]'}`} />
                </button>
              </label>

              <div className="p-4 rounded-xl border border-dashed border-slate-300 text-center">
                <Link href="/normalization/batches" className="text-blue-600 hover:underline text-sm font-medium">
                  배치 작업 관리 →
                </Link>
                <p className="text-xs text-slate-400 mt-1">수동 업로드 및 배치 실행 이력 조회</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ─── AI Analysis Tab ─── */}
      {tab === 'ai-analysis' && (
        <div className="space-y-6">
          {/* Analysis Input */}
          <div className="bg-white rounded-xl border shadow-sm p-5">
            <h2 className="font-semibold text-lg mb-2">AI 비표준 DICOM 분석</h2>
            <p className="text-sm text-slate-500 mb-4">
              DICOM Study를 AI로 분석하여 비표준 요소를 자동 감지하고 권장 정규화 알고리즘을 제안합니다
            </p>
            <div className="flex gap-3">
              <div className="flex bg-slate-100 rounded-xl p-0.5 shrink-0">
                {([
                  { key: 'study_uid' as const, label: 'Study UID' },
                  { key: 'patient_name' as const, label: '환자명' },
                  { key: 'patient_id' as const, label: '환자번호' },
                ] as const).map(t => (
                  <button key={t.key} onClick={() => { setSearchType(t.key); setAnalyzeStudyUID(''); }}
                    className={`px-3 py-2 rounded-lg text-xs font-medium transition ${
                      searchType === t.key ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                    }`}>{t.label}</button>
                ))}
              </div>
              <input type="text"
                placeholder={searchType === 'study_uid' ? 'Study Instance UID 입력' : searchType === 'patient_name' ? '환자명 입력 (부분 검색 가능)' : '환자번호 입력'}
                value={analyzeStudyUID}
                onChange={e => setAnalyzeStudyUID(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && runAiAnalysis()}
                className="flex-1 border border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:border-blue-400 focus:ring-2 focus:ring-blue-100 outline-none" />
              <button onClick={runAiAnalysis} disabled={aiAnalyzing}
                className="px-6 py-2.5 bg-violet-600 text-white rounded-xl text-sm font-semibold hover:bg-violet-700 transition disabled:opacity-50 flex items-center gap-2 shrink-0">
                {aiAnalyzing && <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
                {aiAnalyzing ? '분석 중...' : 'AI 분석 실행'}
              </button>
            </div>
          </div>

          {/* Analysis Items Description */}
          <div className="bg-white rounded-xl border shadow-sm p-5">
            <h3 className="font-semibold mb-3">분석 항목</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {[
                { icon: '🔍', title: 'JPEG 압축 밀도 조작', desc: 'JFIF 헤더 vs DICOM 태그 교차 검증' },
                { icon: '📐', title: 'Pixel Spacing 불일치', desc: '패턴 학습 기반 불일치 감지' },
                { icon: '🔤', title: '비표준 인코딩 감지', desc: '깨진 한글, 잘못된 Character Set' },
                { icon: '🔄', title: 'Transfer Syntax', desc: '비표준 전송 구문 식별' },
                { icon: '📋', title: '필수 태그 누락', desc: 'DICOM 필수/권장 태그 검증' },
                { icon: '🏭', title: '제조사별 패턴 매칭', desc: '장비 제조사 알려진 비표준 패턴' },
              ].map(item => (
                <div key={item.title} className="flex items-start gap-3 p-3 rounded-xl bg-slate-50">
                  <span className="text-lg">{item.icon}</span>
                  <div>
                    <div className="text-sm font-medium text-slate-700">{item.title}</div>
                    <div className="text-xs text-slate-500">{item.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* AI Result */}
          {aiResult && (
            <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
              <div className="px-5 py-4 border-b bg-violet-50">
                <h3 className="font-semibold text-violet-900">분석 결과</h3>
                <p className="text-xs text-violet-600 mt-1">
                  {aiResult.total_issues || 0}건의 비표준 항목 발견
                  {aiResult.duration_ms && ` (${aiResult.duration_ms}ms)`}
                </p>
              </div>
              <div className="divide-y">
                {(aiResult.issues || []).length === 0 ? (
                  <div className="px-5 py-8 text-center text-slate-400">비표준 항목이 없습니다. DICOM 표준을 준수합니다.</div>
                ) : (
                  (aiResult.issues || []).map((issue: any, i: number) => (
                    <div key={i} className="px-5 py-4 flex items-center justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-slate-800">{issue.tag || issue.field}</span>
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${riskColor[issue.risk_level as keyof typeof riskColor] || 'bg-slate-100'}`}>
                            {riskLabel[issue.risk_level as keyof typeof riskLabel] || issue.risk_level}
                          </span>
                          {issue.auto_fixable && (
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-100 text-blue-700">자동 수정 가능</span>
                          )}
                        </div>
                        <p className="text-xs text-slate-500 mt-0.5">{issue.description}</p>
                        {issue.current_value && (
                          <div className="text-xs text-slate-400 mt-1">
                            현재: <code className="bg-slate-100 px-1 rounded">{issue.current_value}</code>
                            {issue.suggested_value && (
                              <> → 권장: <code className="bg-emerald-50 text-emerald-700 px-1 rounded">{issue.suggested_value}</code></>
                            )}
                          </div>
                        )}
                      </div>
                      <div className="text-xs text-slate-400 shrink-0 ml-4">{issue.algorithm}</div>
                    </div>
                  ))
                )}
              </div>
              {(aiResult.issues || []).length > 0 && (
                <div className="px-5 py-4 border-t bg-slate-50 flex justify-end gap-3">
                  <button className="px-4 py-2 border border-slate-300 rounded-lg text-sm font-medium hover:bg-slate-100 transition">
                    리포트 다운로드
                  </button>
                  <button className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-semibold hover:bg-blue-700 transition">
                    일괄 정규화 실행
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Workflow Diagram */}
          <div className="bg-slate-50 rounded-xl border border-slate-200 p-5">
            <h3 className="font-semibold text-sm text-slate-600 mb-3">정규화 워크플로우</h3>
            <div className="flex items-center gap-2 text-xs text-slate-500 overflow-x-auto pb-2">
              <span className="bg-white border rounded-lg px-3 py-2 whitespace-nowrap font-medium">DICOM 수신</span>
              <span className="text-slate-300">→</span>
              <span className="bg-violet-100 text-violet-700 border border-violet-200 rounded-lg px-3 py-2 whitespace-nowrap font-medium">AI 분석</span>
              <span className="text-slate-300">→</span>
              <div className="flex flex-col gap-1">
                <span className="bg-emerald-100 text-emerald-700 rounded-lg px-3 py-1.5 whitespace-nowrap">Safe → 자동 정규화</span>
                <span className="bg-amber-100 text-amber-700 rounded-lg px-3 py-1.5 whitespace-nowrap">Medium → 검토 대기</span>
                <span className="bg-red-100 text-red-700 rounded-lg px-3 py-1.5 whitespace-nowrap">Risky → 수동 승인</span>
              </div>
              <span className="text-slate-300">→</span>
              <span className="bg-white border rounded-lg px-3 py-2 whitespace-nowrap font-medium">정규화 완료</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
