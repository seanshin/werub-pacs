'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { apiFetch, getUser, login } from '@/lib/api';
import { formatDate, formatPatientName, ModalityBadge } from '@/lib/format';
import ViewerButton from '@/components/ViewerButton';

type DashboardData = {
  date: string;
  pacs: { total_patients: number; total_studies: number; total_instances: number; disk_size_mb: number };
  worklist_today: { total: number; by_status: Record<string, number>; by_modality: Record<string, number> };
  reading: { pending: number; completed_today: number; urgent: number; total_reports: number };
  ai: { jobs_today: number; completed: number; critical_findings: number };
};

type ReadingItem = {
  patient_name: string; patient_id: string; modality: string;
  study_description: string; study_date: string; read_status: string;
  urgency: string; viewer_url: string; study_instance_uid: string;
  sla_minutes: number | null; sla_level: string | null;
};

type SLAStats = { total: number; resolved: number; unresolved: number; avg_resolution_minutes: number };
type RetakeStats = { total: number; pending: number; by_status: Record<string, number> };

function LoginForm({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try { await login(username, password); onLogin(); } catch (err: any) { setError(err.message); }
  };
  const setCredentials = (u: string, p: string) => { setUsername(u); setPassword(p); };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-slate-100 flex items-center justify-center">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-3 mb-2">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center shadow-lg">
              <span className="text-white text-xl font-bold">W</span>
            </div>
            <div className="text-left">
              <h1 className="text-2xl font-bold text-gray-900">WeRU.B PACS</h1>
              <p className="text-sm text-gray-500">Medical Imaging System</p>
            </div>
          </div>
        </div>
        <form onSubmit={handleSubmit} className="bg-white p-8 rounded-2xl border shadow-lg space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">사용자명</label>
            <input type="text" value={username} onChange={e => setUsername(e.target.value)}
              className="w-full border rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none" placeholder="username" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">비밀번호</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)}
              className="w-full border rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none" placeholder="password" />
          </div>
          {error && <p className="text-red-600 text-sm bg-red-50 p-2 rounded">{error}</p>}
          <button type="submit" className="w-full bg-blue-600 text-white py-2.5 rounded-lg font-semibold hover:bg-blue-700 transition shadow">로그인</button>
        </form>
        {/* 데모/파일럿 계정 힌트 — 사용자명 클릭 시 자동 입력 (비밀번호는 별도 입력) */}
        <div className="mt-4 bg-white/70 border rounded-xl p-4 text-sm text-gray-600">
          <p className="font-semibold text-gray-700 mb-2">테스트 계정 (데모)</p>
          <div className="space-y-1">
            {[
              { label: '관리자', u: 'admin', p: '' },
              { label: '영상의학과 전문의', u: 'dr.kim', p: '' },
              { label: '방사선사', u: 'tech.park', p: '' },
              { label: '주치의 (내과)', u: 'dr.lee', p: '' },
              { label: '연구자', u: 'res.choi', p: '' },
            ].map(a => (
              <button key={a.u} type="button" onClick={() => setCredentials(a.u, a.p)}
                className="w-full flex justify-between hover:bg-blue-50 rounded-lg px-3 py-1.5 transition">
                <span>{a.label}</span><span className="font-mono text-xs text-gray-400">{a.u}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [user, setUser] = useState<{ username: string; role: string } | null>(null);
  const [data, setData] = useState<DashboardData | null>(null);
  const [queue, setQueue] = useState<ReadingItem[]>([]);
  const [slaStats, setSlaStats] = useState<SLAStats | null>(null);
  const [retakeStats, setRetakeStats] = useState<RetakeStats | null>(null);
  const [hisCount, setHisCount] = useState(0);
  const [dicomIssues, setDicomIssues] = useState<{ total: number; by_severity: Record<string, number>; auto_fix_rate: number } | null>(null);
  const [provStats, setProvStats] = useState<{ total: number; by_origin: Record<string, { count: number; label: string }> } | null>(null);
  const [uploadStats, setUploadStats] = useState<{ by_status: Record<string, number> } | null>(null);
  const [worklistStats, setWorklistStats] = useState<{ total: number; scheduled?: number; in_progress?: number; completed?: number } | null>(null);
  const [loading, setLoading] = useState(true);

  const loadData = async () => {
    try {
      const [d, q] = await Promise.all([
        apiFetch<DashboardData>('/api/v1/dashboard/today'),
        apiFetch<{ queue: ReadingItem[] }>('/api/v1/dashboard/reading-queue'),
      ]);
      setData(d); setQueue(q.queue);

      // Load supplementary stats (non-blocking)
      apiFetch<SLAStats>('/api/v1/sla/stats?days=7').then(setSlaStats).catch(() => {});
      apiFetch<RetakeStats>('/api/v1/retake/stats').then(setRetakeStats).catch(() => {});
      apiFetch<{ total: number }>('/api/v1/his/requests?limit=1').then(d => setHisCount(d.total)).catch(() => {});
      apiFetch<any>('/api/v1/dicom-issues/statistics?days=30').then(setDicomIssues).catch(() => {});
      apiFetch<any>('/api/v1/provenance/statistics').then(setProvStats).catch(() => {});
      apiFetch<any>('/api/v1/upload-queue/stats').then(setUploadStats).catch(() => {});
      apiFetch<any>('/api/v1/worklist/stats').then(setWorklistStats).catch(() => {});
    } catch { setUser(null); }
    setLoading(false);
  };

  useEffect(() => {
    // SSO: auto-login via token query parameter from HIS
    const params = new URLSearchParams(window.location.search);
    const ssoToken = params.get('sso_token') || params.get('token');
    if (ssoToken) {
      localStorage.setItem('pacs_token', ssoToken);
      // Remove token from URL for security
      params.delete('sso_token'); params.delete('token');
      const clean = params.toString();
      window.history.replaceState({}, '', window.location.pathname + (clean ? '?' + clean : ''));
    }

    const u = getUser(); setUser(u);
    if (u) loadData(); else setLoading(false);
    const interval = setInterval(() => { if (getUser()) loadData(); }, 30000);
    return () => clearInterval(interval);
  }, []);

  if (!loading && !user) return <LoginForm onLogin={() => window.location.reload()} />;
  if (loading || !data) return (
    <div className="flex items-center justify-center h-[60vh]">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p className="text-sm text-slate-500">대시보드 로딩 중...</p>
      </div>
    </div>
  );

  const urgentCount = data.reading.urgent;
  const pendingCount = data.reading.pending;
  const slaWarnings = queue.filter(q => q.sla_level === 'warning').length;
  const slaCriticals = queue.filter(q => q.sla_level === 'critical').length;

  return (
    <div className="space-y-6">
      {/* Urgent Alert Banner */}
      {urgentCount > 0 && (
        <div className="bg-gradient-to-r from-red-600 to-red-500 text-white px-5 py-4 rounded-2xl flex items-center justify-between shadow-lg">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 bg-white/20 rounded-xl flex items-center justify-center">
              <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" /></svg>
            </div>
            <div>
              <p className="font-bold text-lg">긴급 판독 {urgentCount}건</p>
              <p className="text-red-100 text-sm">즉시 확인이 필요합니다</p>
            </div>
          </div>
          <Link href="/reading" className="bg-white text-red-600 px-5 py-2.5 rounded-xl font-bold hover:bg-red-50 transition shadow">
            판독 시작 →
          </Link>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">대시보드</h1>
          <p className="text-sm text-slate-500 mt-0.5">{data.date} · {user?.username} ({user?.role})</p>
        </div>
        <div className="flex gap-2">
          <Link href="/reading" className="bg-blue-600 text-white px-5 py-2.5 rounded-xl font-semibold hover:bg-blue-700 transition shadow-sm text-sm">
            판독 시작
          </Link>
          <a href="/werub-viewer/" target="_blank" className="bg-white text-slate-700 px-4 py-2.5 rounded-xl font-medium hover:bg-slate-50 transition text-sm border">
            뷰어 열기
          </a>
        </div>
      </div>

      {/* Primary Stats Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Link href="/reading" className={`rounded-2xl p-5 border-2 transition hover:shadow-md ${pendingCount > 0 ? 'bg-amber-50 border-amber-200' : 'bg-white border-slate-100'}`}>
          <div className="flex items-center justify-between">
            <p className="text-sm text-slate-500 font-medium">판독 대기</p>
            <svg className="w-5 h-5 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
          </div>
          <p className={`text-4xl font-bold mt-2 ${pendingCount > 0 ? 'text-amber-600' : 'text-slate-300'}`}>{pendingCount}</p>
          {slaCriticals > 0 && <p className="text-xs text-red-600 font-semibold mt-1 animate-pulse">SLA 위반 {slaCriticals}건</p>}
          {slaWarnings > 0 && !slaCriticals && <p className="text-xs text-amber-600 font-semibold mt-1">SLA 경고 {slaWarnings}건</p>}
        </Link>

        <Link href="/reading" className="bg-white rounded-2xl p-5 border transition hover:shadow-md">
          <div className="flex items-center justify-between">
            <p className="text-sm text-slate-500 font-medium">오늘 완료</p>
            <svg className="w-5 h-5 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
          </div>
          <p className="text-4xl font-bold mt-2 text-emerald-600">{data.reading.completed_today}</p>
          <p className="text-xs text-slate-400 mt-1">전체 {data.reading.total_reports}건</p>
        </Link>

        <div className="bg-white rounded-2xl p-5 border">
          <div className="flex items-center justify-between">
            <p className="text-sm text-slate-500 font-medium">오늘 워크리스트</p>
            <svg className="w-5 h-5 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" /></svg>
          </div>
          <p className="text-4xl font-bold mt-2 text-slate-800">{data.worklist_today.total}</p>
          <div className="flex gap-1.5 mt-1 flex-wrap">
            {Object.entries(data.worklist_today.by_modality).slice(0, 4).map(([mod, cnt]) => (
              <span key={mod} className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded font-medium">{mod} {cnt as number}</span>
            ))}
          </div>
        </div>

        <div className="bg-white rounded-2xl p-5 border">
          <div className="flex items-center justify-between">
            <p className="text-sm text-slate-500 font-medium">AI 분석</p>
            <svg className="w-5 h-5 text-violet-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" /></svg>
          </div>
          <p className="text-4xl font-bold mt-2 text-violet-600">{data.ai.jobs_today}</p>
          <p className="text-xs text-slate-400 mt-1">완료 {data.ai.completed} · 긴급소견 <span className={data.ai.critical_findings > 0 ? 'text-red-600 font-semibold' : ''}>{data.ai.critical_findings}</span></p>
        </div>
      </div>

      {/* Secondary Stats Row — Worklist(MWL/MPPS), SLA, Retake, HIS, Storage */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Link href="/worklist" className="bg-white rounded-xl p-4 border hover:shadow-sm transition">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm">🗂️</span>
            <span className="text-xs font-semibold text-slate-500">워크리스트 (MWL)</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-800">{worklistStats?.scheduled || 0}</span>
            <span className="text-xs text-slate-400">예약</span>
          </div>
          {(worklistStats?.in_progress || 0) > 0 && (
            <p className="text-xs text-blue-600 font-semibold mt-1">촬영중 {worklistStats?.in_progress} (MPPS)</p>
          )}
        </Link>

        <Link href="/sla" className="bg-white rounded-xl p-4 border hover:shadow-sm transition">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm">⏱</span>
            <span className="text-xs font-semibold text-slate-500">SLA (7일)</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-800">{slaStats?.total || 0}</span>
            <span className="text-xs text-slate-400">에스컬레이션</span>
          </div>
          {(slaStats?.unresolved || 0) > 0 && (
            <p className="text-xs text-amber-600 font-semibold mt-1">미해결 {slaStats?.unresolved}</p>
          )}
        </Link>

        <Link href="/retake" className="bg-white rounded-xl p-4 border hover:shadow-sm transition">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm">🔄</span>
            <span className="text-xs font-semibold text-slate-500">재촬영</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-800">{retakeStats?.total || 0}</span>
            <span className="text-xs text-slate-400">요청</span>
          </div>
          {(retakeStats?.pending || 0) > 0 && (
            <p className="text-xs text-amber-600 font-semibold mt-1">대기 {retakeStats?.pending}</p>
          )}
        </Link>

        <Link href="/his" className="bg-white rounded-xl p-4 border hover:shadow-sm transition">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm">🏥</span>
            <span className="text-xs font-semibold text-slate-500">HIS 연동</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-800">{hisCount}</span>
            <span className="text-xs text-slate-400">요청</span>
          </div>
        </Link>

        <div className="bg-white rounded-xl p-4 border">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm">💾</span>
            <span className="text-xs font-semibold text-slate-500">스토리지</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-800">
              {data.pacs.disk_size_mb >= 1024 ? `${(data.pacs.disk_size_mb / 1024).toFixed(1)}` : data.pacs.disk_size_mb}
            </span>
            <span className="text-xs text-slate-400">{data.pacs.disk_size_mb >= 1024 ? 'GB' : 'MB'}</span>
          </div>
          <p className="text-xs text-slate-400 mt-1">{data.pacs.total_patients}명 · {data.pacs.total_studies}검사 · {data.pacs.total_instances.toLocaleString()}영상</p>
        </div>
      </div>

      {/* DICOM Quality & Ingestion Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Link href="/dicom-issues" className="bg-white rounded-xl p-4 border hover:shadow-sm transition">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm">⚠</span>
            <span className="text-xs font-semibold text-slate-500">DICOM 이슈</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className={`text-2xl font-bold ${(dicomIssues?.by_severity?.critical || 0) > 0 ? 'text-red-600' : 'text-slate-800'}`}>
              {dicomIssues?.total || 0}
            </span>
            <span className="text-xs text-slate-400">건</span>
          </div>
          <div className="flex gap-1 mt-1">
            {(dicomIssues?.by_severity?.critical || 0) > 0 && <span className="text-[9px] px-1 py-0.5 rounded bg-red-100 text-red-700 font-bold">C:{dicomIssues?.by_severity.critical}</span>}
            {(dicomIssues?.by_severity?.error || 0) > 0 && <span className="text-[9px] px-1 py-0.5 rounded bg-orange-100 text-orange-700 font-bold">E:{dicomIssues?.by_severity.error}</span>}
            {(dicomIssues?.by_severity?.warning || 0) > 0 && <span className="text-[9px] px-1 py-0.5 rounded bg-yellow-100 text-yellow-700 font-bold">W:{dicomIssues?.by_severity.warning}</span>}
          </div>
        </Link>

        <div className="bg-white rounded-xl p-4 border">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm">🔧</span>
            <span className="text-xs font-semibold text-slate-500">자동수정율</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className={`text-2xl font-bold ${(dicomIssues?.auto_fix_rate || 0) >= 80 ? 'text-emerald-600' : 'text-amber-600'}`}>
              {dicomIssues?.auto_fix_rate || 0}%
            </span>
          </div>
          <div className="w-full bg-slate-100 rounded-full h-1.5 mt-2">
            <div className="bg-emerald-500 h-1.5 rounded-full" style={{ width: `${Math.min(dicomIssues?.auto_fix_rate || 0, 100)}%` }} />
          </div>
        </div>

        <div className="bg-white rounded-xl p-4 border">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm">📊</span>
            <span className="text-xs font-semibold text-slate-500">영상 출처</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-800">{provStats?.total || 0}</span>
            <span className="text-xs text-slate-400">추적</span>
          </div>
          <div className="flex gap-1 mt-1 flex-wrap">
            {provStats?.by_origin && Object.entries(provStats.by_origin).slice(0, 3).map(([k, v]: [string, any]) => (
              <span key={k} className="text-[9px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded font-medium">{v.label} {v.count}</span>
            ))}
          </div>
        </div>

        <Link href="/upload-queue" className="bg-white rounded-xl p-4 border hover:shadow-sm transition">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm">📤</span>
            <span className="text-xs font-semibold text-slate-500">업로드 큐</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className={`text-2xl font-bold ${(uploadStats?.by_status?.pending || 0) > 0 ? 'text-amber-600' : 'text-slate-800'}`}>
              {uploadStats?.by_status?.pending || 0}
            </span>
            <span className="text-xs text-slate-400">대기</span>
          </div>
          {(uploadStats?.by_status?.approved || 0) > 0 && (
            <p className="text-xs text-slate-400 mt-1">승인 {uploadStats?.by_status.approved}건</p>
          )}
        </Link>
      </div>

      {/* Reading Queue */}
      <div className="bg-white rounded-2xl border shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b flex justify-between items-center">
          <div>
            <h3 className="font-bold text-slate-900">판독 대기 목록</h3>
            <p className="text-xs text-slate-400 mt-0.5">30초마다 자동 갱신</p>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-slate-500">{queue.length}건</span>
            <Link href="/reading" className="text-sm text-blue-600 font-medium hover:underline">전체 보기 →</Link>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50/80">
              <tr className="text-xs text-slate-400 uppercase tracking-wider">
                <th className="px-3 py-3 text-center w-10"></th>
                <th className="px-4 py-3 text-left">환자</th>
                <th className="px-4 py-3 text-left w-20">모달리티</th>
                <th className="px-4 py-3 text-left">검사설명</th>
                <th className="px-4 py-3 text-left whitespace-nowrap">검사일</th>
                <th className="px-4 py-3 text-center">SLA</th>
                <th className="px-4 py-3 text-right w-36">액션</th>
              </tr>
            </thead>
            <tbody>
              {queue.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-16 text-center">
                  <svg className="w-12 h-12 text-slate-200 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                  <p className="text-slate-400">판독 대기 건이 없습니다</p>
                </td></tr>
              )}
              {queue.slice(0, 15).map((item, i) => (
                <tr key={i} className={`border-t hover:bg-blue-50/50 transition ${item.urgency === 'urgent' ? 'bg-red-50/50' : ''}`}>
                  <td className="px-5 py-3 text-center">
                    {item.urgency === 'urgent' ? (
                      <span className="inline-block w-3 h-3 rounded-full bg-red-500 animate-pulse" title="긴급" />
                    ) : item.sla_level === 'critical' ? (
                      <span className="inline-block w-3 h-3 rounded-full bg-red-400 animate-pulse" title="SLA 위험" />
                    ) : item.sla_level === 'warning' ? (
                      <span className="inline-block w-3 h-3 rounded-full bg-amber-400" title="SLA 경고" />
                    ) : (
                      <span className="inline-block w-3 h-3 rounded-full bg-blue-300" title="대기" />
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <p className="font-medium text-slate-900">{formatPatientName(item.patient_name)}</p>
                    <p className="text-xs text-slate-400">{item.patient_id || '-'}</p>
                  </td>
                  <td className="px-4 py-3"><ModalityBadge modality={item.modality} /></td>
                  <td className="px-4 py-3 text-slate-600">{item.study_description || '-'}</td>
                  <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">{formatDate(item.study_date)}</td>
                  <td className="px-4 py-3 text-center">
                    {item.sla_minutes != null && item.sla_level && item.sla_level !== 'normal' ? (
                      <span className={`text-xs font-bold ${item.sla_level === 'critical' ? 'text-red-600 animate-pulse' : 'text-amber-600'}`}>
                        {item.sla_minutes}분
                      </span>
                    ) : (
                      <span className="text-xs text-slate-300">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1.5 justify-end">
                      <ViewerButton url={`/werub-viewer/viewer?StudyInstanceUIDs=${item.study_instance_uid || ''}`} label="W" size="sm" modality={item.modality} />
                      <Link href={`/reading/view?study=${item.study_instance_uid || ''}`}
                        className="bg-slate-800 text-white px-3 py-1 rounded text-xs font-medium hover:bg-slate-900 transition">
                        판독
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {queue.length > 15 && (
          <div className="px-5 py-3 border-t text-center bg-slate-50/50">
            <Link href="/reading" className="text-sm text-blue-600 font-medium hover:underline">
              나머지 {queue.length - 15}건 더 보기 →
            </Link>
          </div>
        )}
      </div>

      {/* Version & System Info */}
      <div className="mt-8 bg-white rounded-2xl border border-slate-100 shadow-sm p-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 bg-gradient-to-br from-blue-600 to-indigo-700 rounded-xl flex items-center justify-center shadow-sm">
              <span className="text-white font-extrabold text-sm">W</span>
            </div>
            <div>
              <h3 className="font-bold text-slate-900">WeRU.B PACS</h3>
              <p className="text-xs text-slate-400">Open Medical Imaging Platform</p>
            </div>
          </div>
          <div className="text-right">
            <span className="inline-block px-2.5 py-1 bg-blue-50 text-blue-700 text-xs font-bold rounded-lg">v12.9</span>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <div className="bg-slate-50 rounded-xl p-3">
            <div className="text-slate-400 mb-0.5">DICOM Server</div>
            <div className="font-semibold text-slate-700">Orthanc 1.12.11</div>
          </div>
          <div className="bg-slate-50 rounded-xl p-3">
            <div className="text-slate-400 mb-0.5">Viewer</div>
            <div className="font-semibold text-slate-700">OHIF v3.12 (WeRU.B)</div>
          </div>
          <div className="bg-slate-50 rounded-xl p-3">
            <div className="text-slate-400 mb-0.5">Backend</div>
            <div className="font-semibold text-slate-700">FastAPI / Python 3.12</div>
          </div>
          <div className="bg-slate-50 rounded-xl p-3">
            <div className="text-slate-400 mb-0.5">Database</div>
            <div className="font-semibold text-slate-700">PostgreSQL 16</div>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <div className="bg-slate-50 rounded-xl p-3">
            <div className="text-slate-400 mb-0.5">통신 보안</div>
            <div className="font-semibold text-slate-700">TLS 1.3 / HTTPS</div>
          </div>
          <div className="bg-slate-50 rounded-xl p-3">
            <div className="text-slate-400 mb-0.5">인증</div>
            <div className="font-semibold text-slate-700">JWT + RBAC (6 Roles)</div>
          </div>
          <div className="bg-slate-50 rounded-xl p-3">
            <div className="text-slate-400 mb-0.5">암호화</div>
            <div className="font-semibold text-slate-700">pgcrypto / PBKDF2</div>
          </div>
          <div className="bg-slate-50 rounded-xl p-3">
            <div className="text-slate-400 mb-0.5">감사</div>
            <div className="font-semibold text-slate-700">Audit Log (전수 기록)</div>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <div className="bg-slate-50 rounded-xl p-3">
            <div className="text-slate-400 mb-0.5">DICOM 규격</div>
            <div className="font-semibold text-slate-700">DICOM 3.0 / DICOMweb</div>
          </div>
          <div className="bg-slate-50 rounded-xl p-3">
            <div className="text-slate-400 mb-0.5">프로토콜</div>
            <div className="font-semibold text-slate-700">DIMSE (C-STORE/FIND/MOVE)</div>
          </div>
          <div className="bg-slate-50 rounded-xl p-3">
            <div className="text-slate-400 mb-0.5">법규 준수</div>
            <div className="font-semibold text-slate-700">개인정보보호법 / 의료법</div>
          </div>
          <div className="bg-slate-50 rounded-xl p-3">
            <div className="text-slate-400 mb-0.5">데이터 보존</div>
            <div className="font-semibold text-slate-700">5년 (의료법 시행규칙)</div>
          </div>
        </div>
        <div className="mt-3 pt-3 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-400">
          <span>WeRU.B Inc. / OpenPACS Project</span>
          <span>Updated 2026-06</span>
        </div>
      </div>
    </div>
  );
}
