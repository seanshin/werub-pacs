'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch, getUser } from '@/lib/api';

type ResidentRow = {
  resident: string | null;
  preliminary_count: number;
  finalized_count: number;
  pending_count: number;
  impression_changed: number;
  findings_changed: number;
  avg_prelim_min: number | null;
  correction_rate: number | null;
  agreement_rate: number | null;
};

type ResidentStats = {
  period_days: number;
  by_resident: ResidentRow[];
  summary: {
    resident_count: number;
    preliminary_count: number;
    finalized_count: number;
    avg_correction_rate: number | null;
    avg_agreement_rate: number | null;
  };
};

function StatsTabs({ active }: { active: 'tat' | 'residents' }) {
  const tab = (href: string, label: string, key: string) => (
    <a
      href={href}
      className={`px-4 py-2 text-sm rounded-xl border ${
        active === key ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-slate-600 hover:bg-slate-50'
      }`}
    >
      {label}
    </a>
  );
  return (
    <div className="flex items-center gap-2">
      {tab('/pacs-admin/reading/stats', '판독 시간 (TAT)', 'tat')}
      {tab('/pacs-admin/reading/residents', '레지던트 성과', 'residents')}
    </div>
  );
}

function agreementColor(rate: number | null) {
  if (rate === null) return 'text-slate-400';
  if (rate >= 90) return 'text-emerald-600';
  if (rate >= 75) return 'text-amber-600';
  return 'text-red-600';
}

export default function ResidentStatsPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [data, setData] = useState<ResidentStats | null>(null);
  const [days, setDays] = useState(90);

  useEffect(() => {
    const u = getUser();
    if (!u || !['admin', 'radiologist'].includes(u.role)) {
      router.replace('/');
      return;
    }
    setUser(u);
  }, []);

  useEffect(() => {
    if (user) apiFetch<ResidentStats>(`/api/v1/reports/statistics/residents?days=${days}`).then(setData).catch(() => {});
  }, [user, days]);

  if (!user || !data) return <div className="text-center py-20 text-slate-400">로딩 중...</div>;

  const s = data.summary;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold">레지던트 성과</h1>
          <p className="text-sm text-slate-500 mt-1">예비판독 정확도 · 전문의 수정률 분석 (교육용)</p>
        </div>
        <div className="flex items-center gap-3">
          <StatsTabs active="residents" />
          <select value={days} onChange={e => setDays(Number(e.target.value))}
            className="border rounded-xl px-3 py-2 text-sm">
            <option value={30}>최근 30일</option>
            <option value={90}>최근 90일</option>
            <option value={180}>최근 180일</option>
            <option value={365}>최근 1년</option>
          </select>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {[
          { label: '레지던트', value: s.resident_count, unit: '명', color: 'text-blue-600' },
          { label: '예비판독', value: s.preliminary_count, unit: '건', color: 'text-slate-800' },
          { label: '최종확정', value: s.finalized_count, unit: '건', color: 'text-emerald-600' },
          { label: '평균 일치율', value: s.avg_agreement_rate, unit: '%', color: agreementColor(s.avg_agreement_rate) },
          { label: '평균 수정률', value: s.avg_correction_rate, unit: '%', color: 'text-amber-600' },
        ].map(c => (
          <div key={c.label} className="bg-white rounded-xl border p-4 text-center">
            <div className="text-xs text-slate-400">{c.label}</div>
            <div className={`text-2xl font-bold mt-1 ${c.color}`}>{c.value ?? '-'}</div>
            <div className="text-[10px] text-slate-400">{c.unit}</div>
          </div>
        ))}
      </div>

      {/* Per-resident table */}
      <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b">
          <h2 className="font-semibold">레지던트별 예비판독 성과</h2>
          <p className="text-xs text-slate-400 mt-0.5">
            수정률 = 전문의 최종본에서 결론(impression)이 변경된 비율 · 일치율 = 변경되지 않은 비율
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="px-5 py-3 text-left">레지던트</th>
                <th className="px-4 py-3 text-right">예비판독</th>
                <th className="px-4 py-3 text-right">최종확정</th>
                <th className="px-4 py-3 text-right">대기</th>
                <th className="px-4 py-3 text-right">결론 수정</th>
                <th className="px-4 py-3 text-right">소견 수정</th>
                <th className="px-4 py-3 text-right">일치율</th>
                <th className="px-5 py-3 text-left">일치도</th>
                <th className="px-4 py-3 text-right">평균 소요</th>
              </tr>
            </thead>
            <tbody>
              {data.by_resident.length === 0 ? (
                <tr><td colSpan={9} className="text-center py-10 text-slate-400">예비판독 데이터 없음</td></tr>
              ) : data.by_resident.map(r => (
                <tr key={r.resident || '미지정'} className="border-t hover:bg-slate-50">
                  <td className="px-5 py-3 font-medium">{r.resident || '(미지정)'}</td>
                  <td className="px-4 py-3 text-right font-semibold">{r.preliminary_count}</td>
                  <td className="px-4 py-3 text-right text-slate-600">{r.finalized_count}</td>
                  <td className="px-4 py-3 text-right text-slate-400">{r.pending_count}</td>
                  <td className="px-4 py-3 text-right text-amber-700">{r.impression_changed}</td>
                  <td className="px-4 py-3 text-right text-slate-500">{r.findings_changed}</td>
                  <td className={`px-4 py-3 text-right font-bold ${agreementColor(r.agreement_rate)}`}>
                    {r.agreement_rate ?? '-'}{r.agreement_rate !== null ? '%' : ''}
                  </td>
                  <td className="px-5 py-3">
                    <div className="w-28 bg-slate-100 rounded-full h-2">
                      <div className={`h-2 rounded-full ${(r.agreement_rate ?? 0) >= 90 ? 'bg-emerald-500' : (r.agreement_rate ?? 0) >= 75 ? 'bg-amber-500' : 'bg-red-500'}`}
                        style={{ width: `${Math.min(100, Math.max(0, r.agreement_rate ?? 0))}%` }} />
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right text-slate-500">{r.avg_prelim_min != null ? `${r.avg_prelim_min}분` : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p className="text-xs text-slate-400">
        ※ 수정률은 텍스트 차이 기반 근사치입니다. 경미한 표현 수정도 변경으로 집계될 수 있습니다.
      </p>
    </div>
  );
}
