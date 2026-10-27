'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch, getUser } from '@/lib/api';

type CaseSummary = {
  id: string;
  title: string;
  modality: string | null;
  organ: string | null;
  difficulty: string;
  is_published: boolean;
  publish_status: string;
  view_count: number;
  tags: string[];
  created_at: string | null;
};

type CaseList = { total: number; page: number; page_size: number; items: CaseSummary[] };
type CaseDetail = CaseSummary & {
  study_instance_uid: string;
  summary: string | null;
  diagnosis: string | null;
  patient_age: string | null;
  patient_sex: string | null;
  created_by_name: string | null;
  study_available?: boolean;
  submitted_at?: string | null;
  reviewed_by_name?: string | null;
  reviewed_at?: string | null;
  review_comment?: string | null;
};

type QuizView = {
  id: string; modality: string | null; difficulty: string;
  patient_age: string | null; patient_sex: string | null;
  study_instance_uid: string; study_available: boolean;
};
type QuizReveal = {
  attempt_id: string; submitted_answer: string;
  title: string; diagnosis: string | null; summary: string | null;
  organ: string | null; tags: string[];
};
type Breakdown = { key: string | null; attempts: number; assessed: number; correct: number; accuracy: number | null };
type RecentAttempt = {
  attempt_id: string; case_id: string; case_title: string; modality: string | null;
  difficulty: string; self_assessment: string | null; created_at: string | null;
};
type Progress = {
  user_id: string; total_attempts: number; assessed: number;
  correct: number; partial: number; incorrect: number; accuracy: number | null;
  by_modality: Breakdown[]; by_difficulty: Breakdown[]; recent: RecentAttempt[];
};

const DIFF: Record<string, { label: string; cls: string }> = {
  beginner: { label: '입문', cls: 'bg-emerald-100 text-emerald-700' },
  intermediate: { label: '중급', cls: 'bg-amber-100 text-amber-700' },
  advanced: { label: '고급', cls: 'bg-red-100 text-red-700' },
};

const ASSESS: Record<string, { label: string; cls: string }> = {
  correct: { label: '맞음', cls: 'text-emerald-600' },
  partial: { label: '부분', cls: 'text-amber-600' },
  incorrect: { label: '틀림', cls: 'text-red-500' },
};

const STATUS: Record<string, { label: string; cls: string }> = {
  draft: { label: '초안', cls: 'bg-slate-100 text-slate-500' },
  pending: { label: '검토 대기', cls: 'bg-blue-100 text-blue-700' },
  published: { label: '게시됨', cls: 'bg-emerald-100 text-emerald-700' },
  rejected: { label: '반려', cls: 'bg-red-100 text-red-600' },
};

const blankForm = {
  study_instance_uid: '', title: '', summary: '', diagnosis: '', organ: '',
  difficulty: 'intermediate', tags: '', is_published: false,
};

export default function TeachingPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [data, setData] = useState<CaseList | null>(null);
  const [filters, setFilters] = useState({ q: '', modality: '', difficulty: '', tag: '', status: '' });
  const [page, setPage] = useState(1);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState<any>(blankForm);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [quiz, setQuiz] = useState<QuizView | null>(null);
  const [quizAnswer, setQuizAnswer] = useState('');
  const [quizReveal, setQuizReveal] = useState<QuizReveal | null>(null);
  const [quizStart, setQuizStart] = useState(0);
  const [progress, setProgress] = useState<Progress | null>(null);

  const canWrite = !!user && ['admin', 'radiologist', 'resident'].includes(user.role);
  const isAdmin = user?.role === 'admin';
  const isAttending = !!user && ['admin', 'radiologist'].includes(user.role); // 게시 승인 권한

  useEffect(() => {
    const u = getUser();
    if (!u || !['admin', 'radiologist', 'resident'].includes(u.role)) { router.replace('/'); return; }
    setUser(u);
  }, []);

  const load = useCallback(() => {
    const p = new URLSearchParams();
    if (filters.q) p.set('q', filters.q);
    if (filters.modality) p.set('modality', filters.modality);
    if (filters.difficulty) p.set('difficulty', filters.difficulty);
    if (filters.tag) p.set('tag', filters.tag);
    if (filters.status) p.set('status', filters.status);
    p.set('page', String(page));
    apiFetch<CaseList>(`/api/v1/teaching/cases?${p.toString()}`).then(setData).catch(() => {});
  }, [filters, page]);

  useEffect(() => { if (user) load(); }, [user, load]);

  const openNew = () => { setEditId(null); setForm(blankForm); setError(''); setShowForm(true); };
  const openEdit = async (id: string) => {
    try {
      const d = await apiFetch<CaseDetail>(`/api/v1/teaching/cases/${id}`);
      setEditId(id);
      setForm({
        study_instance_uid: d.study_instance_uid, title: d.title, summary: d.summary || '',
        diagnosis: d.diagnosis || '', organ: d.organ || '', difficulty: d.difficulty,
        tags: (d.tags || []).join(', '), is_published: d.is_published,
      });
      setError(''); setShowForm(true);
    } catch { }
  };

  const openDetail = async (id: string) => {
    try { setDetail(await apiFetch<CaseDetail>(`/api/v1/teaching/cases/${id}`)); } catch { }
  };

  const submit = async () => {
    if (!form.study_instance_uid || !form.title) { setError('Study UID와 제목은 필수입니다.'); return; }
    setBusy(true); setError('');
    const tags = String(form.tags || '').split(',').map((t: string) => t.trim()).filter(Boolean);
    const body: any = {
      title: form.title, summary: form.summary || null, diagnosis: form.diagnosis || null,
      organ: form.organ || null, difficulty: form.difficulty, tags, is_published: form.is_published,
    };
    try {
      if (editId) {
        await apiFetch(`/api/v1/teaching/cases/${editId}`, { method: 'PUT', body: JSON.stringify(body) });
      } else {
        body.study_instance_uid = form.study_instance_uid;
        await apiFetch('/api/v1/teaching/cases', { method: 'POST', body: JSON.stringify(body) });
      }
      setShowForm(false); load();
    } catch (e: any) {
      setError(e?.message || '저장에 실패했습니다 (Study UID를 확인하세요).');
    } finally { setBusy(false); }
  };

  const remove = async (id: string) => {
    if (!confirm('이 티칭 케이스를 삭제할까요?')) return;
    try { await apiFetch(`/api/v1/teaching/cases/${id}`, { method: 'DELETE' }); setDetail(null); load(); } catch { }
  };

  // 게시 승인 워크플로 — 전이 결과(_review_state)를 detail에 병합(재조회로 view_count 증가 회피)
  const transition = async (id: string, action: string, body?: any) => {
    try {
      const r = await apiFetch<any>(`/api/v1/teaching/cases/${id}/${action}`,
        { method: 'POST', body: body ? JSON.stringify(body) : undefined });
      setDetail(d => (d && d.id === id ? { ...d, ...r } : d));
      load();
    } catch (e: any) { alert(e?.message || '처리에 실패했습니다.'); }
  };
  const submitReview = (id: string) => transition(id, 'submit');
  const approveCase = (id: string) => transition(id, 'approve');
  const rejectCase = (id: string) => {
    const comment = prompt('반려 사유(선택):') ?? undefined;
    transition(id, 'reject', { comment });
  };
  const unpublishCase = (id: string) => { if (confirm('게시를 취소하고 초안으로 되돌릴까요?')) transition(id, 'unpublish'); };

  // 익명화 사본 export — 인증 헤더 필요한 바이너리 다운로드(blob)
  const exportAnon = async (id: string) => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('pacs_token') : null;
    try {
      const res = await fetch(`/pacs-api/api/v1/teaching/cases/${id}/export`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!res.ok) {
        const msg = await res.json().catch(() => ({}));
        alert(msg?.detail || `export에 실패했습니다 (${res.status})`);
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `teaching_${id.slice(0, 8)}_anon.zip`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (e: any) { alert(e?.message || 'export에 실패했습니다.'); }
  };

  const startQuiz = async (id: string) => {
    setDetail(null); setQuizReveal(null); setQuizAnswer(''); setError('');
    try {
      const v = await apiFetch<QuizView>(`/api/v1/teaching/cases/${id}/quiz`);
      setQuiz(v); setQuizStart(Date.now());
    } catch { }
  };

  const submitQuiz = async () => {
    if (!quiz || !quizAnswer.trim()) { setError('답안을 입력하세요.'); return; }
    setBusy(true); setError('');
    try {
      const r = await apiFetch<QuizReveal>(`/api/v1/teaching/cases/${quiz.id}/quiz/submit`, {
        method: 'POST', body: JSON.stringify({ answer: quizAnswer, time_spent_ms: Date.now() - quizStart }),
      });
      setQuizReveal(r);
    } catch (e: any) { setError(e?.message || '제출에 실패했습니다.'); }
    finally { setBusy(false); }
  };

  const assessQuiz = async (v: string) => {
    if (!quizReveal) return;
    try {
      await apiFetch(`/api/v1/teaching/quiz/attempts/${quizReveal.attempt_id}`,
        { method: 'PUT', body: JSON.stringify({ self_assessment: v }) });
    } catch { }
    setQuiz(null); setQuizReveal(null); setQuizAnswer('');
  };

  const loadProgress = async () => {
    try { setProgress(await apiFetch<Progress>('/api/v1/teaching/quiz/progress')); } catch { }
  };

  if (!user || !data) return <div className="text-center py-20 text-slate-400">로딩 중...</div>;

  const byDiff = (d: string) => data.items.filter(i => i.difficulty === d).length;
  const totalPages = Math.max(1, Math.ceil(data.total / data.page_size));

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold">📚 티칭파일 라이브러리</h1>
          <p className="text-sm text-slate-500 mt-1">판독 교육용 케이스 — 수집·태깅·검색 (참고용 · 교육 목적)</p>
        </div>
        <div className="flex gap-2">
          <button onClick={loadProgress} className="px-4 py-2 rounded-xl border text-sm font-semibold hover:bg-slate-50">
            📊 내 학습 진도
          </button>
          {canWrite && (
            <button onClick={openNew} className="px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700">
              + 케이스 등록
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: '전체(현재 페이지)', value: data.total, color: 'text-slate-800' },
          { label: '입문', value: byDiff('beginner'), color: 'text-emerald-600' },
          { label: '중급', value: byDiff('intermediate'), color: 'text-amber-600' },
          { label: '고급', value: byDiff('advanced'), color: 'text-red-600' },
        ].map(c => (
          <div key={c.label} className="bg-white rounded-xl border p-4 text-center">
            <div className="text-xs text-slate-400">{c.label}</div>
            <div className={`text-2xl font-bold mt-1 ${c.color}`}>{c.value}</div>
          </div>
        ))}
      </div>

      {/* 필터바 */}
      <div className="bg-white rounded-xl border p-3 flex flex-wrap items-end gap-2 text-sm">
        <input placeholder="제목/요약/진단 검색" value={filters.q}
          onChange={e => setFilters({ ...filters, q: e.target.value })}
          onKeyDown={e => { if (e.key === 'Enter') { setPage(1); load(); } }}
          className="border rounded-lg px-3 py-2 flex-1 min-w-[160px]" />
        <input placeholder="모달리티 (CT…)" value={filters.modality}
          onChange={e => setFilters({ ...filters, modality: e.target.value })}
          className="border rounded-lg px-3 py-2 w-32" />
        <select value={filters.difficulty} onChange={e => setFilters({ ...filters, difficulty: e.target.value })}
          className="border rounded-lg px-3 py-2">
          <option value="">난이도 전체</option>
          <option value="beginner">입문</option>
          <option value="intermediate">중급</option>
          <option value="advanced">고급</option>
        </select>
        <input placeholder="태그" value={filters.tag}
          onChange={e => setFilters({ ...filters, tag: e.target.value })}
          className="border rounded-lg px-3 py-2 w-28" />
        <select value={filters.status} onChange={e => { setFilters({ ...filters, status: e.target.value }); setPage(1); }}
          className="border rounded-lg px-3 py-2">
          <option value="">게시상태 전체</option>
          <option value="draft">초안</option>
          <option value="pending">검토 대기</option>
          <option value="published">게시됨</option>
          <option value="rejected">반려</option>
        </select>
        <button onClick={() => { setPage(1); load(); }} className="px-3 py-2 rounded-lg bg-slate-700 text-white">검색</button>
        {isAttending && (
          <button onClick={() => { setFilters({ q: '', modality: '', difficulty: '', tag: '', status: 'pending' }); setPage(1); }}
            className="px-3 py-2 rounded-lg border border-blue-300 text-blue-700">🔔 검토 대기</button>
        )}
      </div>

      {showForm && (
        <div className="bg-white rounded-xl border shadow-sm p-5 space-y-3">
          <h2 className="font-semibold">{editId ? '티칭 케이스 수정' : '티칭 케이스 등록'}</h2>
          {error && <div className="text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</div>}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
            <Field label="Study Instance UID *" value={form.study_instance_uid}
              onChange={v => setForm({ ...form, study_instance_uid: v })} disabled={!!editId} />
            <Field label="제목 *" value={form.title} onChange={v => setForm({ ...form, title: v })} />
            <Field label="장기/부위" value={form.organ} onChange={v => setForm({ ...form, organ: v })} />
            <label className="flex flex-col gap-1">
              <span className="text-slate-500">난이도</span>
              <select value={form.difficulty} onChange={e => setForm({ ...form, difficulty: e.target.value })}
                className="border rounded-lg px-3 py-2">
                <option value="beginner">입문</option>
                <option value="intermediate">중급</option>
                <option value="advanced">고급</option>
              </select>
            </label>
            <Field label="태그 (쉼표 구분)" value={form.tags} onChange={v => setForm({ ...form, tags: v })} />
            {isAttending && !editId ? (
              <label className="flex items-center gap-2 mt-6">
                <input type="checkbox" checked={form.is_published}
                  onChange={e => setForm({ ...form, is_published: e.target.checked })} />
                <span className="text-slate-600">즉시 게시(전문의 자가승인)</span>
              </label>
            ) : !editId ? (
              <div className="flex items-center mt-6 text-xs text-slate-400">초안으로 저장 → 검토 요청 후 전문의 승인 시 게시</div>
            ) : null}
          </div>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-slate-500">요약</span>
            <textarea value={form.summary} onChange={e => setForm({ ...form, summary: e.target.value })}
              rows={2} className="border rounded-lg px-3 py-2" />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-slate-500">정답 진단</span>
            <textarea value={form.diagnosis} onChange={e => setForm({ ...form, diagnosis: e.target.value })}
              rows={2} className="border rounded-lg px-3 py-2" />
          </label>
          <div className="flex gap-2">
            <button onClick={submit} disabled={busy}
              className="px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 disabled:opacity-50">
              {busy ? '저장 중…' : '저장'}
            </button>
            <button onClick={() => setShowForm(false)} className="px-4 py-2 rounded-xl border text-sm">취소</button>
          </div>
        </div>
      )}

      {/* 케이스 그리드 */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {data.items.length === 0 ? (
          <div className="col-span-full text-center py-12 text-slate-400 bg-white rounded-xl border">등록된 티칭 케이스 없음</div>
        ) : data.items.map(c => {
          const d = DIFF[c.difficulty] || DIFF.intermediate;
          return (
            <div key={c.id} className="bg-white rounded-xl border p-4 space-y-2 hover:shadow-sm">
              <div className="flex items-start justify-between gap-2">
                <button onClick={() => openDetail(c.id)} className="font-semibold text-left hover:text-blue-600 line-clamp-2">{c.title}</button>
                {c.publish_status !== 'published' && (
                  <span className={`text-[10px] rounded px-1.5 py-0.5 shrink-0 font-medium ${(STATUS[c.publish_status] || STATUS.draft).cls}`}>
                    {(STATUS[c.publish_status] || STATUS.draft).label}
                  </span>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                {c.modality && <span className="bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded font-medium">{c.modality}</span>}
                {c.organ && <span className="text-slate-500">{c.organ}</span>}
                <span className={`px-1.5 py-0.5 rounded font-medium ${d.cls}`}>{d.label}</span>
                <span className="text-slate-400">👁 {c.view_count}</span>
              </div>
              {c.tags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {c.tags.slice(0, 5).map(t => <span key={t} className="text-[10px] text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded">#{t}</span>)}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* 페이지네이션 */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 text-sm">
          <button disabled={page <= 1} onClick={() => setPage(page - 1)} className="px-3 py-1 rounded border disabled:opacity-40">이전</button>
          <span className="text-slate-500">{page} / {totalPages}</span>
          <button disabled={page >= totalPages} onClick={() => setPage(page + 1)} className="px-3 py-1 rounded border disabled:opacity-40">다음</button>
        </div>
      )}

      {/* 상세 모달 */}
      {detail && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={() => setDetail(null)}>
          <div className="bg-white rounded-2xl shadow-xl max-w-lg w-full p-6 space-y-3" onClick={e => e.stopPropagation()}>
            <div className="flex items-start justify-between">
              <h2 className="text-lg font-bold">{detail.title}</h2>
              <button onClick={() => setDetail(null)} className="text-slate-400 hover:text-slate-700">✕</button>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {detail.modality && <span className="bg-slate-100 px-2 py-0.5 rounded">{detail.modality}</span>}
              {detail.organ && <span className="text-slate-500">{detail.organ}</span>}
              <span className={`px-2 py-0.5 rounded ${(DIFF[detail.difficulty] || DIFF.intermediate).cls}`}>{(DIFF[detail.difficulty] || DIFF.intermediate).label}</span>
              <span className={`px-2 py-0.5 rounded font-medium ${(STATUS[detail.publish_status] || STATUS.draft).cls}`}>{(STATUS[detail.publish_status] || STATUS.draft).label}</span>
              {detail.patient_age && <span className="text-slate-500">{detail.patient_age} / {detail.patient_sex || '-'}</span>}
              <span className="text-slate-400">👁 {detail.view_count}</span>
            </div>
            {detail.study_available === false && (
              <div className="text-xs text-amber-600 bg-amber-50 rounded px-2 py-1">⚠ 원본 영상을 찾을 수 없습니다 (삭제/이동됨)</div>
            )}
            {detail.summary && <div><div className="text-xs text-slate-400">요약</div><p className="text-sm whitespace-pre-wrap">{detail.summary}</p></div>}
            {detail.diagnosis && <div><div className="text-xs text-slate-400">정답 진단</div><p className="text-sm whitespace-pre-wrap">{detail.diagnosis}</p></div>}
            {detail.tags.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {detail.tags.map(t => <span key={t} className="text-[11px] text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded">#{t}</span>)}
              </div>
            )}
            {detail.publish_status === 'rejected' && (
              <div className="text-xs text-red-600 bg-red-50 rounded px-2 py-1.5">
                ⛔ 반려됨{detail.reviewed_by_name ? ` (${detail.reviewed_by_name})` : ''}
                {detail.review_comment ? ` — ${detail.review_comment}` : ''}
              </div>
            )}
            {detail.publish_status === 'published' && detail.reviewed_by_name && (
              <div className="text-[11px] text-emerald-600">✔ 승인: {detail.reviewed_by_name} · {detail.reviewed_at?.slice(0, 10)}</div>
            )}
            <div className="text-[11px] text-slate-400">등록: {detail.created_by_name || '-'} · {detail.created_at?.slice(0, 10)}</div>

            {/* 게시 승인 워크플로 액션 */}
            {(() => {
              const st = detail.publish_status;
              const acts: any[] = [];
              if (canWrite && (st === 'draft' || st === 'rejected'))
                acts.push(<button key="sub" onClick={() => submitReview(detail.id)} className="px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700">📤 검토 요청</button>);
              if (isAttending && st === 'pending') {
                acts.push(<button key="app" onClick={() => approveCase(detail.id)} className="px-4 py-2 rounded-xl bg-emerald-600 text-white text-sm font-semibold hover:bg-emerald-700">✔ 승인</button>);
                acts.push(<button key="rej" onClick={() => rejectCase(detail.id)} className="px-4 py-2 rounded-xl bg-red-500 text-white text-sm font-semibold hover:bg-red-600">⛔ 반려</button>);
              }
              if (isAttending && st === 'published')
                acts.push(<button key="exp" onClick={() => exportAnon(detail.id)} className="px-4 py-2 rounded-xl bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700">🗜 익명화 export</button>);
              if (isAdmin && st === 'published')
                acts.push(<button key="unp" onClick={() => unpublishCase(detail.id)} className="px-4 py-2 rounded-xl border text-amber-600 text-sm">게시 취소</button>);
              return acts.length ? <div className="flex flex-wrap gap-2 pt-1 border-t mt-1">{acts}</div> : null;
            })()}

            <div className="flex gap-2 pt-1">
              <a href={`/werub-viewer/viewer?StudyInstanceUIDs=${detail.study_instance_uid}`} target="_blank" rel="noopener noreferrer"
                className="px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700">뷰어 열기 ↗</a>
              <button onClick={() => startQuiz(detail.id)} className="px-4 py-2 rounded-xl bg-indigo-600 text-white text-sm font-semibold hover:bg-indigo-700">🎯 퀴즈 풀기</button>
              {canWrite && <button onClick={() => { setDetail(null); openEdit(detail.id); }} className="px-4 py-2 rounded-xl border text-sm">수정</button>}
              {isAdmin && <button onClick={() => remove(detail.id)} className="px-4 py-2 rounded-xl border text-red-500 text-sm">삭제</button>}
            </div>
          </div>
        </div>
      )}

      {/* 퀴즈/언노운 모달 */}
      {quiz && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={() => { setQuiz(null); setQuizReveal(null); }}>
          <div className="bg-white rounded-2xl shadow-xl max-w-lg w-full p-6 space-y-3 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-start justify-between">
              <h2 className="text-lg font-bold">🎯 언노운 케이스</h2>
              <button onClick={() => { setQuiz(null); setQuizReveal(null); }} className="text-slate-400 hover:text-slate-700">✕</button>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {quiz.modality && <span className="bg-slate-100 px-2 py-0.5 rounded">{quiz.modality}</span>}
              <span className={`px-2 py-0.5 rounded ${(DIFF[quiz.difficulty] || DIFF.intermediate).cls}`}>{(DIFF[quiz.difficulty] || DIFF.intermediate).label}</span>
              {quiz.patient_age && <span className="text-slate-500">{quiz.patient_age} / {quiz.patient_sex || '-'}</span>}
            </div>
            {quiz.study_available === false && (
              <div className="text-xs text-amber-600 bg-amber-50 rounded px-2 py-1">⚠ 원본 영상을 찾을 수 없습니다</div>
            )}
            <a href={`/werub-viewer/viewer?StudyInstanceUIDs=${quiz.study_instance_uid}`} target="_blank" rel="noopener noreferrer"
              className="inline-block px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700">영상 뷰어 열기 ↗</a>

            {!quizReveal ? (
              <>
                <p className="text-xs text-slate-500">영상을 판독하고 진단 소견을 작성한 뒤 제출하세요. 제출하면 정답이 공개됩니다(되돌릴 수 없음).</p>
                {error && <div className="text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</div>}
                <textarea value={quizAnswer} onChange={e => setQuizAnswer(e.target.value)} rows={4}
                  placeholder="나의 진단 소견…" className="w-full border rounded-lg px-3 py-2 text-sm" />
                <button onClick={submitQuiz} disabled={busy}
                  className="px-4 py-2 rounded-xl bg-indigo-600 text-white text-sm font-semibold hover:bg-indigo-700 disabled:opacity-50">
                  {busy ? '제출 중…' : '제출하고 정답 보기'}
                </button>
              </>
            ) : (
              <div className="space-y-3 border-t pt-3">
                <div><div className="text-xs text-slate-400">나의 답안</div><p className="text-sm whitespace-pre-wrap bg-slate-50 rounded px-3 py-2">{quizReveal.submitted_answer}</p></div>
                <div><div className="text-xs text-slate-400">제목</div><p className="text-sm font-semibold">{quizReveal.title}</p></div>
                {quizReveal.diagnosis && <div><div className="text-xs text-slate-400">정답 진단</div><p className="text-sm whitespace-pre-wrap text-emerald-700">{quizReveal.diagnosis}</p></div>}
                {quizReveal.summary && <div><div className="text-xs text-slate-400">요약</div><p className="text-sm whitespace-pre-wrap">{quizReveal.summary}</p></div>}
                {quizReveal.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1">{quizReveal.tags.map(t => <span key={t} className="text-[11px] text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded">#{t}</span>)}</div>
                )}
                <div className="pt-1">
                  <div className="text-xs text-slate-500 mb-1.5">자가평가 — 내 답안이 정답과 얼마나 일치했나요?</div>
                  <div className="flex gap-2">
                    <button onClick={() => assessQuiz('correct')} className="flex-1 px-3 py-2 rounded-xl bg-emerald-600 text-white text-sm font-semibold hover:bg-emerald-700">맞음</button>
                    <button onClick={() => assessQuiz('partial')} className="flex-1 px-3 py-2 rounded-xl bg-amber-500 text-white text-sm font-semibold hover:bg-amber-600">부분</button>
                    <button onClick={() => assessQuiz('incorrect')} className="flex-1 px-3 py-2 rounded-xl bg-red-500 text-white text-sm font-semibold hover:bg-red-600">틀림</button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 학습 진도 모달 */}
      {progress && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={() => setProgress(null)}>
          <div className="bg-white rounded-2xl shadow-xl max-w-xl w-full p-6 space-y-4 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-start justify-between">
              <h2 className="text-lg font-bold">📊 내 학습 진도</h2>
              <button onClick={() => setProgress(null)} className="text-slate-400 hover:text-slate-700">✕</button>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-center">
              <div className="bg-slate-50 rounded-xl p-3"><div className="text-xs text-slate-400">총 시도</div><div className="text-2xl font-bold">{progress.total_attempts}</div></div>
              <div className="bg-emerald-50 rounded-xl p-3"><div className="text-xs text-slate-400">정답률</div><div className="text-2xl font-bold text-emerald-600">{progress.accuracy != null ? `${progress.accuracy}%` : '-'}</div></div>
              <div className="bg-slate-50 rounded-xl p-3"><div className="text-xs text-slate-400">평가완료</div><div className="text-2xl font-bold">{progress.assessed}</div></div>
              <div className="bg-slate-50 rounded-xl p-3"><div className="text-xs text-slate-400">맞음/부분/틀림</div><div className="text-sm font-bold mt-1.5"><span className="text-emerald-600">{progress.correct}</span> / <span className="text-amber-600">{progress.partial}</span> / <span className="text-red-500">{progress.incorrect}</span></div></div>
            </div>
            {progress.total_attempts === 0 ? (
              <div className="text-center py-8 text-slate-400 text-sm">아직 퀴즈 기록이 없습니다. 케이스에서 🎯 퀴즈 풀기를 시작하세요.</div>
            ) : (
              <>
                <Bars title="모달리티별" rows={progress.by_modality} />
                <Bars title="난이도별" rows={progress.by_difficulty} diff />
                <div>
                  <div className="text-sm font-semibold mb-1.5">최근 시도</div>
                  <div className="space-y-1">
                    {progress.recent.map(r => (
                      <div key={r.attempt_id} className="flex items-center justify-between text-xs border-b py-1.5">
                        <span className="truncate flex-1">{r.case_title}</span>
                        {r.modality && <span className="bg-slate-100 px-1.5 py-0.5 rounded mx-2">{r.modality}</span>}
                        <span className={ASSESS[r.self_assessment || '']?.cls || 'text-slate-400'}>{ASSESS[r.self_assessment || '']?.label || '미평가'}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Bars({ title, rows, diff = false }: { title: string; rows: Breakdown[]; diff?: boolean }) {
  if (!rows.length) return null;
  return (
    <div>
      <div className="text-sm font-semibold mb-1.5">{title}</div>
      <div className="space-y-1.5">
        {rows.map(r => {
          const label = diff ? (DIFF[r.key || '']?.label || r.key || '-') : (r.key || '기타');
          const pct = r.accuracy ?? 0;
          return (
            <div key={r.key || 'na'} className="flex items-center gap-2 text-xs">
              <span className="w-20 shrink-0 text-slate-600">{label}</span>
              <div className="flex-1 bg-slate-100 rounded-full h-3 overflow-hidden">
                <div className="bg-emerald-500 h-full" style={{ width: `${pct}%` }} />
              </div>
              <span className="w-24 shrink-0 text-right text-slate-500">{r.accuracy != null ? `${r.accuracy}%` : '미평가'} ({r.correct}/{r.assessed})</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Field({ label, value, onChange, disabled = false }:
  { label: string; value: string; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-slate-500">{label}</span>
      <input value={value} disabled={disabled} onChange={e => onChange(e.target.value)}
        className="border rounded-lg px-3 py-2 disabled:bg-slate-100" />
    </label>
  );
}
