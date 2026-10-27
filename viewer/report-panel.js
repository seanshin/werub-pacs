/**
 * OpenPACS Report Panel
 * Injected into OHIF Viewer — adds a reading report sidebar.
 * Detects StudyInstanceUID from URL and loads/creates reports via API.
 */
(function () {
  'use strict';

  const API = '/pacs-api/api/v1';
  let panel = null;
  let currentStudyUID = null;
  let currentReport = null;
  let token = localStorage.getItem('pacs_token');
  let templates = [];

  // ── API Helpers ──
  async function api(path, opts = {}) {
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(`${API}${path}`, { ...opts, headers: { ...headers, ...opts.headers } });
    if (res.status === 401) { showLogin(); return null; }
    return res.ok ? res.json() : null;
  }

  // ── Study UID Detection ──
  function getStudyUID() {
    const params = new URLSearchParams(window.location.search);
    return params.get('StudyInstanceUIDs');
  }

  // ── Panel HTML ──
  function createPanel() {
    const el = document.createElement('div');
    el.id = 'openpacs-report-panel';
    el.innerHTML = `
      <style>
        #openpacs-report-panel {
          position: fixed; top: 0; right: 0; width: 400px; height: 100vh;
          background: #1a1a2e; color: #e0e0e0; z-index: 999999;
          display: none; flex-direction: column; font-family: -apple-system, 'Noto Sans KR', sans-serif;
          box-shadow: -4px 0 20px rgba(0,0,0,0.7); font-size: 13px;
          transition: transform 0.3s; overflow: hidden;
        }
        #openpacs-report-panel.open { display: flex; }
        .rp-header { padding: 12px 16px; background: #16213e; border-bottom: 1px solid #333;
          display: flex; justify-content: space-between; align-items: center; }
        .rp-header h3 { margin: 0; font-size: 14px; font-weight: 600; }
        .rp-body { flex: 1; overflow-y: auto; padding: 16px; }
        .rp-field { margin-bottom: 12px; }
        .rp-field label { display: block; font-size: 11px; color: #888; margin-bottom: 4px; font-weight: 500; }
        .rp-field textarea, .rp-field input, .rp-field select {
          width: 100%; background: #0f1629; border: 1px solid #333; border-radius: 4px;
          color: #e0e0e0; padding: 8px; font-size: 13px; resize: vertical;
        }
        .rp-field textarea:focus, .rp-field input:focus { border-color: #2563eb; outline: none; }
        .rp-info { background: #0f1629; border-radius: 4px; padding: 8px 10px; margin-bottom: 12px; font-size: 11px; color: #888; }
        .rp-info span { color: #ccc; }
        .rp-footer { padding: 12px 16px; border-top: 1px solid #333; display: flex; gap: 8px; }
        .rp-btn { padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: 600; }
        .rp-btn-primary { background: #2563eb; color: white; }
        .rp-btn-primary:hover { background: #1d4ed8; }
        .rp-btn-success { background: #16a34a; color: white; }
        .rp-btn-success:hover { background: #15803d; }
        .rp-btn-outline { background: transparent; color: #888; border: 1px solid #444; }
        .rp-btn-outline:hover { color: #ccc; border-color: #666; }
        .rp-status { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
        .rp-status-draft { background: #1e3a5f; color: #60a5fa; }
        .rp-status-final { background: #14532d; color: #4ade80; }
        .rp-status-unread { background: #422006; color: #fbbf24; }
        .rp-template-btn { background: #1e293b; border: 1px solid #334155; color: #94a3b8;
          padding: 4px 8px; border-radius: 4px; font-size: 11px; cursor: pointer; margin: 2px; }
        .rp-template-btn:hover { background: #334155; color: #e2e8f0; }
        .rp-macro { color: #60a5fa; cursor: pointer; font-size: 11px; }
        .rp-macro:hover { text-decoration: underline; }
        .rp-login { padding: 20px; }
        .rp-login input { margin-bottom: 8px; }
        #openpacs-toggle-btn {
          position: fixed; bottom: 20px; right: 20px; z-index: 99999;
          background: #2563eb; color: white; border: none; border-radius: 50px;
          padding: 12px 24px; font-size: 14px; font-weight: 700; cursor: pointer;
          box-shadow: 0 4px 16px rgba(37,99,235,0.6); letter-spacing: 0.5px;
        }
        #openpacs-toggle-btn:hover { background: #1d4ed8; transform: scale(1.05); }
        #openpacs-toggle-btn.has-report { background: #16a34a; box-shadow: 0 4px 16px rgba(22,163,74,0.6); }
      </style>

      <div class="rp-header">
        <h3>📋 판독 리포트</h3>
        <button onclick="OpenPACSReport.close()" class="rp-btn rp-btn-outline" style="padding:4px 8px;">✕</button>
      </div>

      <div class="rp-body" id="rp-content">
        <p style="color:#666; text-align:center; margin-top:40px;">Study를 선택하세요</p>
      </div>

      <div class="rp-footer" id="rp-footer" style="display:none;">
        <button onclick="OpenPACSReport.save()" class="rp-btn rp-btn-primary" style="flex:1;">임시 저장</button>
        <button onclick="OpenPACSReport.sign()" class="rp-btn rp-btn-success" style="flex:1;">서명 (Ctrl+Enter)</button>
      </div>
    `;
    document.body.appendChild(el);

    // Toggle button
    const btn = document.createElement('button');
    btn.id = 'openpacs-toggle-btn';
    btn.textContent = '📋 판독';
    btn.onclick = () => togglePanel();
    document.body.appendChild(btn);

    // Keyboard shortcut
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); OpenPACSReport.sign(); }
    });

    return el;
  }

  function togglePanel() {
    if (!panel) panel = createPanel();
    panel.classList.toggle('open');
    const uid = getStudyUID();
    if (uid && uid !== currentStudyUID) loadStudy(uid);
  }

  // ── Login ──
  function showLogin() {
    const content = document.getElementById('rp-content');
    content.innerHTML = `
      <div class="rp-login">
        <p style="margin-bottom:12px; font-weight:600;">로그인이 필요합니다</p>
        <input type="text" id="rp-username" placeholder="사용자명" />
        <input type="password" id="rp-password" placeholder="비밀번호" />
        <button onclick="OpenPACSReport.login()" class="rp-btn rp-btn-primary" style="width:100%; margin-top:4px;">로그인</button>
        <div style="margin-top:8px; font-size:11px; color:#666;">
          <span class="rp-macro" onclick="document.getElementById('rp-username').value='admin';document.getElementById('rp-password').value=''">admin</span> |
          <span class="rp-macro" onclick="document.getElementById('rp-username').value='dr.kim';document.getElementById('rp-password').value=''">dr.kim</span>
        </div>
      </div>
    `;
  }

  async function doLogin() {
    const u = document.getElementById('rp-username').value;
    const p = document.getElementById('rp-password').value;
    const res = await fetch(`${API}/auth/login`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: u, password: p }),
    });
    if (res.ok) {
      const data = await res.json();
      token = data.access_token;
      localStorage.setItem('pacs_token', token);
      const uid = getStudyUID();
      if (uid) loadStudy(uid);
    }
  }

  // ── Load Study ──
  async function loadStudy(studyUID) {
    currentStudyUID = studyUID;
    const content = document.getElementById('rp-content');
    const footer = document.getElementById('rp-footer');
    content.innerHTML = '<p style="color:#666; text-align:center; margin-top:40px;">로딩 중...</p>';

    // Load templates
    if (templates.length === 0) {
      const tRes = await api('/templates');
      if (tRes) templates = tRes.templates;
    }

    // Check existing report
    const reports = await api(`/reports?study_uid=${studyUID}`);
    if (!reports) return;

    if (reports.results && reports.results.length > 0) {
      currentReport = reports.results[0];
      renderReport();
    } else {
      currentReport = null;
      renderNewReport(studyUID);
    }
    footer.style.display = 'flex';
  }

  // ── Render Existing Report ──
  function renderReport() {
    const r = currentReport;
    const statusClass = { draft: 'rp-status-draft', final: 'rp-status-final', preliminary: 'rp-status-draft' };
    const statusLabel = { draft: '작성 중', final: '판독 완료', preliminary: '예비 판독', unread: '미판독' };

    document.getElementById('rp-content').innerHTML = `
      <div class="rp-info">
        <span class="rp-status ${statusClass[r.status] || 'rp-status-unread'}">${statusLabel[r.status] || r.status}</span>
        ${r.signed_by_name ? `<span style="margin-left:8px;">판독의: ${r.signed_by_name}</span>` : ''}
        <br/><span>${r.patient_name || ''} (${r.patient_id})</span> · <span>${r.modality || ''}</span>
      </div>

      ${r.status === 'final' ? `
        <div class="rp-field"><label>소견</label><div style="background:#0f1629;padding:8px;border-radius:4px;white-space:pre-wrap;">${r.findings || '-'}</div></div>
        <div class="rp-field"><label>결론</label><div style="background:#0f1629;padding:8px;border-radius:4px;white-space:pre-wrap;color:#4ade80;">${r.impression || '-'}</div></div>
        ${r.recommendation ? `<div class="rp-field"><label>권고</label><div style="background:#0f1629;padding:8px;border-radius:4px;">${r.recommendation}</div></div>` : ''}
      ` : `
        <div class="rp-field"><label>소견 (Findings)</label>
          <textarea id="rp-findings" rows="6">${r.findings || ''}</textarea>
        </div>
        <div class="rp-field"><label>결론 (Impression)</label>
          <textarea id="rp-impression" rows="3">${r.impression || ''}</textarea>
        </div>
        <div class="rp-field"><label>권고 사항</label>
          <textarea id="rp-recommendation" rows="2">${r.recommendation || ''}</textarea>
        </div>
        <div class="rp-field"><label>긴급도</label>
          <select id="rp-urgency">
            <option value="normal" ${r.urgency === 'normal' ? 'selected' : ''}>정상</option>
            <option value="non_urgent" ${r.urgency === 'non_urgent' ? 'selected' : ''}>비긴급 이상</option>
            <option value="urgent" ${r.urgency === 'urgent' ? 'selected' : ''}>긴급</option>
          </select>
        </div>
        ${renderMacros()}
      `}
    `;

    const footer = document.getElementById('rp-footer');
    if (r.status === 'final') {
      footer.innerHTML = `<button onclick="OpenPACSReport.addendum()" class="rp-btn rp-btn-outline" style="flex:1;">수정본 추가</button>`;
    }
  }

  // ── Render New Report Form ──
  function renderNewReport(studyUID) {
    // Match template by getting study info
    const templateBtns = templates.map(t =>
      `<button class="rp-template-btn" onclick="OpenPACSReport.applyTemplate('${t.id}')">${t.modality} ${t.name.split('(')[0].trim()}</button>`
    ).join('');

    document.getElementById('rp-content').innerHTML = `
      <div class="rp-info">
        <span class="rp-status rp-status-unread">새 리포트</span>
        <span style="margin-left:8px; font-size:11px;">Study: ${studyUID.substr(0, 30)}...</span>
      </div>

      ${templateBtns ? `<div class="rp-field"><label>템플릿 선택</label><div>${templateBtns}</div></div>` : ''}

      <div class="rp-field"><label>소견 (Findings)</label>
        <textarea id="rp-findings" rows="6" placeholder="소견을 입력하세요..."></textarea>
      </div>
      <div class="rp-field"><label>결론 (Impression)</label>
        <textarea id="rp-impression" rows="3" placeholder="결론을 입력하세요..."></textarea>
      </div>
      <div class="rp-field"><label>권고 사항</label>
        <textarea id="rp-recommendation" rows="2" placeholder="권고 사항 (선택)"></textarea>
      </div>
      <div class="rp-field"><label>긴급도</label>
        <select id="rp-urgency">
          <option value="normal">정상</option>
          <option value="non_urgent">비긴급 이상</option>
          <option value="urgent">긴급</option>
        </select>
      </div>
      ${renderMacros()}
    `;
  }

  function renderMacros() {
    const matchedTemplate = templates.find(t => {
      // Simple matching - could be improved
      return true;
    });
    if (!matchedTemplate || !matchedTemplate.macros) return '';

    const macroHtml = Object.entries(matchedTemplate.macros).map(([key, val]) =>
      `<span class="rp-macro" onclick="OpenPACSReport.insertMacro('${val}')" title="${val}">${key}</span>`
    ).join(' · ');

    return `<div class="rp-field"><label>단축어</label><div>${macroHtml}</div></div>`;
  }

  // ── Apply Template ──
  async function applyTemplate(templateId) {
    const t = templates.find(x => x.id === templateId);
    if (!t) return;

    const findingsEl = document.getElementById('rp-findings');
    const impressionEl = document.getElementById('rp-impression');
    if (findingsEl && t.normal_template) findingsEl.value = t.normal_template;
    if (impressionEl && t.impression_template) impressionEl.value = t.impression_template;
  }

  function insertMacro(text) {
    const el = document.getElementById('rp-findings');
    if (el) {
      const pos = el.selectionStart;
      el.value = el.value.substring(0, pos) + text + el.value.substring(pos);
      el.focus();
    }
  }

  // ── Save ──
  async function save() {
    const findings = document.getElementById('rp-findings')?.value;
    const impression = document.getElementById('rp-impression')?.value;
    const recommendation = document.getElementById('rp-recommendation')?.value;
    const urgency = document.getElementById('rp-urgency')?.value;

    if (currentReport) {
      // Update existing
      await api(`/reports/${currentReport.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ findings, impression, recommendation, urgency }),
      });
    } else {
      // Create new
      const res = await api('/reports', {
        method: 'POST',
        body: JSON.stringify({
          study_instance_uid: currentStudyUID,
          patient_id: '-',
          findings, impression, recommendation, urgency,
        }),
      });
      if (res) currentReport = res;
    }
    showToast('임시 저장됨');
  }

  // ── Sign ──
  async function sign() {
    await save(); // Save first
    if (!currentReport) return;

    if (!currentReport.findings || !currentReport.impression) {
      showToast('소견과 결론을 입력해주세요', 'error');
      return;
    }

    const res = await api(`/reports/${currentReport.id}/sign`, { method: 'POST' });
    if (res) {
      currentReport = res;
      renderReport();
      showToast('판독 서명 완료!', 'success');
      const btn = document.getElementById('openpacs-toggle-btn');
      if (btn) btn.classList.add('has-report');
    }
  }

  // ── Addendum ──
  async function addendum() {
    if (!currentReport) return;
    const res = await api(`/reports/${currentReport.id}/addendum`, {
      method: 'POST',
      body: JSON.stringify({ findings: '', impression: '' }),
    });
    if (res) { currentReport = res; renderReport(); }
  }

  // ── Toast ──
  function showToast(msg, type = 'info') {
    const colors = { info: '#2563eb', success: '#16a34a', error: '#dc2626' };
    const toast = document.createElement('div');
    toast.style.cssText = `position:fixed;bottom:20px;right:400px;background:${colors[type]};color:white;
      padding:10px 20px;border-radius:6px;font-size:13px;z-index:10001;box-shadow:0 4px 12px rgba(0,0,0,0.3);`;
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2500);
  }

  // ── URL Change Detection ──
  let lastHref = '';
  setInterval(() => {
    if (window.location.href !== lastHref) {
      lastHref = window.location.href;
      const uid = getStudyUID();
      if (uid && panel?.classList.contains('open')) loadStudy(uid);
      // Update toggle button
      const btn = document.getElementById('openpacs-toggle-btn');
      if (btn) btn.style.display = 'block';
    }
  }, 1500);

  // ── Public API ──
  window.OpenPACSReport = {
    toggle: togglePanel,
    close: () => panel?.classList.remove('open'),
    save, sign, addendum,
    login: doLogin,
    applyTemplate,
    insertMacro,
  };

  // ── Init ──
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => createPanel());
  } else {
    createPanel();
  }
})();
