'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import Breadcrumb from '@/components/ui/Breadcrumb';
import Link from 'next/link';

type Rule = {
  id: string; rule_code: string; display_name: string; category: string;
  default_severity: string; severity: string; severity_locked: boolean;
  enabled: boolean; default_message: string; custom_message: string | null;
  auto_action: string; thresholds: Record<string, any> | null;
};
type ModalityConfig = {
  modality: string; render_type: string; display_label: string;
  description: string; action_text: string | null; enabled: boolean;
};
type MessageTemplate = {
  message_key: string; context: string; default_text: string;
  custom_text: string | null; text: string; variables: string[] | null;
};

const sevColors: Record<string, string> = {
  critical: 'text-red-700 bg-red-50', error: 'text-orange-700 bg-orange-50',
  warning: 'text-yellow-700 bg-yellow-50', info: 'text-blue-700 bg-blue-50',
};
const actionLabel: Record<string, string> = {
  none: '없음', normalize: '자동 정규화', quarantine: '격리', reject: '거부', alert: '알림',
};
const renderLabel: Record<string, string> = {
  non_renderable: '비렌더링', partial: '부분 렌더링', renderable: '렌더링 가능',
};

export default function DicomIssueSettingsPage() {
  const [tab, setTab] = useState<'rules' | 'modality' | 'messages'>('rules');
  const [rules, setRules] = useState<Rule[]>([]);
  const [modalities, setModalities] = useState<ModalityConfig[]>([]);
  const [messages, setMessages] = useState<MessageTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null);
  const [editMsg, setEditMsg] = useState<MessageTemplate | null>(null);
  const [editMsgText, setEditMsgText] = useState('');
  const [editMod, setEditMod] = useState<ModalityConfig | null>(null);

  useEffect(() => { loadAll(); }, []);
  useEffect(() => { if (!toast) return; const t = setTimeout(() => setToast(null), 3000); return () => clearTimeout(t); }, [toast]);

  const showToast = (msg: string, type: 'success' | 'error' = 'success') => setToast({ msg, type });

  const loadAll = async () => {
    setLoading(true);
    try {
      const [r, m, msg] = await Promise.all([
        apiFetch<{ rules: Rule[] }>('/api/v1/dicom-issues/rules'),
        apiFetch<{ configs: ModalityConfig[] }>('/api/v1/dicom-issues/modality-config'),
        apiFetch<{ messages: MessageTemplate[] }>('/api/v1/dicom-issues/messages'),
      ]);
      setRules(r.rules); setModalities(m.configs); setMessages(msg.messages);
    } catch (e: any) { showToast(e.message, 'error'); }
    setLoading(false);
  };

  const updateRule = async (code: string, patch: Partial<Rule>) => {
    setSaving(true);
    try {
      await apiFetch(`/api/v1/dicom-issues/rules/${code}`, {
        method: 'PUT', body: JSON.stringify(patch),
      });
      showToast(`${code} 규칙이 수정되었습니다.`);
      loadAll();
    } catch (e: any) { showToast(e.message, 'error'); }
    setSaving(false);
  };

  const updateModality = async (mod: string, patch: Partial<ModalityConfig>) => {
    setSaving(true);
    try {
      await apiFetch(`/api/v1/dicom-issues/modality-config/${mod}`, {
        method: 'PUT', body: JSON.stringify(patch),
      });
      showToast(`${mod} 설정이 수정되었습니다.`);
      loadAll();
    } catch (e: any) { showToast(e.message, 'error'); }
    setSaving(false);
  };

  const updateMessage = async (key: string, customText: string | null) => {
    setSaving(true);
    try {
      await apiFetch(`/api/v1/dicom-issues/messages/${key}`, {
        method: 'PUT', body: JSON.stringify({ custom_text: customText }),
      });
      showToast('메시지가 수정되었습니다.');
      setEditMsg(null);
      loadAll();
    } catch (e: any) { showToast(e.message, 'error'); }
    setSaving(false);
  };

  const resetAll = async () => {
    if (!confirm('모든 규칙을 기본값으로 복원하시겠습니까?')) return;
    setSaving(true);
    try {
      await apiFetch('/api/v1/dicom-issues/rules/reset', { method: 'POST' });
      showToast('모든 규칙이 기본값으로 복원되었습니다.');
      loadAll();
    } catch (e: any) { showToast(e.message, 'error'); }
    setSaving(false);
  };

  return (
    <div className="p-4 sm:p-6 max-w-[1200px] mx-auto">
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-2 rounded-lg shadow-lg text-sm font-medium ${toast.type === 'error' ? 'bg-red-500 text-white' : 'bg-green-500 text-white'}`}>
          {toast.msg}
        </div>
      )}
      <div className="flex items-center justify-between mb-6">
        <div>
          <Breadcrumb items={[{ label: '관리', href: '/' }, { label: 'DICOM 이슈', href: '/dicom-issues' }, { label: '규칙 설정' }]} />
          <h1 className="text-2xl font-bold mt-1">DICOM 이슈 규칙 설정</h1>
        </div>
        <Link href="/dicom-issues" className="px-4 py-2 bg-slate-100 rounded-lg text-sm hover:bg-slate-200">← 이슈 현황</Link>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 border-b">
        {[
          { key: 'rules' as const, label: '검증 규칙' },
          { key: 'modality' as const, label: '모달리티 설정' },
          { key: 'messages' as const, label: '에러 메시지' },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition ${tab === t.key ? 'border-indigo-500 text-indigo-700' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {loading ? <div className="py-20 text-center text-gray-400">불러오는 중...</div> : (
        <>
          {/* Rules Tab */}
          {tab === 'rules' && (
            <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b">
                    <tr>
                      <th className="px-3 py-2.5 text-left w-12">활성</th>
                      <th className="px-3 py-2.5 text-left">규칙 코드</th>
                      <th className="px-3 py-2.5 text-left hidden md:table-cell">표시명</th>
                      <th className="px-3 py-2.5 text-left w-20">카테고리</th>
                      <th className="px-3 py-2.5 text-left w-28">심각도</th>
                      <th className="px-3 py-2.5 text-left w-28">자동 조치</th>
                      <th className="px-3 py-2.5 text-left hidden lg:table-cell">커스텀 메시지</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {rules.map(rule => (
                      <tr key={rule.rule_code} className="hover:bg-gray-50">
                        <td className="px-3 py-2.5">
                          <input type="checkbox" checked={rule.enabled}
                            onChange={e => updateRule(rule.rule_code, { enabled: e.target.checked })}
                            className="rounded" disabled={saving} />
                        </td>
                        <td className="px-3 py-2.5">
                          <code className="text-xs text-gray-700">{rule.rule_code}</code>
                        </td>
                        <td className="px-3 py-2.5 hidden md:table-cell text-gray-600 text-xs">{rule.display_name}</td>
                        <td className="px-3 py-2.5 text-[10px] font-medium text-gray-500 uppercase">{rule.category}</td>
                        <td className="px-3 py-2.5">
                          {rule.severity_locked ? (
                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${sevColors[rule.severity]}`} title="잠금됨">
                              {rule.severity.toUpperCase()} 🔒
                            </span>
                          ) : (
                            <select value={rule.severity} disabled={saving}
                              onChange={e => updateRule(rule.rule_code, { severity: e.target.value })}
                              className={`text-[10px] font-bold rounded px-2 py-0.5 border-0 ${sevColors[rule.severity]}`}>
                              <option value="critical">CRITICAL</option>
                              <option value="error">ERROR</option>
                              <option value="warning">WARNING</option>
                              <option value="info">INFO</option>
                            </select>
                          )}
                        </td>
                        <td className="px-3 py-2.5">
                          <select value={rule.auto_action} disabled={saving}
                            onChange={e => updateRule(rule.rule_code, { auto_action: e.target.value })}
                            className="text-xs border rounded px-2 py-0.5">
                            {Object.entries(actionLabel).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                          </select>
                        </td>
                        <td className="px-3 py-2.5 hidden lg:table-cell">
                          <input type="text" placeholder={rule.default_message.slice(0, 40) + '...'}
                            defaultValue={rule.custom_message || ''}
                            onBlur={e => {
                              const v = e.target.value.trim();
                              if (v !== (rule.custom_message || '')) updateRule(rule.rule_code, { custom_message: v || null });
                            }}
                            className="text-xs border rounded px-2 py-0.5 w-full" disabled={saving} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="px-4 py-3 border-t bg-gray-50 flex justify-between">
                <span className="text-xs text-gray-400">{rules.length}개 규칙</span>
                <button onClick={resetAll} disabled={saving}
                  className="px-3 py-1.5 text-xs text-red-600 border border-red-200 rounded hover:bg-red-50 disabled:opacity-50">기본값 복원</button>
              </div>
            </div>
          )}

          {/* Modality Tab */}
          {tab === 'modality' && (
            <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b">
                    <tr>
                      <th className="px-3 py-2.5 text-left w-12">활성</th>
                      <th className="px-3 py-2.5 text-left w-24">모달리티</th>
                      <th className="px-3 py-2.5 text-left w-28">렌더링 유형</th>
                      <th className="px-3 py-2.5 text-left">표시명</th>
                      <th className="px-3 py-2.5 text-left hidden md:table-cell">설명</th>
                      <th className="px-3 py-2.5 text-right w-16">편집</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {modalities.map(mod => (
                      <tr key={mod.modality} className="hover:bg-gray-50">
                        <td className="px-3 py-2.5">
                          <input type="checkbox" checked={mod.enabled}
                            onChange={e => updateModality(mod.modality, { enabled: e.target.checked })}
                            className="rounded" disabled={saving} />
                        </td>
                        <td className="px-3 py-2.5 font-mono font-bold text-sm">{mod.modality}</td>
                        <td className="px-3 py-2.5">
                          <select value={mod.render_type} disabled={saving}
                            onChange={e => updateModality(mod.modality, { render_type: e.target.value })}
                            className="text-xs border rounded px-2 py-0.5">
                            <option value="non_renderable">비렌더링</option>
                            <option value="partial">부분 렌더링</option>
                            <option value="renderable">렌더링 가능</option>
                          </select>
                        </td>
                        <td className="px-3 py-2.5 text-sm">{mod.display_label}</td>
                        <td className="px-3 py-2.5 hidden md:table-cell text-xs text-gray-500 max-w-xs truncate">{mod.description}</td>
                        <td className="px-3 py-2.5 text-right">
                          <button onClick={() => setEditMod(mod)} className="text-xs text-indigo-600 hover:underline">편집</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="px-4 py-3 border-t bg-gray-50 text-xs text-gray-400">
                {modalities.length}개 모달리티 설정 — 복합 모달리티(CT\SR)에서 렌더링 가능한 것이 하나라도 있으면 표시
              </div>
            </div>
          )}

          {/* Messages Tab */}
          {tab === 'messages' && (
            <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b">
                    <tr>
                      <th className="px-3 py-2.5 text-left">메시지 키</th>
                      <th className="px-3 py-2.5 text-left w-20">컨텍스트</th>
                      <th className="px-3 py-2.5 text-left">현재 텍스트</th>
                      <th className="px-3 py-2.5 text-left hidden md:table-cell">변수</th>
                      <th className="px-3 py-2.5 text-right w-16">편집</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {messages.map(msg => (
                      <tr key={msg.message_key} className="hover:bg-gray-50">
                        <td className="px-3 py-2.5 font-mono text-xs text-gray-600">{msg.message_key}</td>
                        <td className="px-3 py-2.5 text-[10px] font-medium text-gray-500 uppercase">{msg.context}</td>
                        <td className="px-3 py-2.5">
                          <span className={msg.custom_text ? 'text-indigo-700 font-medium' : 'text-gray-600'}>{msg.text}</span>
                          {msg.custom_text && <span className="ml-1 text-[8px] text-indigo-400">(커스텀)</span>}
                        </td>
                        <td className="px-3 py-2.5 hidden md:table-cell">
                          {msg.variables?.map(v => (
                            <span key={v} className="inline-block px-1.5 py-0.5 bg-gray-100 rounded text-[9px] font-mono mr-1">{v}</span>
                          ))}
                        </td>
                        <td className="px-3 py-2.5 text-right">
                          <button onClick={() => { setEditMsg(msg); setEditMsgText(msg.custom_text || ''); }}
                            className="text-xs text-indigo-600 hover:underline">편집</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {/* Message Edit Modal */}
      {editMsg && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setEditMsg(null)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md" onClick={e => e.stopPropagation()}>
            <div className="p-5 border-b">
              <h3 className="font-semibold">메시지 편집</h3>
              <code className="text-xs text-gray-400">{editMsg.message_key}</code>
            </div>
            <div className="p-5 space-y-3">
              <div>
                <label className="text-xs text-gray-400">기본 메시지</label>
                <p className="text-sm text-gray-500 bg-gray-50 rounded p-2">{editMsg.default_text}</p>
              </div>
              {editMsg.variables && editMsg.variables.length > 0 && (
                <div>
                  <label className="text-xs text-gray-400">사용 가능한 변수</label>
                  <div className="flex gap-1 mt-1">
                    {editMsg.variables.map(v => (
                      <span key={v} className="px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded text-xs font-mono">{v}</span>
                    ))}
                  </div>
                </div>
              )}
              <div>
                <label className="text-xs text-gray-400">커스텀 메시지 (비우면 기본 사용)</label>
                <textarea value={editMsgText} onChange={e => setEditMsgText(e.target.value)} rows={3}
                  className="w-full border rounded-lg p-2 text-sm mt-1" placeholder={editMsg.default_text} />
              </div>
              {editMsgText && (
                <div>
                  <label className="text-xs text-gray-400">미리보기</label>
                  <p className="text-sm bg-yellow-50 rounded p-2 border border-yellow-200">
                    {editMsgText || editMsg.default_text}
                  </p>
                </div>
              )}
            </div>
            <div className="p-4 border-t flex justify-end gap-2">
              <button onClick={() => setEditMsg(null)} className="px-4 py-2 border rounded-lg text-sm">취소</button>
              <button onClick={() => updateMessage(editMsg.message_key, editMsgText || null)} disabled={saving}
                className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-700 disabled:opacity-50">저장</button>
            </div>
          </div>
        </div>
      )}

      {/* Modality Edit Modal */}
      {editMod && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setEditMod(null)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md" onClick={e => e.stopPropagation()}>
            <div className="p-5 border-b">
              <h3 className="font-semibold">모달리티 설정 편집 — {editMod.modality}</h3>
            </div>
            <div className="p-5 space-y-3">
              <div>
                <label className="text-xs text-gray-400">표시명</label>
                <input type="text" defaultValue={editMod.display_label}
                  onBlur={e => setEditMod(m => m ? { ...m, display_label: e.target.value } : null)}
                  className="w-full border rounded-lg p-2 text-sm mt-1" />
              </div>
              <div>
                <label className="text-xs text-gray-400">설명</label>
                <textarea defaultValue={editMod.description} rows={2}
                  onBlur={e => setEditMod(m => m ? { ...m, description: e.target.value } : null)}
                  className="w-full border rounded-lg p-2 text-sm mt-1" />
              </div>
              <div>
                <label className="text-xs text-gray-400">조치 안내</label>
                <input type="text" defaultValue={editMod.action_text || ''}
                  onBlur={e => setEditMod(m => m ? { ...m, action_text: e.target.value } : null)}
                  className="w-full border rounded-lg p-2 text-sm mt-1" />
              </div>
            </div>
            <div className="p-4 border-t flex justify-end gap-2">
              <button onClick={() => setEditMod(null)} className="px-4 py-2 border rounded-lg text-sm">취소</button>
              <button disabled={saving} onClick={() => {
                if (!editMod) return;
                updateModality(editMod.modality, {
                  display_label: editMod.display_label,
                  description: editMod.description,
                  action_text: editMod.action_text,
                });
                setEditMod(null);
              }}
                className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-700 disabled:opacity-50">저장</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
