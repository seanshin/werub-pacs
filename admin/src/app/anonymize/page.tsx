'use client';

import { useState, useEffect } from 'react';
import { apiFetch } from '@/lib/api';

type Study = {
  study_instance_uid: string;
  patient_name: string;
  patient_id: string;
  modality: string;
  study_date: string;
  description: string;
};

type AnonymizeResult = {
  study_uid: string;
  status: string;
  anonymized_id?: string;
  anonymized_pid?: string;
};

export default function AnonymizePage() {
  const [studies, setStudies] = useState<Study[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<AnonymizeResult[] | null>(null);
  const [keepDate, setKeepDate] = useState(false);
  const [prefix, setPrefix] = useState('ANON');
  const [history, setHistory] = useState<any[]>([]);
  const [search, setSearch] = useState('');

  // Load studies from DICOMweb
  useEffect(() => {
    apiFetch<any>('/api/v1/dicomweb/studies?limit=100').then(data => {
      if (Array.isArray(data)) {
        setStudies(data.map((s: any) => ({
          study_instance_uid: s['0020000D']?.Value?.[0] || s.study_instance_uid || '',
          patient_name: s['00100010']?.Value?.[0]?.Alphabetic || s.patient_name || '',
          patient_id: s['00100020']?.Value?.[0] || s.patient_id || '',
          modality: s['00080061']?.Value?.join('/') || s.modality || '',
          study_date: s['00080020']?.Value?.[0] || s.study_date || '',
          description: s['00081030']?.Value?.[0] || s.description || '',
        })));
      }
    }).catch(() => {});
    loadHistory();
  }, []);

  const loadHistory = () => {
    apiFetch<any>('/api/v1/anonymize/history?limit=20').then(data => {
      setHistory(data?.history || []);
    }).catch(() => {});
  };

  const toggleSelect = (uid: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(uid) ? next.delete(uid) : next.add(uid);
      return next;
    });
  };

  const selectAll = () => {
    if (selected.size === filtered.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(filtered.map(s => s.study_instance_uid)));
    }
  };

  const handleAnonymize = async () => {
    if (selected.size === 0) return;
    setLoading(true);
    setResults(null);
    try {
      const res = await apiFetch<any>('/api/v1/anonymize/batch', {
        method: 'POST',
        body: JSON.stringify({
          study_uids: Array.from(selected),
          keep_study_date: keepDate,
          custom_prefix: prefix,
        }),
      });
      setResults(res?.results || []);
      loadHistory();
    } catch (e: any) {
      alert(e.message);
    }
    setLoading(false);
  };

  const filtered = studies.filter(s =>
    !search || s.patient_name.includes(search) || s.patient_id.includes(search) || s.description.includes(search)
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">익명화 (De-identification)</h1>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1 text-sm">
            <input type="checkbox" checked={keepDate} onChange={e => setKeepDate(e.target.checked)} />
            검사일 유지
          </label>
          <input
            type="text"
            value={prefix}
            onChange={e => setPrefix(e.target.value)}
            className="border rounded px-2 py-1 text-sm w-24"
            placeholder="접두사"
          />
          <button
            onClick={handleAnonymize}
            disabled={selected.size === 0 || loading}
            className="bg-red-600 text-white px-4 py-2 rounded-lg font-semibold hover:bg-red-700 disabled:opacity-50 text-sm"
          >
            {loading ? '처리 중...' : `선택 익명화 (${selected.size}건)`}
          </button>
        </div>
      </div>

      {/* Results */}
      {results && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-4">
          <h3 className="font-semibold text-green-800 mb-2">
            익명화 완료: {results.filter(r => r.status === 'anonymized').length}/{results.length}건
          </h3>
          <div className="text-sm space-y-1">
            {results.map((r, i) => (
              <div key={i} className={r.status === 'anonymized' ? 'text-green-700' : 'text-red-600'}>
                {r.study_uid.substring(0, 30)}... → {r.status === 'anonymized' ? `${r.anonymized_pid}` : r.status}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Search */}
      <div className="mb-4">
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="환자명, 환자번호, 검사설명 검색..."
          className="w-full border rounded-lg px-3 py-2 text-sm"
        />
      </div>

      {/* Study Table */}
      <div className="bg-white rounded-lg border shadow-sm overflow-hidden mb-8">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-3 py-2 text-left">
                <input type="checkbox" onChange={selectAll} checked={selected.size === filtered.length && filtered.length > 0} />
              </th>
              <th className="px-3 py-2 text-left">환자명</th>
              <th className="px-3 py-2 text-left">환자번호</th>
              <th className="px-3 py-2 text-left">모달리티</th>
              <th className="px-3 py-2 text-left">검사일</th>
              <th className="px-3 py-2 text-left">검사설명</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(s => (
              <tr
                key={s.study_instance_uid}
                className={`border-b hover:bg-gray-50 cursor-pointer ${selected.has(s.study_instance_uid) ? 'bg-blue-50' : ''}`}
                onClick={() => toggleSelect(s.study_instance_uid)}
              >
                <td className="px-3 py-2">
                  <input type="checkbox" checked={selected.has(s.study_instance_uid)} readOnly />
                </td>
                <td className="px-3 py-2 font-medium">{s.patient_name || '-'}</td>
                <td className="px-3 py-2 text-gray-600">{s.patient_id}</td>
                <td className="px-3 py-2">{s.modality}</td>
                <td className="px-3 py-2">{s.study_date}</td>
                <td className="px-3 py-2 text-gray-600 truncate max-w-[200px]">{s.description || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* History */}
      <div>
        <h2 className="text-lg font-semibold mb-3">익명화 이력</h2>
        <div className="bg-white rounded-lg border shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-3 py-2 text-left">작업</th>
                <th className="px-3 py-2 text-left">사용자</th>
                <th className="px-3 py-2 text-left">대상</th>
                <th className="px-3 py-2 text-left">일시</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h, i) => (
                <tr key={i} className="border-b">
                  <td className="px-3 py-2">{h.action === 'BATCH_ANONYMIZE' ? '배치 익명화' : '단일 익명화'}</td>
                  <td className="px-3 py-2">{h.user_name}</td>
                  <td className="px-3 py-2 text-gray-600 truncate max-w-[200px]">{h.resource_id}</td>
                  <td className="px-3 py-2 text-gray-500">{h.created_at ? new Date(h.created_at).toLocaleString('ko-KR') : ''}</td>
                </tr>
              ))}
              {history.length === 0 && (
                <tr><td colSpan={4} className="px-3 py-8 text-center text-gray-400">이력이 없습니다</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
