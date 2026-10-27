'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

interface Tenant {
  id: string;
  name: string;
  slug: string;
  domain: string | null;
  is_active: boolean;
  storage_quota_gb: number;
  max_users: number;
  user_count?: number;
  created_at: string;
}

interface TenantUser {
  user_id: string;
  username: string;
  full_name: string;
  email: string;
  role: string;
}

const EMPTY_FORM = { name: '', slug: '', domain: '', storage_quota_gb: 100, max_users: 50 };

export default function TenantsPage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');
  const [msgType, setMsgType] = useState<'success' | 'error'>('success');

  // Create/Edit modal
  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);

  // User assignment
  const [selectedTenant, setSelectedTenant] = useState<string | null>(null);
  const [tenantUsers, setTenantUsers] = useState<TenantUser[]>([]);
  const [assignUserId, setAssignUserId] = useState('');
  const [assignRole, setAssignRole] = useState('radiologist');

  const showMsg = (text: string, type: 'success' | 'error' = 'success') => {
    setMsg(text);
    setMsgType(type);
    setTimeout(() => setMsg(''), 4000);
  };

  const loadTenants = async () => {
    setLoading(true);
    try {
      const res: any = await apiFetch('/api/v1/tenants?active_only=false&page_size=100');
      setTenants(res.tenants || []);
      setTotal(res.total || 0);
    } catch (e: any) {
      showMsg(`목록 로드 실패: ${e.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    if (!form.name || !form.slug) { showMsg('이름과 슬러그는 필수입니다.', 'error'); return; }
    try {
      if (editingId) {
        await apiFetch(`/api/v1/tenants/${editingId}`, {
          method: 'PUT',
          body: JSON.stringify({
            name: form.name, domain: form.domain || null,
            storage_quota_gb: form.storage_quota_gb, max_users: form.max_users,
          }),
        });
        showMsg('기관이 수정되었습니다.');
      } else {
        await apiFetch('/api/v1/tenants', {
          method: 'POST',
          body: JSON.stringify(form),
        });
        showMsg('기관이 등록되었습니다.');
      }
      setShowModal(false);
      setEditingId(null);
      setForm(EMPTY_FORM);
      loadTenants();
    } catch (e: any) {
      showMsg(`오류: ${e.message}`, 'error');
    }
  };

  const toggleActive = async (t: Tenant) => {
    try {
      await apiFetch(`/api/v1/tenants/${t.id}`, {
        method: 'PUT',
        body: JSON.stringify({ is_active: !t.is_active }),
      });
      showMsg(`${t.name} ${t.is_active ? '비활성화' : '활성화'}됨`);
      loadTenants();
    } catch (e: any) {
      showMsg(`상태 변경 실패: ${e.message}`, 'error');
    }
  };

  const openEdit = (t: Tenant) => {
    setEditingId(t.id);
    setForm({ name: t.name, slug: t.slug, domain: t.domain || '', storage_quota_gb: t.storage_quota_gb, max_users: t.max_users });
    setShowModal(true);
  };

  const loadUsers = async (tenantId: string) => {
    setSelectedTenant(tenantId);
    try {
      const res: any = await apiFetch(`/api/v1/tenants/${tenantId}/users`);
      setTenantUsers(res.users || []);
    } catch (e: any) {
      showMsg(`사용자 로드 실패: ${e.message}`, 'error');
    }
  };

  const handleAssign = async () => {
    if (!selectedTenant || !assignUserId) return;
    try {
      await apiFetch(`/api/v1/tenants/${selectedTenant}/users?user_id=${assignUserId}&role=${assignRole}`, { method: 'POST' });
      showMsg('사용자가 배정되었습니다.');
      setAssignUserId('');
      loadUsers(selectedTenant);
    } catch (e: any) {
      showMsg(`배정 실패: ${e.message}`, 'error');
    }
  };

  useEffect(() => { loadTenants(); }, []);

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">기관 관리 (Multi-Tenancy)</h1>
        <button onClick={() => { setEditingId(null); setForm(EMPTY_FORM); setShowModal(true); }}
          className="bg-primary text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-primary-dark">
          + 기관 등록
        </button>
      </div>

      {msg && (
        <div className={`mb-4 p-3 rounded text-sm ${msgType === 'error' ? 'bg-red-50 text-red-800 border border-red-200' : 'bg-green-50 text-green-800'}`}>
          {msg}
        </div>
      )}

      {/* Tenant Table */}
      <div className="bg-white rounded-lg border shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-4 py-3 text-left">이름</th>
              <th className="px-4 py-3 text-left">슬러그</th>
              <th className="px-4 py-3 text-left">도메인</th>
              <th className="px-4 py-3 text-center">사용자</th>
              <th className="px-4 py-3 text-center">쿼타(GB)</th>
              <th className="px-4 py-3 text-center">상태</th>
              <th className="px-4 py-3 text-left">등록일</th>
              <th className="px-4 py-3 text-center">작업</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              [...Array(3)].map((_, i) => (
                <tr key={i} className="border-b animate-pulse">
                  {[...Array(8)].map((_, j) => <td key={j} className="px-4 py-3"><div className="h-3 bg-gray-200 rounded" /></td>)}
                </tr>
              ))
            ) : tenants.length === 0 ? (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-gray-500">등록된 기관이 없습니다.</td></tr>
            ) : tenants.map(t => (
              <tr key={t.id} className="border-b hover:bg-gray-50">
                <td className="px-4 py-3 font-medium">{t.name}</td>
                <td className="px-4 py-3 text-gray-600 font-mono text-xs">{t.slug}</td>
                <td className="px-4 py-3 text-gray-600">{t.domain || '-'}</td>
                <td className="px-4 py-3 text-center">{t.max_users}</td>
                <td className="px-4 py-3 text-center">{t.storage_quota_gb}</td>
                <td className="px-4 py-3 text-center">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${t.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'}`}>
                    {t.is_active ? '활성' : '비활성'}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-500 text-xs">{t.created_at ? new Date(t.created_at).toLocaleDateString('ko-KR') : '-'}</td>
                <td className="px-4 py-3 text-center">
                  <div className="flex items-center justify-center gap-2">
                    <button onClick={() => openEdit(t)} className="text-primary hover:text-primary-dark text-xs font-semibold">수정</button>
                    <button onClick={() => toggleActive(t)} className={`text-xs font-semibold ${t.is_active ? 'text-yellow-600 hover:text-yellow-800' : 'text-green-600 hover:text-green-800'}`}>
                      {t.is_active ? '비활성화' : '활성화'}
                    </button>
                    <button onClick={() => loadUsers(t.id)} className="text-blue-600 hover:text-blue-800 text-xs font-semibold">사용자</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-gray-500 mt-2">총 {total}개 기관</p>

      {/* User Assignment Panel */}
      {selectedTenant && (
        <div className="bg-white rounded-lg border shadow-sm p-5 mt-6">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-bold">기관 사용자 관리</h2>
            <button onClick={() => setSelectedTenant(null)} className="text-gray-400 hover:text-gray-600 text-sm">닫기</button>
          </div>
          <div className="flex gap-2 mb-4">
            <input placeholder="사용자 ID" value={assignUserId} onChange={e => setAssignUserId(e.target.value)}
              className="flex-1 border rounded px-3 py-2 text-sm" />
            <select value={assignRole} onChange={e => setAssignRole(e.target.value)} className="border rounded px-3 py-2 text-sm">
              <option value="admin">관리자</option>
              <option value="radiologist">영상의학과</option>
              <option value="physician">임상의</option>
              <option value="technologist">기사</option>
            </select>
            <button onClick={handleAssign} className="bg-primary text-white px-4 py-2 rounded text-sm font-semibold hover:bg-primary-dark">배정</button>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50"><tr>
              <th className="px-3 py-2 text-left">사용자명</th>
              <th className="px-3 py-2 text-left">이름</th>
              <th className="px-3 py-2 text-left">이메일</th>
              <th className="px-3 py-2 text-left">역할</th>
            </tr></thead>
            <tbody>
              {tenantUsers.length === 0 ? (
                <tr><td colSpan={4} className="px-3 py-6 text-center text-gray-500">배정된 사용자가 없습니다.</td></tr>
              ) : tenantUsers.map(u => (
                <tr key={u.user_id} className="border-t">
                  <td className="px-3 py-2 font-medium">{u.username}</td>
                  <td className="px-3 py-2">{u.full_name}</td>
                  <td className="px-3 py-2 text-gray-600">{u.email}</td>
                  <td className="px-3 py-2">
                    <span className="px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">{u.role}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create / Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={() => setShowModal(false)}>
          <div className="bg-white rounded-xl shadow-2xl p-6 w-full max-w-md" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-4">{editingId ? '기관 수정' : '기관 등록'}</h2>
            <div className="space-y-3 text-sm">
              <div>
                <label className="text-xs text-gray-500">기관명 *</label>
                <input className="w-full border rounded px-2 py-1.5" value={form.name}
                  onChange={e => setForm({ ...form, name: e.target.value })} placeholder="예: 서울대병원" />
              </div>
              <div>
                <label className="text-xs text-gray-500">슬러그 *</label>
                <input className="w-full border rounded px-2 py-1.5 font-mono" value={form.slug}
                  onChange={e => setForm({ ...form, slug: e.target.value })} placeholder="예: snu" disabled={!!editingId} />
              </div>
              <div>
                <label className="text-xs text-gray-500">도메인</label>
                <input className="w-full border rounded px-2 py-1.5" value={form.domain}
                  onChange={e => setForm({ ...form, domain: e.target.value })} placeholder="예: snu.openpacs.kr" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-500">스토리지 쿼타 (GB)</label>
                  <input type="number" className="w-full border rounded px-2 py-1.5" value={form.storage_quota_gb}
                    onChange={e => setForm({ ...form, storage_quota_gb: Number(e.target.value) })} />
                </div>
                <div>
                  <label className="text-xs text-gray-500">최대 사용자</label>
                  <input type="number" className="w-full border rounded px-2 py-1.5" value={form.max_users}
                    onChange={e => setForm({ ...form, max_users: Number(e.target.value) })} />
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button onClick={() => { setShowModal(false); setEditingId(null); }} className="px-4 py-2 border rounded text-sm">취소</button>
              <button onClick={handleSave} className="px-4 py-2 bg-primary text-white rounded text-sm font-semibold hover:bg-primary-dark">
                {editingId ? '수정' : '등록'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
