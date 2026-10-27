'use client';

import Link from 'next/link';
import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { apiFetch } from '@/lib/api';
import ViewerButton from '@/components/ViewerButton';

type Opinion = {
  id: string; study_instance_uid: string; question: string;
  external_email: string | null; response: string | null;
  status: string; created_at: string; responded_at: string | null;
  requester: string;
};

export default function SecondOpinionWrapper() {
  return <Suspense fallback={<p className="text-center mt-20">로딩 중...</p>}><SecondOpinionPage /></Suspense>;
}

function SecondOpinionPage() {
  const params = useSearchParams();
  const opinionId = params.get('id');
  const [opinion, setOpinion] = useState<Opinion | null>(null);
  const [list, setList] = useState<Opinion[]>([]);
  const [response, setResponse] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [filter, setFilter] = useState('');

  useEffect(() => {
    if (opinionId) {
      // Detail view
      apiFetch<Opinion>(`/api/v1/conferences/second-opinion/${opinionId}`).then(setOpinion).catch(() => {});
    } else {
      // List view
      const url = filter ? `/api/v1/conferences/second-opinion/all?status=${filter}` : '/api/v1/conferences/second-opinion/all';
      apiFetch<{ requests: Opinion[] }>(url).then(d => setList(d.requests)).catch(() => {});
    }
  }, [opinionId, filter]);

  // Detail view — respond to second opinion
  if (opinionId && opinion) {
    const isPending = opinion.status === 'pending';
    return (
      <div className="max-w-3xl mx-auto">
        <h1 className="text-2xl font-bold mb-6">세컨드 오피니언</h1>

        <div className="bg-white rounded-xl border shadow-sm p-6 space-y-4">
          <div className="flex items-center justify-between">
            <span className={`px-3 py-1 rounded-full text-xs font-semibold ${opinion.status === 'completed' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'}`}>
              {opinion.status === 'completed' ? '응답 완료' : '응답 대기'}
            </span>
            <span className="text-xs text-gray-400">{new Date(opinion.created_at).toLocaleString('ko-KR')}</span>
          </div>

          <div>
            <label className="text-sm font-semibold text-gray-700 block mb-1">요청자</label>
            <p className="text-sm">{opinion.requester}</p>
          </div>

          <div>
            <label className="text-sm font-semibold text-gray-700 block mb-1">질문 / 자문 요청</label>
            <div className="bg-blue-50 rounded-lg p-4 text-sm whitespace-pre-wrap border border-blue-200">
              {opinion.question}
            </div>
          </div>

          <div>
            <label className="text-sm font-semibold text-gray-700 block mb-1">Study</label>
            <div className="flex items-center gap-3">
              <code className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">{opinion.study_instance_uid?.substring(0, 40)}...</code>
              <ViewerButton url={`/werub-viewer/viewer?StudyInstanceUIDs=${opinion.study_instance_uid}`} label="영상 보기" size="sm" />
            </div>
          </div>

          {opinion.response && (
            <div>
              <label className="text-sm font-semibold text-gray-700 block mb-1">전문의 응답</label>
              <div className="bg-green-50 rounded-lg p-4 text-sm whitespace-pre-wrap border border-green-200">
                {opinion.response}
              </div>
              {opinion.responded_at && (
                <p className="text-xs text-gray-400 mt-1">응답일: {new Date(opinion.responded_at).toLocaleString('ko-KR')}</p>
              )}
            </div>
          )}

          {isPending && !submitted && (
            <div>
              <label className="text-sm font-semibold text-gray-700 block mb-1">의견 작성</label>
              <textarea rows={6} value={response} onChange={e => setResponse(e.target.value)}
                className="w-full border rounded-lg px-4 py-3 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                placeholder="전문의 의견을 작성하세요..." />
              <div className="flex justify-end gap-2 mt-3">
                <Link href="/second-opinion" className="px-4 py-2 border rounded-lg text-sm">목록으로</Link>
                <button onClick={async () => {
                  if (!response.trim()) return;
                  await apiFetch(`/api/v1/conferences/second-opinion/${opinionId}/respond`, {
                    method: 'PUT', body: JSON.stringify({ response }),
                  });
                  setSubmitted(true);
                  setOpinion({ ...opinion, status: 'completed', response });
                }} className="px-6 py-2 bg-green-600 text-white rounded-lg text-sm font-semibold hover:bg-green-700">
                  응답 제출
                </button>
              </div>
            </div>
          )}

          {submitted && (
            <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-sm text-green-800 font-medium">
              응답이 제출되었습니다. 요청자에게 알림이 전송됩니다.
            </div>
          )}
        </div>
      </div>
    );
  }

  if (opinionId && !opinion) {
    return <div className="text-center mt-20 text-gray-400">로딩 중...</div>;
  }

  // List view
  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">세컨드 오피니언</h1>

      <div className="flex gap-2 mb-4">
        {[
          { key: '', label: '전체' },
          { key: 'pending', label: '대기' },
          { key: 'completed', label: '완료' },
        ].map(f => (
          <button key={f.key} onClick={() => setFilter(f.key)}
            className={`px-3 py-1.5 rounded text-sm font-medium transition ${filter === f.key ? 'bg-primary text-white' : 'bg-white border text-gray-600 hover:bg-gray-50'}`}>
            {f.label}
          </button>
        ))}
      </div>

      <div className="bg-white rounded-lg border shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-500">
            <tr>
              <th className="px-3 py-2 text-left">상태</th>
              <th className="px-3 py-2 text-left">요청자</th>
              <th className="px-3 py-2 text-left">질문</th>
              <th className="px-3 py-2 text-left">외부 이메일</th>
              <th className="px-3 py-2 text-left">요청일</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {list.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-12 text-center text-gray-400">세컨드 오피니언 요청이 없습니다</td></tr>
            )}
            {list.map(o => (
              <tr key={o.id} className="border-t hover:bg-gray-50">
                <td className="px-3 py-2">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${o.status === 'completed' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'}`}>
                    {o.status === 'completed' ? '완료' : '대기'}
                  </span>
                </td>
                <td className="px-3 py-2">{o.requester}</td>
                <td className="px-3 py-2 text-gray-600 max-w-[250px] truncate">{o.question}</td>
                <td className="px-3 py-2 text-gray-500 text-xs">{o.external_email || '-'}</td>
                <td className="px-3 py-2 text-gray-500 text-xs whitespace-nowrap">{new Date(o.created_at).toLocaleDateString('ko-KR')}</td>
                <td className="px-3 py-2">
                  <a href={`/pacs-admin/second-opinion?id=${o.id}`}
                    className="bg-blue-600 text-white px-2 py-1 rounded text-xs hover:bg-blue-700">
                    {o.status === 'pending' ? '응답하기' : '보기'}
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
