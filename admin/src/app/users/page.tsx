'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import ConfirmDialog from '@/components/ConfirmDialog';

const EMPTY_USER = { username: '', email: '', password: '', full_name: '', role: 'physician', department: '', status: 'active' };
const EMPTY_RESET = { password: '', confirm: '' };

interface User {
  id: string;
  username: string;
  email: string;
  full_name: string;
  role: string;
  department: string;
  status: string;
  created_at: string;
}

interface FormErrors {
  username?: string;
  email?: string;
  password?: string;
  full_name?: string;
}

function validateForm(form: typeof EMPTY_USER, editingId: string | null): FormErrors {
  const errors: FormErrors = {};
  if (!form.username.trim()) {
    errors.username = '사용자명을 입력하세요.';
  } else if (form.username.length < 3) {
    errors.username = '사용자명은 3자 이상이어야 합니다.';
  }
  if (!form.email.trim()) {
    errors.email = '이메일을 입력하세요.';
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
    errors.email = '올바른 이메일 형식이 아닙니다.';
  }
  if (!editingId && !form.password) {
    errors.password = '비밀번호를 입력하세요.';
  } else if (form.password) {
    if (form.password.length < 8) {
      errors.password = '비밀번호는 8자 이상이어야 합니다.';
    } else if (!/[A-Z]/.test(form.password)) {
      errors.password = '대문자를 1개 이상 포함해야 합니다.';
    } else if (!/[0-9]/.test(form.password)) {
      errors.password = '숫자를 1개 이상 포함해야 합니다.';
    } else if (!/[!@#$%^&*]/.test(form.password)) {
      errors.password = '특수문자(!@#$%^&*)를 1개 이상 포함해야 합니다.';
    }
  }
  if (!form.full_name.trim()) {
    errors.full_name = '이름을 입력하세요.';
  }
  return errors;
}

const roleBadge: Record<string, string> = {
  admin: 'bg-red-100 text-red-800',
  radiologist: 'bg-blue-100 text-blue-800',
  physician: 'bg-green-100 text-green-800',
  technologist: 'bg-yellow-100 text-yellow-800',
  researcher: 'bg-purple-100 text-purple-800',
};

const roleLabel: Record<string, string> = {
  admin: '관리자',
  radiologist: '영상의학과',
  physician: '임상의',
  technologist: '기사',
  researcher: '연구자',
};

export default function UsersPage() {
  const [me, setMe] = useState<any>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_USER);
  const [formErrors, setFormErrors] = useState<FormErrors>({});
  const [msg, setMsg] = useState('');
  const [msgType, setMsgType] = useState<'success' | 'error'>('success');
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [sortCol, setSortCol] = useState<string>('username');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  // Confirm dialog state
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  // Password reset modal
  const [resetUserId, setResetUserId] = useState<string | null>(null);
  const [resetUser, setResetUser] = useState<User | null>(null);
  const [resetForm, setResetForm] = useState(EMPTY_RESET);
  const [resetError, setResetError] = useState('');

  const LIMIT = 20;

  const showMsg = (text: string, type: 'success' | 'error' = 'success') => {
    setMsg(text);
    setMsgType(type);
    setTimeout(() => setMsg(''), 4000);
  };

  const loadUsers = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        limit: String(LIMIT),
        ...(search && { search }),
        ...(roleFilter && { role: roleFilter }),
        sort: sortCol,
        order: sortDir,
      });
      const result: any = await apiFetch(`/api/v1/users?${params}`);
      setUsers(result.results || []);
      setTotal(result.total || 0);
    } catch (e: any) {
      showMsg(`목록 로드 실패: ${e.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async () => {
    const errors = validateForm(form, editingId);
    if (Object.keys(errors).length > 0) {
      setFormErrors(errors);
      return;
    }
    setFormErrors({});
    try {
      const body = { ...form };
      if (editingId && !body.password) delete (body as any).password;
      const method = editingId ? 'PUT' : 'POST';
      const path = editingId ? `/api/v1/users/${editingId}` : '/api/v1/auth/register';
      await apiFetch(path, { method, body: JSON.stringify(body) });
      setShowForm(false);
      setForm(EMPTY_USER);
      setEditingId(null);
      showMsg(editingId ? '사용자가 수정되었습니다.' : '사용자가 등록되었습니다.');
      loadUsers();
    } catch (e: any) {
      showMsg(`오류: ${e.message}`, 'error');
    }
  };

  const handleDeleteRequest = (id: string) => {
    setConfirmDeleteId(id);
    setConfirmOpen(true);
  };

  const handleDeleteConfirm = async () => {
    if (!confirmDeleteId) return;
    setConfirmOpen(false);
    try {
      await apiFetch(`/api/v1/users/${confirmDeleteId}`, { method: 'DELETE' });
      showMsg('사용자가 삭제되었습니다.');
      loadUsers();
    } catch (e: any) {
      showMsg(`삭제 실패: ${e.message}`, 'error');
    } finally {
      setConfirmDeleteId(null);
    }
  };

  const handleEdit = (user: User) => {
    setEditingId(user.id);
    setForm({
      username: user.username,
      email: user.email,
      password: '',
      full_name: user.full_name,
      role: user.role,
      department: user.department,
      status: user.status || 'active',
    });
    setFormErrors({});
    setShowForm(true);
  };

  const handleOpenForm = () => {
    setEditingId(null);
    setForm(EMPTY_USER);
    setFormErrors({});
    setShowForm(true);
  };

  const openPasswordReset = (user: User) => {
    setResetUserId(user.id);
    setResetUser(user);
    setResetForm(EMPTY_RESET);
    setResetError('');
  };

  const handlePasswordReset = async () => {
    if (!resetForm.password || resetForm.password.length < 8) {
      setResetError('비밀번호는 8자 이상이어야 합니다.');
      return;
    }
    if (!/[A-Z]/.test(resetForm.password) || !/[0-9]/.test(resetForm.password) || !/[!@#$%^&*]/.test(resetForm.password)) {
      setResetError('대문자, 숫자, 특수문자(!@#$%^&*)를 각 1개 이상 포함해야 합니다.');
      return;
    }
    if (resetForm.password !== resetForm.confirm) {
      setResetError('비밀번호가 일치하지 않습니다.');
      return;
    }
    try {
      await apiFetch(`/api/v1/users/${resetUserId}/reset-password`, {
        method: 'POST',
        body: JSON.stringify({ new_password: resetForm.password }),
      });
      setResetUserId(null);
      setResetUser(null);
      showMsg('비밀번호가 재설정되었습니다.');
    } catch (e: any) {
      setResetError(`실패: ${e.message}`);
    }
  };

  const handleSort = (col: string) => {
    if (sortCol === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortCol(col);
      setSortDir('asc');
    }
  };

  const SortIcon = ({ col }: { col: string }) => {
    if (sortCol !== col) return <span className="ml-1 text-gray-300">↕</span>;
    return <span className="ml-1">{sortDir === 'asc' ? '↑' : '↓'}</span>;
  };

  useEffect(() => {
    apiFetch('/api/v1/auth/me').then(setMe).catch(() => {});
  }, []);

  useEffect(() => {
    loadUsers();
  }, [page, search, roleFilter, sortCol, sortDir]);

  const totalPages = Math.max(1, Math.ceil(total / LIMIT));

  return (
    <div>
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4">
        <h1 className="text-2xl font-bold">사용자 관리</h1>
        {me?.role === 'admin' && (
          <button
            onClick={handleOpenForm}
            className="bg-primary text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-primary-dark"
          >
            + 사용자 추가
          </button>
        )}
      </div>

      {msg && (
        <div className={`mb-4 p-3 rounded text-sm ${msgType === 'error' ? 'bg-red-50 text-red-800 border border-red-200' : 'bg-green-50 text-green-800'}`}>
          {msg}
        </div>
      )}

      {/* Search & Filters */}
      <div className="bg-white rounded-lg border shadow-sm p-4 mb-6">
        <div className="flex flex-col sm:flex-row gap-3">
          <input
            type="text"
            placeholder="이름, 사용자명 또는 이메일 검색..."
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1); }}
            className="flex-1 border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
          <select
            value={roleFilter}
            onChange={e => { setRoleFilter(e.target.value); setPage(1); }}
            className="border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          >
            <option value="">모든 역할</option>
            <option value="admin">관리자</option>
            <option value="radiologist">영상의학과</option>
            <option value="physician">임상의</option>
            <option value="technologist">기사</option>
            <option value="researcher">연구자</option>
          </select>
        </div>
      </div>

      {/* User Table */}
      <div className="bg-white rounded-lg border shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th
                  className="px-4 py-3 text-left cursor-pointer hover:bg-gray-100 select-none"
                  onClick={() => handleSort('username')}
                >
                  사용자명<SortIcon col="username" />
                </th>
                <th
                  className="px-4 py-3 text-left cursor-pointer hover:bg-gray-100 select-none"
                  onClick={() => handleSort('full_name')}
                >
                  이름<SortIcon col="full_name" />
                </th>
                <th className="px-4 py-3 text-left">이메일</th>
                <th
                  className="px-4 py-3 text-left cursor-pointer hover:bg-gray-100 select-none"
                  onClick={() => handleSort('role')}
                >
                  역할<SortIcon col="role" />
                </th>
                <th className="px-4 py-3 text-left">부서</th>
                <th className="px-4 py-3 text-left">상태</th>
                <th
                  className="px-4 py-3 text-left cursor-pointer hover:bg-gray-100 select-none"
                  onClick={() => handleSort('created_at')}
                >
                  가입일<SortIcon col="created_at" />
                </th>
                <th className="px-4 py-3 text-center">작업</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                [...Array(5)].map((_, i) => (
                  <tr key={i} className="border-b animate-pulse">
                    {[...Array(8)].map((_, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="h-3 bg-gray-200 rounded" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : users.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center text-gray-500">
                    <p>사용자가 없습니다.</p>
                    {(search || roleFilter) && (
                      <button
                        onClick={() => { setSearch(''); setRoleFilter(''); }}
                        className="mt-2 text-sm text-primary underline"
                      >
                        필터 초기화
                      </button>
                    )}
                  </td>
                </tr>
              ) : (
                users.map(user => (
                  <tr key={user.id} className="border-b hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium">{user.username}</td>
                    <td className="px-4 py-3">{user.full_name}</td>
                    <td className="px-4 py-3 text-gray-600">{user.email}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-1 rounded text-xs font-medium ${roleBadge[user.role] || 'bg-gray-100 text-gray-700'}`}>
                        {roleLabel[user.role] || user.role}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-600">{user.department || '-'}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${user.status === 'active' ? 'bg-green-100 text-green-800' : user.status === 'inactive' ? 'bg-gray-100 text-gray-600' : 'bg-red-100 text-red-700'}`}>
                        {user.status === 'active' ? '활성' : user.status === 'inactive' ? '비활성' : user.status || '활성'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {user.created_at ? new Date(user.created_at).toLocaleDateString('ko-KR') : '-'}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <div className="flex items-center justify-center gap-2">
                        <button
                          onClick={() => handleEdit(user)}
                          className="text-primary hover:text-primary-dark text-xs font-semibold"
                        >
                          수정
                        </button>
                        {me?.role === 'admin' && (
                          <>
                            <button
                              onClick={() => openPasswordReset(user)}
                              className="text-yellow-600 hover:text-yellow-800 text-xs font-semibold"
                            >
                              PW재설정
                            </button>
                            <button
                              onClick={() => handleDeleteRequest(user.id)}
                              className="text-red-600 hover:text-red-800 text-xs font-semibold"
                            >
                              삭제
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
      </div>

      {/* Pagination */}
      {total > 0 && (
        <div className="flex items-center justify-between mt-4 text-sm">
          <div className="text-gray-600">
            총 {total}명 중 {(page - 1) * LIMIT + 1}-{Math.min(page * LIMIT, total)}명 표시
          </div>
          <div className="flex gap-1">
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
          </div>
        </div>
      )}

      {/* Create / Edit Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={() => setShowForm(false)}>
          <div className="bg-white rounded-xl shadow-2xl p-6 w-full max-w-md" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-4">{editingId ? '사용자 수정' : '사용자 등록'}</h2>
            <div className="space-y-3 text-sm">
              <div>
                <label className="text-xs text-gray-500">사용자명 *</label>
                <input
                  className={`w-full border rounded px-2 py-1.5 ${formErrors.username ? 'border-red-400' : ''}`}
                  value={form.username}
                  onChange={e => setForm({...form, username: e.target.value})}
                  disabled={!!editingId}
                />
                {formErrors.username && <p className="text-red-500 text-xs mt-0.5">{formErrors.username}</p>}
              </div>
              <div>
                <label className="text-xs text-gray-500">이메일 *</label>
                <input
                  type="email"
                  className={`w-full border rounded px-2 py-1.5 ${formErrors.email ? 'border-red-400' : ''}`}
                  value={form.email}
                  onChange={e => setForm({...form, email: e.target.value})}
                />
                {formErrors.email && <p className="text-red-500 text-xs mt-0.5">{formErrors.email}</p>}
              </div>
              <div>
                <label className="text-xs text-gray-500">비밀번호 {editingId ? '(변경할 경우만)' : '*'}</label>
                <input
                  type="password"
                  className={`w-full border rounded px-2 py-1.5 ${formErrors.password ? 'border-red-400' : ''}`}
                  value={form.password}
                  onChange={e => setForm({...form, password: e.target.value})}
                  placeholder={editingId ? '비워두면 변경 안함' : '8자 이상, 대문자·숫자·특수문자 포함'}
                />
                {!formErrors.password && !editingId && form.password.length > 0 && (
                  <p className="text-gray-400 text-xs mt-0.5">대문자, 숫자, 특수문자(!@#$%^&*) 각 1개 이상 필요</p>
                )}
                {formErrors.password && <p className="text-red-500 text-xs mt-0.5">{formErrors.password}</p>}
              </div>
              <div>
                <label className="text-xs text-gray-500">이름 *</label>
                <input
                  className={`w-full border rounded px-2 py-1.5 ${formErrors.full_name ? 'border-red-400' : ''}`}
                  value={form.full_name}
                  onChange={e => setForm({...form, full_name: e.target.value})}
                />
                {formErrors.full_name && <p className="text-red-500 text-xs mt-0.5">{formErrors.full_name}</p>}
              </div>
              <div>
                <label className="text-xs text-gray-500">역할</label>
                <select
                  className="w-full border rounded px-2 py-1.5"
                  value={form.role}
                  onChange={e => setForm({...form, role: e.target.value})}
                >
                  <option value="admin">관리자</option>
                  <option value="radiologist">영상의학과</option>
                  <option value="physician">임상의</option>
                  <option value="technologist">기사</option>
                  <option value="researcher">연구자</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500">부서</label>
                <input
                  className="w-full border rounded px-2 py-1.5"
                  value={form.department}
                  onChange={e => setForm({...form, department: e.target.value})}
                />
              </div>
              {editingId && (
                <div>
                  <label className="text-xs text-gray-500 block mb-1">상태</label>
                  <div className="flex gap-4">
                    {[
                      { value: 'active', label: '활성' },
                      { value: 'inactive', label: '비활성' },
                      { value: 'suspended', label: '정지' },
                    ].map(opt => (
                      <label key={opt.value} className="flex items-center gap-1.5 text-sm cursor-pointer">
                        <input
                          type="radio"
                          name="user-status"
                          value={opt.value}
                          checked={form.status === opt.value}
                          onChange={() => setForm({...form, status: opt.value})}
                        />
                        <span className={opt.value === 'active' ? 'text-green-700' : opt.value === 'suspended' ? 'text-red-600' : 'text-gray-500'}>
                          {opt.label}
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => { setShowForm(false); setEditingId(null); setFormErrors({}); }}
                className="px-4 py-2 border rounded text-sm"
              >
                취소
              </button>
              <button
                onClick={handleRegister}
                className="px-4 py-2 bg-primary text-white rounded text-sm font-semibold hover:bg-primary-dark"
              >
                {editingId ? '수정' : '등록'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Password Reset Modal */}
      {resetUserId && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={() => setResetUserId(null)}>
          <div className="bg-white rounded-xl shadow-2xl p-6 w-full max-w-sm" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-1">비밀번호 재설정</h2>
            <p className="text-sm text-gray-500 mb-4">
              대상: <span className="font-semibold text-gray-700">{resetUser?.username}</span>
            </p>
            <div className="space-y-3 text-sm">
              <div>
                <label className="text-xs text-gray-500">새 비밀번호 *</label>
                <input
                  type="password"
                  className="w-full border rounded px-2 py-1.5"
                  value={resetForm.password}
                  onChange={e => setResetForm({...resetForm, password: e.target.value})}
                  placeholder="8자 이상, 대문자·숫자·특수문자 포함"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">비밀번호 확인 *</label>
                <input
                  type="password"
                  className="w-full border rounded px-2 py-1.5"
                  value={resetForm.confirm}
                  onChange={e => setResetForm({...resetForm, confirm: e.target.value})}
                  placeholder="비밀번호를 다시 입력하세요"
                />
              </div>
              {resetError && <p className="text-red-500 text-xs">{resetError}</p>}
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setResetUserId(null)} className="px-4 py-2 border rounded text-sm">취소</button>
              <button
                onClick={handlePasswordReset}
                className="px-4 py-2 bg-yellow-500 text-white rounded text-sm font-semibold hover:bg-yellow-600"
              >
                재설정
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        open={confirmOpen}
        title="사용자 삭제"
        description="정말 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다."
        confirmLabel="삭제"
        onConfirm={handleDeleteConfirm}
        onCancel={() => { setConfirmOpen(false); setConfirmDeleteId(null); }}
      />

      {/* Current User Info */}
      {me && (
        <div className="bg-white rounded-lg border shadow-sm p-6 mt-6 mb-6">
          <h3 className="font-semibold mb-3">현재 로그인 사용자</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div><span className="text-gray-500">사용자명: </span><span className="font-medium">{me.username}</span></div>
            <div><span className="text-gray-500">이름: </span><span className="font-medium">{me.full_name}</span></div>
            <div>
              <span className="text-gray-500">역할: </span>
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${roleBadge[me.role] || 'bg-gray-100'}`}>
                {roleLabel[me.role] || me.role}
              </span>
            </div>
            <div><span className="text-gray-500">이메일: </span><span className="font-medium">{me.email}</span></div>
          </div>
        </div>
      )}

      {/* Role Permissions Table */}
      <div className="bg-white rounded-lg border shadow-sm p-6">
        <h3 className="font-semibold mb-3">역할별 권한</h3>
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-2 text-left">역할</th>
              <th className="px-4 py-2 text-center">영상 조회</th>
              <th className="px-4 py-2 text-center">판독/리포트</th>
              <th className="px-4 py-2 text-center">업로드/QC</th>
              <th className="px-4 py-2 text-center">AI 실행</th>
              <th className="px-4 py-2 text-center">사용자 관리</th>
            </tr>
          </thead>
          <tbody>
            {[
              { role: 'admin', view: true, read: true, upload: true, ai: true, manage: true },
              { role: 'radiologist', view: true, read: true, upload: false, ai: true, manage: false },
              { role: 'physician', view: true, read: false, upload: false, ai: false, manage: false },
              { role: 'technologist', view: true, read: false, upload: true, ai: false, manage: false },
              { role: 'researcher', view: true, read: false, upload: false, ai: true, manage: false },
            ].map(r => (
              <tr key={r.role} className="border-t">
                <td className="px-4 py-2">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${roleBadge[r.role]}`}>
                    {roleLabel[r.role]}
                  </span>
                </td>
                {[r.view, r.read, r.upload, r.ai, r.manage].map((v, i) => (
                  <td key={i} className="px-4 py-2 text-center">{v ? '✅' : '—'}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
