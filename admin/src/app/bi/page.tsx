'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  BarChart3, CheckCircle2, Clock, Users, AlertTriangle, TrendingUp, Activity,
  Inbox, FileWarning, GitBranch, CalendarClock, Download,
} from 'lucide-react';
import { apiFetch } from '@/lib/api';
import Breadcrumb from '@/components/ui/Breadcrumb';

type Summary = {
  total: number; completed: number; completion_rate: number | null;
  readers: number; urgent: number; avg_tat_h: number | null; p90_tat_h: number | null;
};
type Reception = {
  received: number; reported: number; read_done: number; unread: number;
  read_rate: number | null; by_origin: { origin: string; count: number }[];
};
type TrendRow = { month: string; received: number; completed: number };
type ModalityRow = { modality: string; total: number; completed: number; avg_tat_h: number | null };
type ReaderRow = { reader: string; signed: number; avg_tat_h: number | null };
type BI = {
  period_days: number; trend_months: number;
  summary: Summary; reception: Reception;
  volume_trend: TrendRow[]; modality: ModalityRow[]; readers: ReaderRow[];
};
type MonthlyRow = {
  month: string; received: number; reported: number; read_done: number;
  avg_tat_h: number | null; p90_tat_h: number | null;
  modality_breakdown: Record<string, number>; origin_breakdown: Record<string, number>;
  generated_at: string;
};

const PERIODS = [
  { days: 7, label: '최근 7일' },
  { days: 30, label: '최근 30일' },
  { days: 90, label: '최근 90일' },
  { days: 365, label: '최근 1년' },
];
const ORIGIN_LABEL: Record<string, string> = {
  internal: '원내', external: '전원', patient_upload: '환자업로드', kiosk: '키오스크',
  test_data: '테스트', ai_generated: 'AI생성', research: '연구', migration: '이관', unknown: '미상',
};

const fmtTat = (h: number | null) => (h == null ? '—' : h < 1 ? `${Math.round(h * 60)}분` : `${h.toFixed(1)}시간`);
const pct = (r: number | null) => (r == null ? '—' : `${(r * 100).toFixed(0)}%`);

function Kpi({ icon: Icon, label, value, sub, tint }: {
  icon: any; label: string; value: string; sub?: string; tint: string;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
      <div className="flex items-center gap-2">
        <span className={`flex h-8 w-8 items-center justify-center rounded-lg ${tint}`}>
          <Icon size={17} />
        </span>
        <span className="text-sm text-gray-500 dark:text-gray-400">{label}</span>
      </div>
      <div className="mt-2 text-2xl font-bold text-gray-900 dark:text-gray-100">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-gray-400">{sub}</div>}
    </div>
  );
}

export default function BIPage() {
  const [days, setDays] = useState(90);
  const [data, setData] = useState<BI | null>(null);
  const [history, setHistory] = useState<MonthlyRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setErr('');
    try {
      const [res, hist]: any = await Promise.all([
        apiFetch(`/api/v1/bi/operational?days=${days}&months=12`),
        apiFetch(`/api/v1/bi/monthly-history?limit=12`).catch(() => ({ reports: [] })),
      ]);
      setData(res); setHistory(hist?.reports || []);
    } catch (e: any) {
      setErr(e?.message || 'BI 데이터 로드 실패'); setData(null);
    } finally { setLoading(false); }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  const exportCsv = useCallback(async () => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('pacs_token') : null;
    const res = await fetch(`/pacs-api/api/v1/bi/export?days=${days}&months=12`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) { setErr('CSV 내보내기 실패'); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `openpacs-bi-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [days]);

  const s = data?.summary;
  const rc = data?.reception;
  const maxTrend = Math.max(1, ...(data?.volume_trend.map((t) => t.received) || [1]));
  const maxMod = Math.max(1, ...(data?.modality.map((m) => m.total) || [1]));
  const maxOrigin = Math.max(1, ...(rc?.by_origin.map((o) => o.count) || [1]));

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <Breadcrumb items={[{ label: '경영 BI' }]} />
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold text-gray-900 dark:text-gray-100">
            <BarChart3 size={22} className="text-indigo-500" /> 경영/운영 BI 리포트
          </h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            수신 검사량 · 판독 처리 · 모달리티 가동률 · TAT · 판독의 생산성
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-1 rounded-lg border border-gray-200 p-1 dark:border-gray-700">
            {PERIODS.map((p) => (
              <button key={p.days} onClick={() => setDays(p.days)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
                  days === p.days ? 'bg-indigo-500 text-white' : 'text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700'
                }`}>{p.label}</button>
            ))}
          </div>
          <button onClick={exportCsv}
            className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium text-gray-600 transition hover:bg-gray-100 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-700">
            <Download size={15} /> CSV
          </button>
        </div>
      </div>

      {err && <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">{err}</div>}
      {loading && !data && <div className="py-20 text-center text-gray-400">불러오는 중…</div>}

      {s && rc && (
        <>
          {/* 수신(접수) KPI — 전체 검사량, 미판독 포함 */}
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">수신 (접수 검사량)</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Kpi icon={Inbox} label="수신 검사" value={rc.received.toLocaleString()} sub="전체 study(미판독 포함)" tint="bg-teal-100 text-teal-600 dark:bg-teal-900/40 dark:text-teal-300" />
            <Kpi icon={CheckCircle2} label="판독 완료" value={rc.read_done.toLocaleString()} sub={`판독률 ${pct(rc.read_rate)}`} tint="bg-green-100 text-green-600 dark:bg-green-900/40 dark:text-green-300" />
            <Kpi icon={FileWarning} label="미판독" value={rc.unread.toLocaleString()} sub="수신 − 판독완료" tint="bg-orange-100 text-orange-600 dark:bg-orange-900/40 dark:text-orange-300" />
            <Kpi icon={GitBranch} label="유입 경로" value={String(rc.by_origin.length)} sub="origin 종류" tint="bg-slate-100 text-slate-600 dark:bg-slate-700/60 dark:text-slate-300" />
          </div>

          {/* 판독 KPI */}
          <h2 className="mb-2 mt-6 text-xs font-semibold uppercase tracking-wide text-gray-400">판독 처리</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Kpi icon={Activity} label="총 판독" value={s.total.toLocaleString()} tint="bg-indigo-100 text-indigo-600 dark:bg-indigo-900/40 dark:text-indigo-300" />
            <Kpi icon={CheckCircle2} label="완료" value={s.completed.toLocaleString()} sub={`완료율 ${pct(s.completion_rate)}`} tint="bg-green-100 text-green-600 dark:bg-green-900/40 dark:text-green-300" />
            <Kpi icon={Clock} label="평균 TAT" value={fmtTat(s.avg_tat_h)} tint="bg-sky-100 text-sky-600 dark:bg-sky-900/40 dark:text-sky-300" />
            <Kpi icon={TrendingUp} label="P90 TAT" value={fmtTat(s.p90_tat_h)} tint="bg-violet-100 text-violet-600 dark:bg-violet-900/40 dark:text-violet-300" />
            <Kpi icon={Users} label="활성 판독의" value={String(s.readers)} tint="bg-amber-100 text-amber-600 dark:bg-amber-900/40 dark:text-amber-300" />
            <Kpi icon={AlertTriangle} label="긴급" value={s.urgent.toLocaleString()} tint="bg-red-100 text-red-600 dark:bg-red-900/40 dark:text-red-300" />
          </div>

          {/* 월별 수신량 추이 */}
          <section className="mt-6 rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-800">
            <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-gray-700 dark:text-gray-200">
              <TrendingUp size={16} /> 월별 수신량 추이 (최근 {data.trend_months}개월)
            </h2>
            {data.volume_trend.length === 0 ? (
              <p className="py-6 text-center text-sm text-gray-400">데이터 없음</p>
            ) : (
              <div className="flex items-end gap-3 overflow-x-auto pb-1" style={{ height: 180 }}>
                {data.volume_trend.map((t) => (
                  <div key={t.month} className="flex min-w-[44px] flex-1 flex-col items-center justify-end gap-1">
                    <span className="text-xs font-medium text-gray-600 dark:text-gray-300">{t.received}</span>
                    <div className="flex w-full flex-col justify-end rounded-t bg-teal-100 dark:bg-teal-900/40" style={{ height: `${(t.received / maxTrend) * 130}px` }}>
                      <div className="rounded-t bg-teal-500" style={{ height: `${(t.completed / Math.max(1, t.received)) * 100}%` }} title={`판독완료 ${t.completed}`} />
                    </div>
                    <span className="text-[11px] text-gray-400">{t.month.slice(2)}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-3 flex gap-4 text-xs text-gray-400">
              <span className="flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-sm bg-teal-500" /> 판독완료</span>
              <span className="flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-sm bg-teal-100 dark:bg-teal-900/40" /> 미판독</span>
            </div>
          </section>

          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            {/* 유입 경로별 */}
            <section className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-800">
              <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-gray-700 dark:text-gray-200">
                <GitBranch size={16} /> 유입 경로별 수신량
              </h2>
              {rc.by_origin.length === 0 ? (
                <p className="py-6 text-center text-sm text-gray-400">데이터 없음</p>
              ) : (
                <div className="space-y-2.5">
                  {rc.by_origin.map((o) => (
                    <div key={o.origin} className="flex items-center gap-3">
                      <span className="w-20 shrink-0 text-sm font-medium text-gray-700 dark:text-gray-300">{ORIGIN_LABEL[o.origin] || o.origin}</span>
                      <div className="relative h-6 flex-1 overflow-hidden rounded bg-gray-100 dark:bg-gray-700">
                        <div className="h-full rounded bg-teal-400" style={{ width: `${(o.count / maxOrigin) * 100}%` }} />
                      </div>
                      <span className="w-10 shrink-0 text-right text-sm tabular-nums text-gray-600 dark:text-gray-300">{o.count}</span>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* 모달리티 가동률 */}
            <section className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-800">
              <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-gray-700 dark:text-gray-200">
                <BarChart3 size={16} /> 모달리티별 판독량 · TAT
              </h2>
              {data.modality.length === 0 ? (
                <p className="py-6 text-center text-sm text-gray-400">데이터 없음</p>
              ) : (
                <div className="space-y-2.5">
                  {data.modality.map((m) => (
                    <div key={m.modality} className="flex items-center gap-3">
                      <span className="w-12 shrink-0 text-sm font-medium text-gray-700 dark:text-gray-300">{m.modality}</span>
                      <div className="relative h-6 flex-1 overflow-hidden rounded bg-gray-100 dark:bg-gray-700">
                        <div className="h-full rounded bg-indigo-400" style={{ width: `${(m.total / maxMod) * 100}%` }} />
                      </div>
                      <span className="w-10 shrink-0 text-right text-sm tabular-nums text-gray-600 dark:text-gray-300">{m.total}</span>
                      <span className="w-16 shrink-0 text-right text-xs tabular-nums text-gray-400">{fmtTat(m.avg_tat_h)}</span>
                    </div>
                  ))}
                </div>
              )}
              <p className="mt-3 text-[11px] text-gray-400">막대=판독 건수, 우측=평균 TAT</p>
            </section>
          </div>

          {/* 판독의 생산성 */}
          <section className="mt-6 rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-800">
            <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-gray-700 dark:text-gray-200">
              <Users size={16} /> 판독의 생산성 (서명 기준)
            </h2>
            {data.readers.length === 0 ? (
              <p className="py-6 text-center text-sm text-gray-400">데이터 없음</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 text-left text-xs text-gray-400 dark:border-gray-700">
                    <th className="pb-2 font-medium">판독의</th>
                    <th className="pb-2 text-right font-medium">서명 건수</th>
                    <th className="pb-2 text-right font-medium">평균 TAT</th>
                  </tr>
                </thead>
                <tbody>
                  {data.readers.map((r) => (
                    <tr key={r.reader} className="border-b border-gray-50 last:border-0 dark:border-gray-700/50">
                      <td className="py-2 text-gray-700 dark:text-gray-300">{r.reader}</td>
                      <td className="py-2 text-right tabular-nums text-gray-900 dark:text-gray-100">{r.signed}</td>
                      <td className="py-2 text-right tabular-nums text-gray-500">{fmtTat(r.avg_tat_h)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          {/* 월간 자동 리포트 이력 */}
          {history.length > 0 && (
            <section className="mt-6 rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-800">
              <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-gray-700 dark:text-gray-200">
                <CalendarClock size={16} /> 월간 리포트 이력 <span className="text-xs font-normal text-gray-400">(매월 1일 자동 집계)</span>
              </h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 text-left text-xs text-gray-400 dark:border-gray-700">
                      <th className="pb-2 pr-3 font-medium">월</th>
                      <th className="pb-2 px-3 text-right font-medium">수신</th>
                      <th className="pb-2 px-3 text-right font-medium">판독완료</th>
                      <th className="pb-2 px-3 text-right font-medium">판독률</th>
                      <th className="pb-2 px-3 text-right font-medium">평균 TAT</th>
                      <th className="pb-2 pl-3 font-medium">모달리티</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((m) => {
                      const rate = m.received ? (m.read_done / m.received) * 100 : 0;
                      const topMod = Object.entries(m.modality_breakdown || {})
                        .sort((a, b) => b[1] - a[1]).slice(0, 4)
                        .map(([k, v]) => `${k} ${v}`).join(' · ');
                      return (
                        <tr key={m.month} className="border-b border-gray-50 last:border-0 dark:border-gray-700/50">
                          <td className="py-2 pr-3 font-medium text-gray-800 dark:text-gray-200">{m.month}</td>
                          <td className="py-2 px-3 text-right tabular-nums">{m.received}</td>
                          <td className="py-2 px-3 text-right tabular-nums">{m.read_done}</td>
                          <td className="py-2 px-3 text-right tabular-nums text-gray-500">{rate.toFixed(0)}%</td>
                          <td className="py-2 px-3 text-right tabular-nums text-gray-500">{fmtTat(m.avg_tat_h)}</td>
                          <td className="py-2 pl-3 text-xs text-gray-400">{topMod || '—'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <p className="mt-6 text-center text-xs text-gray-400">
            수신=DICOM 접수(study_provenance, 미판독 포함) · 판독/TAT=리포트 생성~서명 · 완료=전자서명. 기간 {data.period_days}일 · 추이 {data.trend_months}개월
          </p>
        </>
      )}
    </div>
  );
}
