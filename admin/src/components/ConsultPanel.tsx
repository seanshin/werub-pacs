'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import ViewerButton from '@/components/ViewerButton';

type HistoryItem = {
  id: string; kind: string; label: string; status: string;
  reason?: string; requested_by_name?: string; physician_name?: string;
  institution_name?: string; urgency?: string; portal_url?: string;
  requested_at?: string; responded_at?: string;
  external_findings?: string; external_impression?: string;
  response?: string; agreement?: string; comment?: string;
};

type Props = {
  studyUID: string;
  reportId?: string;
  findings?: string;
  impression?: string;
  onClose: () => void;
};

export default function ConsultPanel({ studyUID, reportId, findings, impression, onClose }: Props) {
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [step, setStep] = useState<'list' | 'type' | 'second' | 'external' | 'peer'>('list');
  const [accounts, setAccounts] = useState<any[]>([]);
  const [form, setForm] = useState<any>({});
  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState('');

  const loadHistory = () => {
    apiFetch<{ items: HistoryItem[] }>(`/api/v1/consult-history/${studyUID}`)
      .then(d => setHistory(d.items || []))
      .catch(() => {});
  };

  useEffect(() => {
    loadHistory();
    apiFetch<{ accounts: any[] }>('/api/v1/external-accounts')
      .then(d => setAccounts(d.accounts || []))
      .catch(() => {});
  }, [studyUID]);

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(''), 3000); };

  const statusIcon = (status: string) => {
    if (status === 'completed') return '🟢';
    if (status === 'pending' || status === 'requested') return '🟡';
    if (status === 'cancelled') return '⚫';
    return '🔵';
  };

  const submit = async () => {
    setSubmitting(true);
    try {
      if (step === 'second') {
        await apiFetch('/api/v1/conferences/second-opinion/request', {
          method: 'POST',
          body: JSON.stringify({
            study_instance_uid: studyUID,
            question: (form.attachFindings ? `[현재 소견]\n${findings}\n\n[현재 결론]\n${impression}\n\n[질문]\n` : '') + (form.question || ''),
            external_email: form.email,
          }),
        });
        showToast('세컨드 오피니언이 요청되었습니다.');
      } else if (step === 'external') {
        await apiFetch('/api/v1/external-consult', {
          method: 'POST',
          body: JSON.stringify({
            study_instance_uid: studyUID, report_id: reportId,
            consult_type: form.consult_type || 'external_read',
            institution_name: form.institution, physician_name: form.physician,
            physician_email: form.email,
            reason: form.reason || '판독 의뢰',
            clinical_info: form.attachFindings ? `소견: ${findings}\n결론: ${impression}` : form.clinical_info,
            urgency: form.urgency || 'routine',
            share_method: form.share_method || 'link',
          }),
        });
        showToast('외부 판독 의뢰가 전송되었습니다.');
      } else if (step === 'peer') {
        if (!reportId) { showToast('판독 리포트가 없습니다. 먼저 판독을 완료하세요.'); setSubmitting(false); return; }
        await apiFetch('/api/v1/peer-review/assign', {
          method: 'POST',
          body: JSON.stringify({ report_id: reportId, reviewer_username: form.reviewer || null }),
        });
        showToast('피어 리뷰가 배정되었습니다.');
      }
      setStep('list'); setForm({});
      loadHistory();
    } catch (e: any) {
      showToast(e.message || '요청 실패');
    } finally { setSubmitting(false); }
  };

  return (
    <div className="w-80 shrink-0 border-l bg-white flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b flex items-center justify-between bg-gray-50">
        <h3 className="font-bold text-sm">협진/의뢰</h3>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg">&times;</button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Timeline */}
        {step === 'list' && (
          <div className="p-4">
            {history.length === 0 ? (
              <p className="text-sm text-gray-400 text-center py-8">협진 이력이 없습니다</p>
            ) : (
              <div className="space-y-3">
                {history.map(item => (
                  <div key={item.id} className={`rounded-lg border p-3 text-xs ${item.status === 'completed' ? 'bg-green-50 border-green-200' : item.status === 'cancelled' ? 'bg-gray-50' : 'bg-yellow-50 border-yellow-200'}`}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-semibold">{statusIcon(item.status)} {item.label}</span>
                      <span className="text-gray-400">{item.requested_at ? new Date(item.requested_at).toLocaleDateString('ko-KR') : ''}</span>
                    </div>
                    {item.institution_name && <div className="text-gray-600">{item.institution_name}</div>}
                    {item.physician_name && <div className="text-gray-500">{item.physician_name}</div>}
                    {item.reason && <div className="text-gray-600 mt-1 line-clamp-2">{item.reason}</div>}
                    {item.status === 'completed' && (
                      <div className="mt-2 bg-white rounded p-2 border text-gray-700">
                        {item.external_findings || item.response || (item.agreement ? `결과: ${item.agreement}` : '')}
                        {item.comment && <div className="text-gray-500 mt-1">{item.comment}</div>}
                      </div>
                    )}
                    {item.portal_url && item.status !== 'completed' && (
                      <button onClick={() => navigator.clipboard.writeText(window.location.origin + item.portal_url)}
                        className="mt-2 text-blue-600 hover:underline text-[10px]">포털 링크 복사</button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Type Selection */}
        {step === 'type' && (
          <div className="p-4 space-y-3">
            <h4 className="font-semibold text-sm mb-3">새 협진 요청</h4>
            {[
              { key: 'second', icon: '🩺', title: '세컨드 오피니언', desc: '내부/외부 전문의 자문' },
              { key: 'external', icon: '🏥', title: '외부 판독 의뢰', desc: '기관 위탁 정식 의뢰' },
              { key: 'peer', icon: '👥', title: '피어 리뷰', desc: '내부 동료 품질 검토' },
            ].map(t => (
              <button key={t.key} onClick={() => { setStep(t.key as any); setForm({ attachFindings: true }); }}
                className="w-full text-left p-4 rounded-xl border hover:border-blue-400 hover:bg-blue-50 transition">
                <div className="flex items-center gap-3">
                  <span className="text-2xl">{t.icon}</span>
                  <div>
                    <div className="font-semibold text-sm">{t.title}</div>
                    <div className="text-xs text-gray-500">{t.desc}</div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}

        {/* Second Opinion Form */}
        {step === 'second' && (
          <div className="p-4 space-y-3">
            <h4 className="font-semibold text-sm">🩺 세컨드 오피니언</h4>
            <div>
              <label className="text-xs font-medium text-gray-600">승인 기관</label>
              <select className="w-full border rounded-lg px-3 py-2 mt-1 text-sm"
                onChange={e => { const a = accounts.find(x => x.id === e.target.value); if (a) setForm({...form, email: a.physician_email}); }} defaultValue="">
                <option value="">직접 입력...</option>
                {accounts.map(a => <option key={a.id} value={a.id}>{a.institution_name} — {a.physician_name}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-600">이메일</label>
              <input type="email" className="w-full border rounded-lg px-3 py-2 mt-1 text-sm" placeholder="specialist@hospital.com"
                value={form.email || ''} onChange={e => setForm({...form, email: e.target.value})} />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-600">질문/자문 내용</label>
              <textarea rows={4} className="w-full border rounded-lg px-3 py-2 mt-1 text-sm" placeholder="자문 요청 내용..."
                value={form.question || ''} onChange={e => setForm({...form, question: e.target.value})} />
            </div>
            <label className="flex items-center gap-2 text-xs text-gray-600">
              <input type="checkbox" checked={form.attachFindings ?? true} onChange={e => setForm({...form, attachFindings: e.target.checked})} />
              현재 소견/결론 자동 첨부
            </label>
            <div className="flex items-center gap-2">
              <label className="text-xs font-medium text-gray-600">긴급도</label>
              {['routine', 'urgent', 'stat'].map(u => (
                <button key={u} onClick={() => setForm({...form, urgency: u})}
                  className={`px-2 py-1 rounded text-xs ${(form.urgency || 'routine') === u ? 'bg-blue-600 text-white' : 'bg-gray-100'}`}>
                  {u === 'routine' ? '일반' : u === 'urgent' ? '긴급' : 'STAT'}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* External Consult Form */}
        {step === 'external' && (
          <div className="p-4 space-y-3">
            <h4 className="font-semibold text-sm">🏥 외부 판독 의뢰</h4>
            <div>
              <label className="text-xs font-medium text-gray-600">승인 기관</label>
              <select className="w-full border rounded-lg px-3 py-2 mt-1 text-sm"
                onChange={e => { const a = accounts.find(x => x.id === e.target.value); if (a) setForm({...form, institution: a.institution_name, physician: a.physician_name, email: a.physician_email}); }} defaultValue="">
                <option value="">직접 입력...</option>
                {accounts.map(a => <option key={a.id} value={a.id}>{a.institution_name} — {a.physician_name}</option>)}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-xs font-medium text-gray-600">기관</label>
                <input className="w-full border rounded-lg px-2 py-1.5 mt-1 text-sm" value={form.institution || ''} onChange={e => setForm({...form, institution: e.target.value})} />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600">판독의</label>
                <input className="w-full border rounded-lg px-2 py-1.5 mt-1 text-sm" value={form.physician || ''} onChange={e => setForm({...form, physician: e.target.value})} />
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-600">이메일</label>
              <input type="email" className="w-full border rounded-lg px-3 py-2 mt-1 text-sm" value={form.email || ''} onChange={e => setForm({...form, email: e.target.value})} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-xs font-medium text-gray-600">유형</label>
                <select className="w-full border rounded-lg px-2 py-1.5 mt-1 text-sm" value={form.consult_type || 'external_read'} onChange={e => setForm({...form, consult_type: e.target.value})}>
                  <option value="external_read">외부 판독</option>
                  <option value="subspecialty">세부전공</option>
                  <option value="teleradiology">원격판독</option>
                </select>
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600">긴급도</label>
                <select className="w-full border rounded-lg px-2 py-1.5 mt-1 text-sm" value={form.urgency || 'routine'} onChange={e => setForm({...form, urgency: e.target.value})}>
                  <option value="routine">일반 (7일)</option>
                  <option value="urgent">긴급 (24시간)</option>
                  <option value="stat">STAT</option>
                </select>
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-600">의뢰 사유</label>
              <textarea rows={3} className="w-full border rounded-lg px-3 py-2 mt-1 text-sm" placeholder="의뢰 사유..."
                value={form.reason || ''} onChange={e => setForm({...form, reason: e.target.value})} />
            </div>
            <label className="flex items-center gap-2 text-xs text-gray-600">
              <input type="checkbox" checked={form.attachFindings ?? true} onChange={e => setForm({...form, attachFindings: e.target.checked})} />
              현재 소견/결론 자동 첨부
            </label>
            <div className="text-[10px] text-gray-400 bg-gray-50 rounded p-2">
              의뢰 전송 시 외부 기관에 포털 링크가 이메일로 발송됩니다. 영상 접근 권한: 7일간 유효.
            </div>
          </div>
        )}

        {/* Peer Review Form */}
        {step === 'peer' && (
          <div className="p-4 space-y-3">
            <h4 className="font-semibold text-sm">👥 피어 리뷰</h4>
            <div>
              <label className="text-xs font-medium text-gray-600">리뷰어 (비워두면 랜덤 배정)</label>
              <input className="w-full border rounded-lg px-3 py-2 mt-1 text-sm" placeholder="username"
                value={form.reviewer || ''} onChange={e => setForm({...form, reviewer: e.target.value})} />
            </div>
            <p className="text-xs text-gray-400">판독 완료(final) 상태의 리포트에 대해 동료 검토를 요청합니다.</p>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-3 border-t bg-gray-50">
        {step === 'list' ? (
          <button onClick={() => setStep('type')}
            className="w-full bg-blue-600 text-white py-2.5 rounded-lg text-sm font-semibold hover:bg-blue-700 transition">
            + 새 협진 요청
          </button>
        ) : step === 'type' ? (
          <button onClick={() => setStep('list')}
            className="w-full border py-2.5 rounded-lg text-sm font-medium hover:bg-gray-100 transition">
            ← 이력으로 돌아가기
          </button>
        ) : (
          <div className="flex gap-2">
            <button onClick={() => setStep('type')}
              className="flex-1 border py-2.5 rounded-lg text-sm font-medium hover:bg-gray-100">← 이전</button>
            <button onClick={submit} disabled={submitting}
              className="flex-1 bg-blue-600 text-white py-2.5 rounded-lg text-sm font-semibold hover:bg-blue-700 disabled:opacity-50">
              {submitting ? '전송 중...' : '요청 전송'}
            </button>
          </div>
        )}
      </div>

      {/* Toast */}
      {toast && (
        <div className="absolute bottom-16 left-4 right-4 bg-gray-900 text-white px-4 py-2 rounded-lg text-xs text-center shadow-lg">
          {toast}
        </div>
      )}
    </div>
  );
}
