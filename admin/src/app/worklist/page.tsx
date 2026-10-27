'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { formatDate, ModalityBadge } from '@/lib/format';
import ConfirmDialog from '@/components/ConfirmDialog';
import Breadcrumb from '@/components/ui/Breadcrumb';

type WorklistItem = {
  id: string;
  patient_id: string;
  patient_name: string;
  accession_number: string;
  modality: string;
  scheduled_date: string;
  scheduled_time: string | null;
  body_part_examined: string | null;
  status: string;
  priority: string;
  scheduled_station_ae_title: string;
  referring_physician: string | null;
  clinical_info?: string | null;
  // MPPS (performed) — set by modality via MPPS N-CREATE/N-SET
  performed_start_time?: string | null;
  performed_end_time?: string | null;
  performed_station_ae_title?: string | null;
  // 영상 도착 시 기록 (MPPS 또는 병리 WSI 도착 감지 beat가 채움)
  study_instance_uid?: string | null;
};

const EMPTY_FORM = {
  patient_id: '',
  patient_name: '',
  modality: 'CT',
  body_part: '',
  scheduled_date: new Date().toISOString().slice(0, 10),
  scheduled_time: '',
  ae_title: 'CT_ROOM1',
  referring_physician: '',
  clinical_info: '',
  priority: 'routine',
};

const PAGE_LIMIT = 20;

const statusBadge: Record<string, string> = {
  scheduled: 'bg-blue-100 text-blue-800',
  in_progress: 'bg-yellow-100 text-yellow-800',
  completed: 'bg-green-100 text-green-800',
  cancelled: 'bg-red-100 text-red-800',
};

const statusLabel: Record<string, string> = {
  scheduled: '예약',
  in_progress: '진행중',
  completed: '완료',
  cancelled: '취소',
};

export default function WorklistPage() {
  const [items, setItems] = useState<WorklistItem[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<any>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [modalityFilter, setModalityFilter] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('');
  const [searchText, setSearchText] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');
  const [msgType, setMsgType] = useState<'success' | 'error'>('success');
  const [page, setPage] = useState(1);

  // Confirm cancel dialog
  const [confirmCancelOpen, setConfirmCancelOpen] = useState(false);
  const [pendingCancelItem, setPendingCancelItem] = useState<WorklistItem | null>(null);

  // Detail / Edit modal
  const [viewItem, setViewItem] = useState<WorklistItem | null>(null);
  const [editItem, setEditItem] = useState<WorklistItem | null>(null);
  const [editStatus, setEditStatus] = useState('');
  const [editPriority, setEditPriority] = useState('');

  const showMsg = (text: string, type: 'success' | 'error' = 'success') => {
    setMsg(text);
    setMsgType(type);
    setTimeout(() => setMsg(''), 4000);
  };

  const loadData = async (targetPage?: number) => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_LIMIT),
        offset: String(((targetPage ?? page) - 1) * PAGE_LIMIT),
      });
      if (statusFilter) params.append('status', statusFilter);
      if (modalityFilter) params.append('modality', modalityFilter);
      if (priorityFilter) params.append('priority', priorityFilter);
      if (searchText) params.append('search', searchText);
      if (dateFrom) params.append('date_from', dateFrom);
      if (dateTo) params.append('date_to', dateTo);

      const [wl, st] = await Promise.all([
        apiFetch<{ results: WorklistItem[]; total: number }>(`/api/v1/worklist?${params.toString()}`),
        apiFetch('/api/v1/worklist/stats'),
      ]);
      setItems(wl.results || []);
      setTotal(wl.total || 0);
      setStats(st);
    } catch (e: any) {
      setError(e.message || '워크리스트를 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setPage(1);
    loadData(1);
  }, [statusFilter, modalityFilter, priorityFilter, searchText, dateFrom, dateTo]);

  useEffect(() => {
    loadData(page);
  }, [page]);

  const validateCreate = () => {
    if (!form.patient_id.trim()) return '환자번호를 입력하세요.';
    if (!form.patient_name.trim()) return '환자명을 입력하세요.';
    if (!form.scheduled_date) return '예약일을 선택하세요.';
    return '';
  };

  const handleCreate = async () => {
    const err = validateCreate();
    if (err) { setFormError(err); return; }
    setFormError('');
    try {
      await apiFetch('/api/v1/worklist', {
        method: 'POST',
        body: JSON.stringify({
          patient_id: form.patient_id,
          patient_name: form.patient_name,
          modality: form.modality,
          body_part_examined: form.body_part,
          scheduled_date: form.scheduled_date,
          scheduled_time: form.scheduled_time || null,
          scheduled_station_ae_title: form.ae_title,
          referring_physician: form.referring_physician,
          clinical_info: form.clinical_info,
          priority: form.priority,
          accession_number: `ACC-${Date.now()}`,
          requested_procedure_id: `RP-${Date.now()}`,
        }),
      });
      setShowForm(false);
      setForm(EMPTY_FORM);
      showMsg('검사가 등록되었습니다.');
      loadData(1);
    } catch (e: any) {
      setFormError(e.message || '등록 실패');
    }
  };

  const handleCancelRequest = (item: WorklistItem) => {
    setPendingCancelItem(item);
    setConfirmCancelOpen(true);
  };

  const handleCancelConfirm = async () => {
    if (!pendingCancelItem) return;
    setConfirmCancelOpen(false);
    try {
      await apiFetch(`/api/v1/worklist/${pendingCancelItem.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: 'cancelled' }),
      });
      showMsg('검사가 취소되었습니다.');
      loadData(page);
    } catch (e: any) {
      showMsg(`취소 실패: ${e.message}`, 'error');
    } finally {
      setPendingCancelItem(null);
    }
  };

  const handleSaveEdit = async () => {
    if (!editItem) return;
    try {
      await apiFetch(`/api/v1/worklist/${editItem.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: editStatus, priority: editPriority }),
      });
      setEditItem(null);
      showMsg('검사가 수정되었습니다.');
      loadData(page);
    } catch (e: any) {
      showMsg(`수정 실패: ${e.message}`, 'error');
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_LIMIT));
  const hasFilters = statusFilter || modalityFilter || priorityFilter || searchText || dateFrom || dateTo;

  const resetFilters = () => {
    setStatusFilter('');
    setModalityFilter('');
    setPriorityFilter('');
    setSearchText('');
    setDateFrom('');
    setDateTo('');
    setPage(1);
  };

  return (
    <div>
      <Breadcrumb items={[{ label: '워크리스트' }]} />
      <div className="flex justify-between items-center mb-2">
        <h1 className="text-2xl font-bold">워크리스트 관리</h1>
        <button
          onClick={() => { setShowForm(true); setFormError(''); setForm(EMPTY_FORM); }}
          className="bg-primary text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-primary-dark"
        >
          + 검사 추가
        </button>
      </div>

      <p className="mb-5 text-xs text-gray-500">
        📡 예약 검사는 <span className="font-semibold">Modality Worklist(MWL)</span>로 촬영실 장비에 자동 제공되어 환자정보 수기 입력을 예방합니다.
        촬영 시작·완료는 <span className="font-semibold">MPPS</span>로 자동 보고되어 상태(진행중→완료)와 수행 시각·장비가 갱신됩니다.
        <span className="text-gray-400"> (MWL/MPPS SCP: AE OPENPACS-MWL)</span>
      </p>

      {msg && (
        <div className={`mb-4 p-3 rounded text-sm ${msgType === 'error' ? 'bg-red-50 text-red-800 border border-red-200' : 'bg-green-50 text-green-800'}`}>
          {msg}
        </div>
      )}

      {/* Create Form Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={() => setShowForm(false)}>
          <div className="bg-white rounded-xl shadow-2xl p-6 w-full max-w-lg" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-4">검사 예약 등록</h2>
            {formError && (
              <div className="mb-3 p-2 bg-red-50 text-red-700 text-xs rounded border border-red-200">{formError}</div>
            )}
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <label className="text-xs text-gray-500">환자번호 *</label>
                <input
                  className={`w-full border rounded px-2 py-1.5 ${!form.patient_id && formError ? 'border-red-400' : ''}`}
                  value={form.patient_id}
                  onChange={e => setForm({...form, patient_id: e.target.value})}
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">환자명 *</label>
                <input
                  className={`w-full border rounded px-2 py-1.5 ${!form.patient_name && formError ? 'border-red-400' : ''}`}
                  value={form.patient_name}
                  onChange={e => setForm({...form, patient_name: e.target.value})}
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">모달리티 *</label>
                <select
                  className="w-full border rounded px-2 py-1.5"
                  value={form.modality}
                  onChange={e => setForm({...form, modality: e.target.value})}
                >
                  <option>CT</option>
                  <option>MR</option>
                  <option>CR</option>
                  <option>DX</option>
                  <option>US</option>
                  <option>SM</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500">검사부위</label>
                <input
                  className="w-full border rounded px-2 py-1.5"
                  placeholder="CHEST, HEAD..."
                  value={form.body_part}
                  onChange={e => setForm({...form, body_part: e.target.value})}
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">예약일 *</label>
                <input
                  type="date"
                  className="w-full border rounded px-2 py-1.5"
                  value={form.scheduled_date}
                  onChange={e => setForm({...form, scheduled_date: e.target.value})}
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">예약시간</label>
                <input
                  type="time"
                  className="w-full border rounded px-2 py-1.5"
                  value={form.scheduled_time}
                  onChange={e => setForm({...form, scheduled_time: e.target.value})}
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">장비 AET</label>
                <input
                  className="w-full border rounded px-2 py-1.5"
                  value={form.ae_title}
                  onChange={e => setForm({...form, ae_title: e.target.value})}
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">의뢰의</label>
                <input
                  className="w-full border rounded px-2 py-1.5"
                  value={form.referring_physician}
                  onChange={e => setForm({...form, referring_physician: e.target.value})}
                />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-gray-500">임상정보</label>
                <input
                  className="w-full border rounded px-2 py-1.5"
                  value={form.clinical_info}
                  onChange={e => setForm({...form, clinical_info: e.target.value})}
                />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-gray-500">우선순위</label>
                <div className="flex gap-3 mt-1">
                  {['routine', 'high', 'stat'].map(p => (
                    <label key={p} className="flex items-center gap-1 text-sm">
                      <input
                        type="radio"
                        name="priority"
                        checked={form.priority === p}
                        onChange={() => setForm({...form, priority: p})}
                      />
                      {p === 'routine' ? '정상' : p === 'high' ? '높음' : '긴급'}
                    </label>
                  ))}
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setShowForm(false)} className="px-4 py-2 border rounded text-sm">취소</button>
              <button
                onClick={handleCreate}
                className="px-4 py-2 bg-primary text-white rounded text-sm font-semibold hover:bg-primary-dark"
              >
                등록
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-5 gap-3 mb-6">
          <div className="bg-white border rounded-lg p-3 text-center">
            <p className="text-sm text-gray-500">전체</p>
            <p className="text-2xl font-bold">{stats.total}</p>
          </div>
          {['scheduled', 'in_progress', 'completed', 'cancelled'].map(s => (
            <div key={s} className="bg-white border rounded-lg p-3 text-center">
              <p className="text-sm text-gray-500">{statusLabel[s]}</p>
              <p className="text-2xl font-bold">{stats[s] || 0}</p>
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="bg-white rounded-lg border shadow-sm p-4 mb-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 text-sm">
          <input
            type="text"
            placeholder="환자명 또는 ID..."
            value={searchText}
            onChange={e => setSearchText(e.target.value)}
            className="border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
          />
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
          >
            <option value="">모든 상태</option>
            <option value="scheduled">예약</option>
            <option value="in_progress">진행중</option>
            <option value="completed">완료</option>
            <option value="cancelled">취소</option>
          </select>
          <select
            value={modalityFilter}
            onChange={e => setModalityFilter(e.target.value)}
            className="border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
          >
            <option value="">모든 모달리티</option>
            <option value="CT">CT</option>
            <option value="MR">MR</option>
            <option value="CR">CR</option>
            <option value="DX">DX</option>
            <option value="US">US</option>
            <option value="SM">SM (병리)</option>
          </select>
          <select
            value={priorityFilter}
            onChange={e => setPriorityFilter(e.target.value)}
            className="border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
          >
            <option value="">모든 우선순위</option>
            <option value="routine">정상</option>
            <option value="high">높음</option>
            <option value="stat">긴급</option>
          </select>
          <input
            type="date"
            value={dateFrom}
            onChange={e => setDateFrom(e.target.value)}
            className="border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
        <div className="flex items-center gap-3 mt-3 text-sm">
          <input
            type="date"
            value={dateTo}
            onChange={e => setDateTo(e.target.value)}
            className="border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
          />
          {hasFilters && (
            <button onClick={resetFilters} className="text-gray-600 underline hover:text-gray-900 text-xs">
              필터 초기화
            </button>
          )}
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => loadData(page)} className="ml-4 px-3 py-1 bg-red-100 hover:bg-red-200 rounded text-xs font-medium">
            재시도
          </button>
        </div>
      )}

      {/* Table */}
      <div className="bg-white rounded-lg border shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-500">
            <tr>
              <th className="px-4 py-2 text-left">상태</th>
              <th className="px-4 py-2 text-left">환자명</th>
              <th className="px-4 py-2 text-left">환자번호</th>
              <th className="px-4 py-2 text-left">접수번호</th>
              <th className="px-4 py-2 text-left">모달리티</th>
              <th className="px-4 py-2 text-left">검사부위</th>
              <th className="px-4 py-2 text-left">예약일</th>
              <th className="px-4 py-2 text-left">장비</th>
              <th className="px-4 py-2 text-left">의뢰의</th>
              <th className="px-4 py-2 text-center">작업</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              [...Array(5)].map((_, i) => (
                <tr key={i} className="border-t animate-pulse">
                  {[...Array(10)].map((_, j) => (
                    <td key={j} className="px-4 py-3">
                      <div className="h-3 bg-gray-200 rounded" />
                    </td>
                  ))}
                </tr>
              ))
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={10} className="px-4 py-12 text-center text-gray-500">
                  <p>검사 항목이 없습니다.</p>
                  {hasFilters && (
                    <button onClick={resetFilters} className="mt-2 text-sm text-primary underline">
                      필터 초기화
                    </button>
                  )}
                </td>
              </tr>
            ) : (
              items.map(item => (
                <tr key={item.id} className="border-t hover:bg-gray-50">
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusBadge[item.status] || 'bg-gray-100'}`}>
                      {statusLabel[item.status] || item.status}
                    </span>
                    {item.priority === 'stat' && (
                      <span className="ml-1 text-red-600 font-bold text-xs">STAT</span>
                    )}
                    {item.priority === 'high' && (
                      <span className="ml-1 text-orange-500 font-bold text-xs">HIGH</span>
                    )}
                    {/* MPPS: 모달리티가 보고한 수행 정보 */}
                    {(item.status === 'in_progress' || item.status === 'completed') && (item.performed_station_ae_title || item.performed_start_time) && (
                      <div className="mt-0.5 text-[10px] leading-tight text-gray-400">
                        <span title="MPPS 수행 보고">📡 {item.performed_station_ae_title || ''}</span>
                        {item.performed_start_time && (
                          <span> · {new Date(item.performed_start_time).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}
                          {item.performed_end_time ? `~${new Date(item.performed_end_time).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}` : '~'}</span>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-2 font-medium">{item.patient_name}</td>
                  <td className="px-4 py-2 text-gray-500">{item.patient_id}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{item.accession_number}</td>
                  <td className="px-4 py-2"><ModalityBadge modality={item.modality} /></td>
                  <td className="px-4 py-2 text-gray-600">{item.body_part_examined || '-'}</td>
                  <td className="px-4 py-2 text-gray-500 whitespace-nowrap">
                    {formatDate(item.scheduled_date)} {item.scheduled_time || ''}
                  </td>
                  <td className="px-4 py-2 text-gray-500">{item.scheduled_station_ae_title}</td>
                  <td className="px-4 py-2 text-gray-500">{item.referring_physician || '-'}</td>
                  <td className="px-4 py-2 text-center">
                    <div className="flex items-center justify-center gap-2">
                      <button
                        onClick={() => setViewItem(item)}
                        className="text-primary hover:text-primary-dark text-xs font-medium"
                      >
                        보기
                      </button>
                      {/* 영상 도착분 열람 — accession 런처가 SM은 microscopy로 자동 라우팅 */}
                      {item.study_instance_uid && (
                        <a
                          href={`/pacs-api/api/v1/viewer/launch?AccessionNumber=${encodeURIComponent(item.accession_number)}`}
                          target="_blank"
                          rel="noreferrer"
                          className="text-emerald-600 hover:text-emerald-800 text-xs font-medium"
                          title="도착한 영상 열람 (SM은 microscopy 뷰어)"
                        >
                          열람
                        </a>
                      )}
                      {item.status !== 'cancelled' && item.status !== 'completed' && (
                        <>
                          <button
                            onClick={() => {
                              setEditItem(item);
                              setEditStatus(item.status);
                              setEditPriority(item.priority);
                            }}
                            className="text-yellow-600 hover:text-yellow-800 text-xs font-medium"
                          >
                            수정
                          </button>
                          <button
                            onClick={() => handleCancelRequest(item)}
                            className="text-red-500 hover:text-red-700 text-xs font-medium"
                          >
                            취소
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {total > 0 && (
        <div className="flex items-center justify-between mt-4 text-sm">
          <div className="text-gray-600">
            총 {total.toLocaleString()}건 중 {((page - 1) * PAGE_LIMIT + 1).toLocaleString()}-{Math.min(page * PAGE_LIMIT, total).toLocaleString()}건 표시
          </div>
          <div className="flex gap-1">
            <button
              onClick={() => setPage(1)}
              disabled={page === 1}
              className="px-2 py-1 border rounded disabled:opacity-50 hover:bg-gray-50 text-xs"
            >
              처음
            </button>
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1 border rounded disabled:opacity-50 hover:bg-gray-50"
            >
              이전
            </button>
            <span className="px-3 py-1 text-gray-600">{page} / {totalPages}</span>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="px-3 py-1 border rounded disabled:opacity-50 hover:bg-gray-50"
            >
              다음
            </button>
            <button
              onClick={() => setPage(totalPages)}
              disabled={page >= totalPages}
              className="px-2 py-1 border rounded disabled:opacity-50 hover:bg-gray-50 text-xs"
            >
              마지막
            </button>
          </div>
        </div>
      )}

      {/* View Detail Modal */}
      {viewItem && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={() => setViewItem(null)}>
          <div className="bg-white rounded-xl shadow-2xl p-6 w-full max-w-md" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-bold">검사 상세 정보</h2>
              <button onClick={() => setViewItem(null)} className="text-gray-400 hover:text-gray-600 text-xl leading-none">x</button>
            </div>
            <div className="space-y-2 text-sm">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <span className="text-xs text-gray-500 block">환자명</span>
                  <span className="font-semibold">{viewItem.patient_name}</span>
                </div>
                <div>
                  <span className="text-xs text-gray-500 block">환자번호</span>
                  <span className="font-medium">{viewItem.patient_id}</span>
                </div>
                <div>
                  <span className="text-xs text-gray-500 block">접수번호</span>
                  <span className="font-mono text-xs">{viewItem.accession_number}</span>
                </div>
                <div>
                  <span className="text-xs text-gray-500 block">모달리티</span>
                  <ModalityBadge modality={viewItem.modality} />
                </div>
                <div>
                  <span className="text-xs text-gray-500 block">상태</span>
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusBadge[viewItem.status] || 'bg-gray-100'}`}>
                    {statusLabel[viewItem.status] || viewItem.status}
                  </span>
                </div>
                <div>
                  <span className="text-xs text-gray-500 block">우선순위</span>
                  <span className={`font-medium ${viewItem.priority === 'stat' ? 'text-red-600' : viewItem.priority === 'high' ? 'text-orange-500' : 'text-gray-700'}`}>
                    {viewItem.priority === 'stat' ? '긴급' : viewItem.priority === 'high' ? '높음' : '정상'}
                  </span>
                </div>
                <div>
                  <span className="text-xs text-gray-500 block">예약일시</span>
                  <span className="font-medium">{formatDate(viewItem.scheduled_date)} {viewItem.scheduled_time || ''}</span>
                </div>
                <div>
                  <span className="text-xs text-gray-500 block">장비 AET</span>
                  <span className="font-mono text-xs">{viewItem.scheduled_station_ae_title}</span>
                </div>
                <div>
                  <span className="text-xs text-gray-500 block">검사부위</span>
                  <span className="font-medium">{viewItem.body_part_examined || '-'}</span>
                </div>
                <div>
                  <span className="text-xs text-gray-500 block">의뢰의</span>
                  <span className="font-medium">{viewItem.referring_physician || '-'}</span>
                </div>
              </div>
              {viewItem.clinical_info && (
                <div>
                  <span className="text-xs text-gray-500 block">임상정보</span>
                  <p className="bg-gray-50 rounded p-2 text-xs mt-1">{viewItem.clinical_info}</p>
                </div>
              )}
            </div>
            <div className="flex justify-end mt-5">
              <button onClick={() => setViewItem(null)} className="px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded text-sm font-medium">닫기</button>
            </div>
          </div>
        </div>
      )}

      {/* Cancel Confirmation Dialog */}
      <ConfirmDialog
        open={confirmCancelOpen}
        title="검사 취소"
        description={pendingCancelItem ? `${pendingCancelItem.patient_name}의 검사를 취소하시겠습니까?` : '검사를 취소하시겠습니까?'}
        confirmLabel="취소 확인"
        confirmClassName="px-4 py-2 bg-red-600 text-white rounded text-sm font-semibold hover:bg-red-700"
        onConfirm={handleCancelConfirm}
        onCancel={() => { setConfirmCancelOpen(false); setPendingCancelItem(null); }}
      />

      {/* Edit Status/Priority Modal */}
      {editItem && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={() => setEditItem(null)}>
          <div className="bg-white rounded-xl shadow-2xl p-6 w-full max-w-sm" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-1">검사 수정</h2>
            <p className="text-sm text-gray-500 mb-4">{editItem.patient_name} — {editItem.accession_number}</p>
            <div className="space-y-3 text-sm">
              <div>
                <label className="text-xs text-gray-500 block mb-1">상태</label>
                <select
                  className="w-full border rounded px-3 py-2"
                  value={editStatus}
                  onChange={e => setEditStatus(e.target.value)}
                >
                  <option value="scheduled">예약</option>
                  <option value="in_progress">진행중</option>
                  <option value="completed">완료</option>
                  <option value="cancelled">취소</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">우선순위</label>
                <select
                  className="w-full border rounded px-3 py-2"
                  value={editPriority}
                  onChange={e => setEditPriority(e.target.value)}
                >
                  <option value="routine">정상</option>
                  <option value="high">높음</option>
                  <option value="stat">긴급</option>
                </select>
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setEditItem(null)} className="px-4 py-2 border rounded text-sm">취소</button>
              <button
                onClick={handleSaveEdit}
                className="px-4 py-2 bg-primary text-white rounded text-sm font-semibold hover:bg-primary-dark"
              >
                저장
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
