'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch, getUser } from '@/lib/api';

type TATData = {
  overall: { total_signed: number; avg_min: number; median_min: number; max_min: number; min_min: number; p95_min: number };
  by_reader: { reader: string; count: number; avg_min: number; median_min: number; max_min: number }[];
  by_modality: { modality: string; count: number; avg_min: number }[];
  hourly_distribution: { hour: number; count: number }[];
  daily_trend: { date: string; count: number; avg_min: number }[];
  period_days: number;
};

export default function ReadingStatsPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [data, setData] = useState<TATData | null>(null);
  const [days, setDays] = useState(30);

  useEffect(() => {
    const u = getUser();
    if (!u || !['admin', 'radiologist'].includes(u.role)) { router.replace('/'); return; }
    setUser(u);
  }, []);

  useEffect(() => { if (user) load(); }, [user, days]);

  const load = () => {
    apiFetch<TATData>(`/api/v1/reports/statistics/tat?days=${days}`).then(setData).catch(() => {});
  };

  if (!user || !data) return <div className="text-center py-20 text-slate-400">로딩 중...</div>;

  const o = data.overall;
  const maxHourly = Math.max(...data.hourly_distribution.map(h => h.count), 1);
  const maxDaily = Math.max(...data.daily_trend.map(d => d.avg_min || 0), 1);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">판독 시간 분석</h1>
          <p className="text-sm text-slate-500 mt-1">Turn Around Time (TAT) 상세 분석</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Link href="/reading/stats"
              className="px-4 py-2 text-sm rounded-xl border bg-blue-600 text-white border-blue-600">판독 시간 (TAT)</Link>
            <Link href="/reading/residents"
              className="px-4 py-2 text-sm rounded-xl border bg-white text-slate-600 hover:bg-slate-50">레지던트 성과</Link>
          </div>
          <select value={days} onChange={e => setDays(Number(e.target.value))}
            className="border rounded-xl px-3 py-2 text-sm">
            <option value={7}>최근 7일</option>
            <option value={30}>최근 30일</option>
            <option value={90}>최근 90일</option>
          </select>
        </div>
      </div>

      {/* Overall TAT Summary */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        {[
          { label: '판독 완료', value: o.total_signed, unit: '건', color: 'text-blue-600' },
          { label: '평균 TAT', value: o.avg_min, unit: '분', color: 'text-slate-800' },
          { label: '중앙값', value: o.median_min, unit: '분', color: 'text-emerald-600' },
          { label: '최소', value: o.min_min, unit: '분', color: 'text-slate-500' },
          { label: 'P95', value: o.p95_min, unit: '분', color: 'text-amber-600' },
          { label: '최대', value: o.max_min, unit: '분', color: 'text-red-600' },
        ].map(s => (
          <div key={s.label} className="bg-white rounded-xl border p-4 text-center">
            <div className="text-xs text-slate-400">{s.label}</div>
            <div className={`text-2xl font-bold mt-1 ${s.color}`}>{s.value ?? '-'}</div>
            <div className="text-[10px] text-slate-400">{s.unit}</div>
          </div>
        ))}
      </div>

      {/* By Reader */}
      <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b"><h2 className="font-semibold">판독의별 TAT</h2></div>
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              <th className="px-5 py-3 text-left">판독의</th>
              <th className="px-5 py-3 text-right">건수</th>
              <th className="px-5 py-3 text-right">평균 (분)</th>
              <th className="px-5 py-3 text-right">중앙값 (분)</th>
              <th className="px-5 py-3 text-right">최대 (분)</th>
              <th className="px-5 py-3 text-left">분포</th>
            </tr>
          </thead>
          <tbody>
            {data.by_reader.length === 0 ? (
              <tr><td colSpan={6} className="text-center py-8 text-slate-400">데이터 없음</td></tr>
            ) : data.by_reader.map(r => (
              <tr key={r.reader} className="border-t hover:bg-slate-50">
                <td className="px-5 py-3 font-medium">{r.reader || '(미지정)'}</td>
                <td className="px-5 py-3 text-right">{r.count}</td>
                <td className="px-5 py-3 text-right font-semibold">{r.avg_min}</td>
                <td className="px-5 py-3 text-right text-slate-600">{r.median_min}</td>
                <td className="px-5 py-3 text-right text-slate-500">{r.max_min}</td>
                <td className="px-5 py-3">
                  <div className="w-32 bg-slate-100 rounded-full h-2">
                    <div className="bg-blue-500 h-2 rounded-full" style={{ width: `${Math.min(100, ((r.avg_min || 0) / (o.max_min || 1)) * 100)}%` }} />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* By Modality */}
        <div className="bg-white rounded-xl border shadow-sm p-5">
          <h2 className="font-semibold mb-4">모달리티별 평균 TAT</h2>
          {data.by_modality.length === 0 ? (
            <p className="text-slate-400 text-center py-8">데이터 없음</p>
          ) : (
            <div className="space-y-3">
              {data.by_modality.map(m => (
                <div key={m.modality} className="flex items-center gap-3">
                  <span className="w-12 text-xs font-bold text-blue-700 bg-blue-100 px-2 py-1 rounded text-center">{m.modality}</span>
                  <div className="flex-1 bg-slate-100 rounded-full h-6 relative overflow-hidden">
                    <div className="bg-blue-500 h-full rounded-full flex items-center justify-end pr-2"
                      style={{ width: `${Math.min(100, ((m.avg_min || 0) / (o.max_min || 1)) * 100)}%`, minWidth: '40px' }}>
                      <span className="text-[10px] text-white font-bold">{m.avg_min}분</span>
                    </div>
                  </div>
                  <span className="text-xs text-slate-500 w-16 text-right">{m.count}건</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Hourly Distribution */}
        <div className="bg-white rounded-xl border shadow-sm p-5">
          <h2 className="font-semibold mb-4">시간대별 판독 분포</h2>
          <div className="flex items-end gap-1 h-40">
            {Array.from({ length: 24 }, (_, h) => {
              const item = data.hourly_distribution.find(d => d.hour === h);
              const count = item?.count || 0;
              const pct = maxHourly > 0 ? (count / maxHourly) * 100 : 0;
              return (
                <div key={h} className="flex-1 flex flex-col items-center gap-1">
                  <div className="w-full flex flex-col justify-end" style={{ height: '120px' }}>
                    <div className={`w-full rounded-t ${h >= 8 && h <= 18 ? 'bg-blue-500' : 'bg-slate-300'}`}
                      style={{ height: `${Math.max(pct, 2)}%` }} title={`${h}시: ${count}건`} />
                  </div>
                  <span className="text-[8px] text-slate-400">{h}</span>
                </div>
              );
            })}
          </div>
          <div className="flex justify-between mt-2 text-[10px] text-slate-400">
            <span>0시</span><span>6시</span><span>12시</span><span>18시</span><span>24시</span>
          </div>
        </div>
      </div>

      {/* Daily Trend */}
      <div className="bg-white rounded-xl border shadow-sm p-5">
        <h2 className="font-semibold mb-4">일별 평균 TAT 추이</h2>
        {data.daily_trend.length === 0 ? (
          <p className="text-slate-400 text-center py-8">데이터 없음</p>
        ) : (
          <div className="overflow-x-auto">
            <div className="flex items-end gap-1 h-32 min-w-[600px]">
              {data.daily_trend.map(d => {
                const pct = maxDaily > 0 ? ((d.avg_min || 0) / maxDaily) * 100 : 0;
                return (
                  <div key={d.date} className="flex-1 flex flex-col items-center gap-1">
                    <span className="text-[9px] text-slate-500">{d.avg_min}분</span>
                    <div className="w-full flex flex-col justify-end" style={{ height: '80px' }}>
                      <div className="w-full bg-emerald-500 rounded-t" style={{ height: `${Math.max(pct, 3)}%` }}
                        title={`${d.date}: 평균 ${d.avg_min}분 (${d.count}건)`} />
                    </div>
                    <span className="text-[7px] text-slate-400 -rotate-45 origin-top-left whitespace-nowrap">{d.date.slice(5)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
