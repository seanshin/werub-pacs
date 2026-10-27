'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import { apiFetch, getUser, login } from '@/lib/api';
import { getModalityRenderability } from '@/lib/dicom-renderability';
import { Report, Template, StudyInfo } from './types';

export function useReadingView() {
  const params = useSearchParams();
  const studyUID = params.get('study') || '';
  const mode = params.get('mode') || 'dual';
  const [user, setUser] = useState(getUser());
  const [report, setReport] = useState<Report | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [studyInfo, setStudyInfo] = useState<StudyInfo | null>(null);
  const [findings, setFindings] = useState('');
  const [impression, setImpression] = useState('');
  const [recommendation, setRecommendation] = useState('');
  const [urgency, setUrgency] = useState('normal');
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState('');
  const [loginForm, setLoginForm] = useState({ username: '', password: '' });
  const [viewerOpened, setViewerOpened] = useState(false);
  const [consultOpen, setConsultOpen] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [activeTab, setActiveTab] = useState<'report' | 'history'>('report');
  const findingsRef = useRef<HTMLTextAreaElement>(null);

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(''), 3000); };

  const [priorStudies, setPriorStudies] = useState<{ study_instance_uid: string; study_date: string; modality: string; study_description: string }[]>([]);

  const loadData = useCallback(async () => {
    if (!studyUID) return;
    const [rpt, tmpl, queue, priors] = await Promise.all([
      apiFetch<{ results: Report[] }>(`/api/v1/reports?study_uid=${studyUID}`).catch(() => null),
      apiFetch<{ templates: Template[] }>('/api/v1/templates').catch(() => null),
      apiFetch<{ queue: any[] }>(`/api/v1/dashboard/reading-queue?study_uid=${studyUID}`).catch(() => null),
      apiFetch<{ priors: any[] }>(`/api/v1/studies/${studyUID}/priors?max_results=5&same_modality=true`).catch(() => null),
    ]);
    if (priors?.priors) setPriorStudies(priors.priors);
    if (tmpl) setTemplates(tmpl.templates);
    if (queue?.queue?.length) {
      // match the clicked study (backend filters by study_uid; .find is a safety net)
      const s = queue.queue.find((q: any) => q.study_instance_uid === studyUID) || queue.queue[0];
      setStudyInfo({
        patient_name: s.patient_name, patient_id: s.patient_id,
        modality: s.modality, study_description: s.study_description,
        study_date: s.study_date, accession_number: s.accession_number,
        series_count: s.series_count,
        sla_minutes: s.sla_minutes, sla_level: s.sla_level,
      });
    }
    if (rpt?.results?.length) {
      const r = rpt.results[0];
      setReport(r); setFindings(r.findings || ''); setImpression(r.impression || '');
      setRecommendation(r.recommendation || ''); setUrgency(r.urgency || 'normal');
    }
  }, [studyUID]);

  useEffect(() => { if (user) loadData(); }, [user, loadData]);

  // Poll for AI draft report updates from viewer (every 2s)
  const lastReportSig = useRef('');
  useEffect(() => {
    if (!studyUID) return;
    const interval = setInterval(async () => {
      try {
        const rpt = await apiFetch<{ results: any[] }>(`/api/v1/reports?study_uid=${studyUID}&limit=1`);
        if (rpt?.results?.length) {
          const r = rpt.results[0];
          const sig = `${r.findings || ''}|${r.impression || ''}|${r.recommendation || ''}`;
          if (sig !== lastReportSig.current && sig !== '||') {
            const isNew = lastReportSig.current !== '';
            lastReportSig.current = sig;
            if (isNew) {
              setFindings(r.findings || '');
              setImpression(r.impression || '');
              setRecommendation(r.recommendation || '');
              showToast('AI 판독 초안이 반영되었습니다');
            } else {
              lastReportSig.current = sig;
            }
          }
        }
      } catch {}
    }, 2000);
    return () => clearInterval(interval);
  }, [studyUID]);

  const handleLogin = async () => {
    try { await login(loginForm.username, loginForm.password); setUser(getUser()); } catch {}
  };

  const [viewerWarning, setViewerWarning] = useState<{ type: 'werub' | 'ohif' } | null>(null);

  const openViewer = (type: 'werub' | 'ohif') => {
    const ri = getModalityRenderability(studyInfo?.modality);
    if (!ri.renderable) {
      setViewerWarning({ type });
      return;
    }
    doOpenViewer(type);
  };

  const doOpenViewer = (type: 'werub' | 'ohif', withPrior = false) => {
    setViewerWarning(null);
    let uids = studyUID;
    if (withPrior && priorStudies.length > 0) {
      uids += ',' + priorStudies[0].study_instance_uid;
    }
    const url = type === 'werub'
      ? `/werub-viewer/viewer?StudyInstanceUIDs=${uids}`
      : `/viewer/?StudyInstanceUIDs=${uids}`;
    const w = window.open(url, `${type}-viewer`, 'width=1400,height=900,menubar=no,toolbar=no,location=no,status=no');
    if (w) { setViewerOpened(true); w.focus(); }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      if (report) {
        await apiFetch(`/api/v1/reports/${report.id}`, {
          method: 'PATCH', body: JSON.stringify({ findings, impression, recommendation, urgency }),
        });
      } else {
        const res = await apiFetch<Report>('/api/v1/reports', {
          method: 'POST',
          body: JSON.stringify({ study_instance_uid: studyUID, patient_id: studyInfo?.patient_id || '-', findings, impression, recommendation, urgency }),
        });
        if (res) setReport(res);
      }
      setDirty(false);
      showToast('저장 완료');
    } catch (e: any) { showToast(e.message); }
    setSaving(false);
  };

  /* ── Next study navigation ── */
  const [nextStudyUID, setNextStudyUID] = useState<string | null>(null);
  const [showNextModal, setShowNextModal] = useState(false);

  const fetchNextStudy = useCallback(async () => {
    try {
      const data = await apiFetch<{ queue: any[] }>('/api/v1/dashboard/reading-queue?status=unread');
      const next = data.queue?.find((s: any) => s.study_instance_uid !== studyUID);
      setNextStudyUID(next?.study_instance_uid || null);
    } catch {}
  }, [studyUID]);

  useEffect(() => { if (user) fetchNextStudy(); }, [user, fetchNextStudy]);

  const goToNextStudy = () => {
    if (nextStudyUID) window.location.href = `/pacs-admin/reading/view?study=${nextStudyUID}&mode=${mode}`;
    else window.location.href = '/pacs-admin/reading';
  };

  const handleSign = async () => {
    await handleSave();
    if (!report) return;
    if (!findings || !impression) { showToast('소견과 결론을 입력하세요'); return; }
    const res = await apiFetch<Report>(`/api/v1/reports/${report.id}/sign`, { method: 'POST' });
    if (res) {
      setReport(res);
      await fetchNextStudy();
      setShowNextModal(true);
    }
  };

  const applyTemplate = (t: Template) => {
    if (t.normal_template) { setFindings(t.normal_template); setDirty(true); }
    if (t.impression_template) { setImpression(t.impression_template); setDirty(true); }
    showToast(`템플릿 "${t.name}" 적용됨`);
    findingsRef.current?.focus();
  };

  const insertMacro = (text: string) => {
    setFindings(prev => prev + text);
    setDirty(true);
    findingsRef.current?.focus();
  };

  /* ── Keyboard shortcuts ── */
  const [showShortcuts, setShowShortcuts] = useState(false);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const isInput = target.tagName === 'TEXTAREA' || target.tagName === 'INPUT';

      if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); handleSign(); return; }
      if (e.ctrlKey && e.key === 's') { e.preventDefault(); handleSave(); return; }

      if (isInput) return;

      if (e.key === '?') { e.preventDefault(); setShowShortcuts(s => !s); return; }
      if (e.key === 'Escape') { setShowShortcuts(false); setShowNextModal(false); return; }
      if (e.key === 'n' || e.key === 'N') { e.preventDefault(); goToNextStudy(); return; }
      if (e.key === 'q' || e.key === 'Q') { e.preventDefault(); window.location.href = '/pacs-admin/reading'; return; }
      if (e.key === 'v' || e.key === 'V') { e.preventDefault(); openViewer('werub'); return; }
      if (e.key === 'f' || e.key === 'F') { e.preventDefault(); findingsRef.current?.focus(); return; }
      if (e.key >= '1' && e.key <= '9') {
        const idx = parseInt(e.key) - 1;
        if (templates[idx]) { e.preventDefault(); applyTemplate(templates[idx]); return; }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [handleSign, handleSave, goToNextStudy, openViewer, applyTemplate, templates]);

  const isFinal = report?.status === 'final';
  const viewerUrl = `/viewer/?StudyInstanceUIDs=${studyUID}`;
  const allMacros = templates.flatMap(t => Object.entries(t.macros || {}).map(([k, v]) => ({ key: k, value: v, templateId: t.id })));

  return {
    // Params
    studyUID, mode,
    // Auth
    user, loginForm, setLoginForm, handleLogin,
    // Data
    report, templates, studyInfo, priorStudies,
    // Editor state
    findings, setFindings, impression, setImpression,
    recommendation, setRecommendation, urgency, setUrgency,
    dirty, setDirty, activeTab, setActiveTab, findingsRef,
    // Actions
    saving, handleSave, handleSign, showToast,
    applyTemplate, insertMacro,
    // Viewer
    viewerOpened, viewerWarning, setViewerWarning, openViewer, doOpenViewer, viewerUrl,
    // Navigation
    nextStudyUID, showNextModal, setShowNextModal, goToNextStudy,
    // Consult
    consultOpen, setConsultOpen,
    // Shortcuts
    showShortcuts, setShowShortcuts,
    // Toast
    toast,
    // Derived
    isFinal, allMacros,
  };
}
