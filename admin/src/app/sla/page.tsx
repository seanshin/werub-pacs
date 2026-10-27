'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch, getUser } from '@/lib/api';

type ModalityThreshold = {
  modality: string; warning_minutes: number; critical_minutes: number; auto_escalate: boolean;
};
type EscalationRule = {
  id: string; name: string; trigger: string; action: string;
  target_role: string | null; target_username: string | null; enabled: boolean;
};
type EscalationLog = {
  id: string; study_instance_uid: string; escalation_type: string;
  action_taken: string; from_user: string | null; to_user: string | null;
  notes: string | null; triggered_at: string; resolved_at: string | null; sla_minutes: number | null;
};
type SLAStats = {
  period_days: number; total: number; resolved: number; unresolved: number;
  avg_resolution_minutes: number; by_type: Record<string, number>;
};

const ACTION_LABEL: Record<string, string> = {
  reassign: '자동 재배정', notify: '알림 발송', escalate_to_supervisor: '상급자 에스컬레이션',
};
const TRIGGER_LABEL: Record<string, string> = { warning: '경고', critical: '위험' };

export default function SLAPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [tab, setTab] = useState<'config' | 'history' | 'stats'>('config');
  const [thresholds, setThresholds] = useState<ModalityThreshold[]>([]);
  const [rules, setRules] = useState<EscalationRule[]>([]);
  const [logs, setLogs] = useState<EscalationLog[]>([]);
  const [stats, setStats] = useState<SLAStats | null>(null);
  const [dirty, setDirty] = useState(false);
  const [toast, setToast] = useState('');
  const [schedulerStatus, setSchedulerStatus] = useState<any>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    const u = getUser();
    if (!u || u.role !== 'admin') { router.replace('/'); return; }
    setUser(u);
    loadConfig(); loadLogs(); loadStats(); loadScheduler();
  }, []);

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(''), 3000); };

  const loadConfig = async () => {
    try {
      const d = await apiFetch<{ thresholds: ModalityThreshold[]; rules: EscalationRule[] }>('/api/v1/sla/config');
      setThresholds(d.thresholds || []); setRules(d.rules || []);
    } catch {}
  };

  const loadLogs = async () => {
    try {
      const d = await apiFetch<{ items: EscalationLog[] }>('/api/v1/sla/escalations');
      setLogs(d.items || []);
    } catch {}
  };

  const loadStats = async () => {
    try {
      const d = await apiFetch<SLAStats>('/api/v1/sla/stats?days=30');
      setStats(d);
    } catch {}
  };

  const loadScheduler = async () => {
    try {
      const d = await apiFetch<any>('/api/v1/sla/scheduler-status');
      setSchedulerStatus(d);
    } catch {}
  };

  const runCheckNow = async () => {
    setChecking(true);
    try {
      await apiFetch('/api/v1/sla/check-now', { method: 'POST' });
      showToast('SLA 체크가 실행되었습니다');
      setTimeout(() => { loadLogs(); loadStats(); }, 5000);
    } catch (e: any) { showToast(e.message); }
    setChecking(false);
  };

  const saveConfig = async () => {
    try {
      await apiFetch('/api/v1/sla/config', {
        method: 'PUT', body: JSON.stringify({ thresholds, rules }),
      });
      setDirty(false); showToast('SLA 설정이 저장되었습니다');
    } catch (e: any) { showToast(e.message); }
  };

  const updateThreshold = (idx: number, field: string, value: any) => {
    setThresholds(prev => prev.map((t, i) => i === idx ? { ...t, [field]: value } : t));
    setDirty(true);
  };

  const toggleRule = (id: string) => {
    setRules(prev => prev.map(r => r.id === id ? { ...r, enabled: !r.enabled } : r));
    setDirty(true);
  };

  const resolveEscalation = async (id: string) => {
    try {
      await apiFetch(`/api/v1/sla/escalations/${id}/resolve`, { method: 'PATCH' });
      showToast('에스컬레이션 해결 완료'); loadLogs(); loadStats();
    } catch (e: any) { showToast(e.message); }
  };

  if (!user) return null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-2xl font-bold">SLA 에스컬레이션</h1>
          <div className="flex bg-slate-100 rounded-lg p-0.5">
            {[
              { key: 'config' as const, label: '설정' },
              { key: 'history' as const, label: '이력' },
              { key: 'stats' as const, label: '통계' },
            ].map(t => (
              <button key={t.key} onClick={() => setTab(t.key)}
                className={`px-4 py-1.5 rounded-md text-sm font-medium transition ${
                  tab === t.key ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                }`}>{t.label}</button>
            ))}
          </div>
        </div>
        {tab === 'config' && dirty && (
          <button onClick={saveConfig} className="px-4 py-2 bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700 transition">
            설정 저장
          </button>
        )}
      </div>

      {/* ─── Config Tab ─── */}
      {tab === 'config' && (
        <div className="space-y-6">
          {/* Modality Thresholds */}
          <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
            <div className="px-5 py-4 border-b bg-slate-50">
              <h2 className="font-semibold text-lg">모달리티별 SLA 임계값</h2>
              <p className="text-sm text-slate-500 mt-1">각 모달리티의 경고/위험 시간(분)을 설정합니다</p>
            </div>
            <table className="w-full text-sm">
              <thead className="text-slate-500 bg-slate-50/50">
                <tr>
                  <th className="px-5 py-3 text-left">모달리티</th>
                  <th className="px-5 py-3 text-center">경고 (분)</th>
                  <th className="px-5 py-3 text-center">위험 (분)</th>
                  <th className="px-5 py-3 text-center">자동 에스컬레이션</th>
                </tr>
              </thead>
              <tbody>
                {thresholds.map((t, i) => (
                  <tr key={t.modality} className="border-t hover:bg-slate-50">
                    <td className="px-5 py-3 font-medium">
                      {t.modality === 'default' ? (
                        <span className="text-slate-500">기본값</span>
                      ) : (
                        <span className="px-2 py-0.5 rounded bg-blue-100 text-blue-700 text-xs font-bold">{t.modality}</span>
                      )}
                    </td>
                    <td className="px-5 py-3 text-center">
                      <input type="number" value={t.warning_minutes} min={5} max={480}
                        onChange={e => updateThreshold(i, 'warning_minutes', parseInt(e.target.value) || 30)}
                        className="w-20 border rounded-lg px-2 py-1.5 text-sm text-center focus:border-amber-400 outline-none" />
                    </td>
                    <td className="px-5 py-3 text-center">
                      <input type="number" value={t.critical_minutes} min={10} max={960}
                        onChange={e => updateThreshold(i, 'critical_minutes', parseInt(e.target.value) || 60)}
                        className="w-20 border rounded-lg px-2 py-1.5 text-sm text-center focus:border-red-400 outline-none" />
                    </td>
                    <td className="px-5 py-3 text-center">
                      <button onClick={() => updateThreshold(i, 'auto_escalate', !t.auto_escalate)}
                        className={`relative w-9 h-5 rounded-full transition ${t.auto_escalate ? 'bg-blue-500' : 'bg-slate-300'}`}>
                        <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${t.auto_escalate ? 'translate-x-4' : 'translate-x-0.5'}`} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Escalation Rules */}
          <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
            <div className="px-5 py-4 border-b bg-slate-50">
              <h2 className="font-semibold text-lg">에스컬레이션 규칙</h2>
              <p className="text-sm text-slate-500 mt-1">임계값 도달 시 자동으로 실행될 액션을 설정합니다</p>
            </div>
            <div className="divide-y">
              {rules.map(rule => (
                <div key={rule.id} className={`px-5 py-4 flex items-center justify-between ${!rule.enabled ? 'opacity-50' : ''}`}>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm">{rule.name}</span>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        rule.trigger === 'critical' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
                      }`}>{TRIGGER_LABEL[rule.trigger]}</span>
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-100 text-blue-700">
                        {ACTION_LABEL[rule.action] || rule.action}
                      </span>
                    </div>
                    <p className="text-xs text-slate-500 mt-0.5">
                      대상: {rule.target_role || '(없음)'} {rule.target_username ? `(${rule.target_username})` : ''}
                    </p>
                  </div>
                  <button onClick={() => toggleRule(rule.id)}
                    className={`relative w-9 h-5 rounded-full transition ${rule.enabled ? 'bg-emerald-500' : 'bg-slate-300'}`}>
                    <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${rule.enabled ? 'translate-x-4' : 'translate-x-0.5'}`} />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Scheduler Status */}
          <div className="bg-white rounded-xl border shadow-sm p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-lg">자동 스케줄러</h2>
              <button onClick={runCheckNow} disabled={checking}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-semibold hover:bg-blue-700 transition disabled:opacity-50 flex items-center gap-2">
                {checking && <span className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
                {checking ? '실행 중...' : '지금 체크'}
              </button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="rounded-xl bg-emerald-50 border border-emerald-200 p-4">
                <div className="text-xs text-emerald-600 font-semibold mb-1">SLA 체크</div>
                <div className="text-sm font-medium text-emerald-800">5분 간격</div>
                <p className="text-xs text-emerald-600 mt-1">미판독 Study → 임계값 비교 → 자동 에스컬레이션</p>
              </div>
              <div className="rounded-xl bg-blue-50 border border-blue-200 p-4">
                <div className="text-xs text-blue-600 font-semibold mb-1">자동 해결</div>
                <div className="text-sm font-medium text-blue-800">10분 간격</div>
                <p className="text-xs text-blue-600 mt-1">판독 완료된 Study → 에스컬레이션 자동 해결</p>
              </div>
              <div className="rounded-xl bg-slate-50 border border-slate-200 p-4">
                <div className="text-xs text-slate-500 font-semibold mb-1">엔진</div>
                <div className="text-sm font-medium text-slate-700">Celery Beat</div>
                <p className="text-xs text-slate-500 mt-1">
                  {schedulerStatus?.tasks ? `${Object.keys(schedulerStatus.tasks).length}개 태스크 등록` : '상태 로딩 중...'}
                </p>
              </div>
            </div>
          </div>

          {/* Escalation Chain */}
          <div className="bg-slate-50 rounded-xl border border-slate-200 p-5">
            <h3 className="font-semibold text-sm text-slate-600 mb-3">에스컬레이션 체인</h3>
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <span className="bg-white border rounded-lg px-3 py-2 font-medium">검사 완료</span>
              <span className="text-slate-300">→</span>
              <span className="bg-amber-100 text-amber-700 rounded-lg px-3 py-2 font-medium">경고 (알림)</span>
              <span className="text-slate-300">→</span>
              <span className="bg-red-100 text-red-700 rounded-lg px-3 py-2 font-medium">위험 (재배정)</span>
              <span className="text-slate-300">→</span>
              <span className="bg-violet-100 text-violet-700 rounded-lg px-3 py-2 font-medium">상급자 에스컬레이션</span>
              <span className="text-slate-300">→</span>
              <span className="bg-emerald-100 text-emerald-700 rounded-lg px-3 py-2 font-medium">해결</span>
            </div>
          </div>
        </div>
      )}

      {/* ─── History Tab ─── */}
      {tab === 'history' && (
        <div className="bg-white rounded-xl border shadow-sm overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left">유형</th>
                <th className="px-4 py-3 text-left">Study UID</th>
                <th className="px-4 py-3 text-left">액션</th>
                <th className="px-4 py-3 text-left">From → To</th>
                <th className="px-4 py-3 text-left">발생 시각</th>
                <th className="px-4 py-3 text-left">상태</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {logs.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-12 text-center text-slate-400">에스컬레이션 이력이 없습니다</td></tr>
              )}
              {logs.map(log => (
                <tr key={log.id} className="border-t hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      log.escalation_type.includes('critical') ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
                    }`}>{log.escalation_type}</span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-500 max-w-[200px] truncate">{log.study_instance_uid}</td>
                  <td className="px-4 py-3 text-slate-600">{log.action_taken}</td>
                  <td className="px-4 py-3 text-slate-500">{log.from_user || '-'} → {log.to_user || '-'}</td>
                  <td className="px-4 py-3 text-slate-500 whitespace-nowrap">
                    {log.triggered_at ? new Date(log.triggered_at).toLocaleString('ko-KR') : '-'}
                  </td>
                  <td className="px-4 py-3">
                    {log.resolved_at ? (
                      <span className="px-2 py-0.5 rounded text-xs font-medium bg-emerald-100 text-emerald-700">해결</span>
                    ) : (
                      <span className="px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-700">미해결</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {!log.resolved_at && (
                      <button onClick={() => resolveEscalation(log.id)}
                        className="px-2.5 py-1 bg-emerald-600 text-white rounded text-xs font-medium hover:bg-emerald-700">
                        해결
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ─── Stats Tab ─── */}
      {tab === 'stats' && stats && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-white rounded-xl border shadow-sm p-4">
              <div className="text-xs text-slate-500">총 에스컬레이션 (30일)</div>
              <div className="text-2xl font-bold text-slate-800">{stats.total}</div>
            </div>
            <div className="bg-white rounded-xl border shadow-sm p-4">
              <div className="text-xs text-slate-500">해결됨</div>
              <div className="text-2xl font-bold text-emerald-600">{stats.resolved}</div>
            </div>
            <div className="bg-white rounded-xl border shadow-sm p-4">
              <div className="text-xs text-slate-500">미해결</div>
              <div className="text-2xl font-bold text-amber-600">{stats.unresolved}</div>
            </div>
            <div className="bg-white rounded-xl border shadow-sm p-4">
              <div className="text-xs text-slate-500">평균 해결 시간</div>
              <div className="text-2xl font-bold text-blue-600">{stats.avg_resolution_minutes}분</div>
            </div>
          </div>

          {/* By Type */}
          <div className="bg-white rounded-xl border shadow-sm p-5">
            <h2 className="font-semibold text-lg mb-4">유형별 분포</h2>
            {Object.keys(stats.by_type).length === 0 ? (
              <p className="text-slate-400 text-center py-8">데이터가 없습니다</p>
            ) : (
              <div className="space-y-3">
                {Object.entries(stats.by_type).map(([type, count]) => (
                  <div key={type} className="flex items-center gap-4">
                    <span className="w-40 text-sm text-slate-600">{type}</span>
                    <div className="flex-1 bg-slate-100 rounded-full h-5 overflow-hidden">
                      <div className="bg-blue-500 h-full rounded-full transition-all"
                        style={{ width: `${stats.total > 0 ? (count / stats.total * 100) : 0}%` }} />
                    </div>
                    <span className="w-12 text-right text-sm font-medium text-slate-700">{count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-slate-900 text-white px-6 py-3 rounded-xl shadow-2xl text-sm font-medium z-50">
          {toast}
        </div>
      )}
    </div>
  );
}
