// WeRU.B Viewer Configuration v2.0
// Based on OHIF Viewer (MIT License) - https://ohif.org
// Fully separate from existing OHIF installation

// Report Panel is now built-in as OHIF Extension (werub-report)
// Old vanilla JS injection removed — see extensions/werub-report/

window.config = {
  routerBasename: '/werub-viewer',
  extensions: [],
  modes: [],

  // =========================================================================
  // WeRU.B Branding & White Labeling
  // =========================================================================
  whiteLabeling: {
    createLogoComponentFn: function(React) {
      return React.createElement('a', {
        href: '/werub-viewer/',
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          textDecoration: 'none',
          cursor: 'pointer',
        }
      },
        // Logo icon
        React.createElement('div', {
          style: {
            width: '32px',
            height: '32px',
            borderRadius: '8px',
            background: 'linear-gradient(135deg, #3B82F6 0%, #1D4ED8 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 2px 8px rgba(59,130,246,0.4)',
          }
        },
          React.createElement('span', {
            style: { color: '#fff', fontSize: '16px', fontWeight: '800', fontFamily: 'system-ui' }
          }, 'W')
        ),
        // Logo text
        React.createElement('div', {
          style: { display: 'flex', flexDirection: 'column', lineHeight: '1.1' }
        },
          React.createElement('span', {
            style: {
              color: '#F8FAFC',
              fontSize: '15px',
              fontWeight: '700',
              fontFamily: 'system-ui,-apple-system,sans-serif',
              letterSpacing: '0.5px',
            }
          }, 'WeRU.B'),
          React.createElement('span', {
            style: {
              color: '#64748B',
              fontSize: '9px',
              fontWeight: '500',
              fontFamily: 'system-ui',
              letterSpacing: '1.5px',
              textTransform: 'uppercase',
            }
          }, 'Medical Viewer')
        )
      );
    },
  },

  // =========================================================================
  // UI Customization
  // =========================================================================
  customizationService: {
    // Viewport overlay - Korean clinical format
    'ohif.overlayItem': {
      topLeft: ['PatientName', 'PatientID', 'PatientBirthDate', 'PatientSex'],
      topRight: ['InstitutionName', 'StudyDate', 'StudyTime', 'StudyDescription'],
      bottomLeft: ['SeriesNumber', 'SeriesDescription', 'InstanceNumber', 'SliceThickness'],
      bottomRight: ['WindowCenter', 'WindowWidth', 'Zoom', 'SliceLocation'],
    },

    // About dialog — handled by source-level AboutModalDefault component

    // W/L presets — Korean clinical defaults per modality
    'cornerstone.windowLevelPresets': {
      CT: [
        { description: '연부조직', window: '400', level: '40' },
        { description: '폐', window: '1500', level: '-600' },
        { description: '뇌', window: '80', level: '40' },
        { description: '골', window: '2500', level: '480' },
        { description: '복부', window: '350', level: '40' },
        { description: '간', window: '150', level: '90' },
        { description: '종격동', window: '350', level: '50' },
      ],
      MR: [
        { description: 'MR 기본', window: '400', level: '200' },
        { description: 'MR 뇌', window: '250', level: '125' },
        { description: 'MR 척추', window: '600', level: '300' },
      ],
      US: [
        { description: 'US 기본', window: '255', level: '128' },
      ],
      CR: [
        { description: 'CR 기본', window: '2048', level: '1024' },
        { description: '흉부', window: '4096', level: '1024' },
      ],
      DX: [
        { description: 'DX 기본', window: '2048', level: '1024' },
        { description: '흉부', window: '4096', level: '1024' },
      ],
      MG: [
        { description: 'MG 기본', window: '4096', level: '2048' },
      ],
      PT: [
        { description: 'PET 기본', window: '5', level: '2.5' },
        { description: 'SUV 3', window: '3', level: '1.5' },
        { description: 'SUV 5', window: '5', level: '2.5' },
        { description: 'SUV 8', window: '8', level: '4' },
      ],
    },
  },

  // =========================================================================
  // Theme & Appearance
  // =========================================================================
  // Custom CSS injected at runtime
  customCSS: `
    /* WeRU.B Custom Theme */

    /* Header bar - darker, more professional */
    .bg-primary-dark, [class*="NavBar"] {
      background: linear-gradient(180deg, #0F172A 0%, #1E293B 100%) !important;
    }

    /* Primary accent color - blue */
    .bg-primary-main, .bg-primary-active,
    [class*="active"][class*="primary"],
    button[class*="primary"] {
      background-color: #2563EB !important;
    }

    /* Hover states */
    .hover\\:bg-primary-main:hover {
      background-color: #1D4ED8 !important;
    }

    /* Selection highlight */
    .border-primary-main, [class*="selected"][class*="border"] {
      border-color: #3B82F6 !important;
    }

    /* Scrollbar styling */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: #1E293B; }
    ::-webkit-scrollbar-thumb { background: #475569; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #64748B; }

    /* Study list - cleaner look */
    [class*="StudyList"] table th {
      font-size: 12px !important;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: #94A3B8 !important;
    }

    /* Fix header/row column alignment on wide screens */
    [class*="StudyList"] table {
      table-layout: fixed !important;
      width: 100% !important;
    }
    [class*="StudyList"] table th,
    [class*="StudyList"] table td {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    /* Column widths: name 15% | mrn 12% | date 15% | desc 20% | mod 8% | acc 15% | inst 5% | arrow 3% */
    [class*="StudyList"] table th:nth-child(1),
    [class*="StudyList"] table td:nth-child(1) { width: 4% !important; }
    [class*="StudyList"] table th:nth-child(2),
    [class*="StudyList"] table td:nth-child(2) { width: 15% !important; }
    [class*="StudyList"] table th:nth-child(3),
    [class*="StudyList"] table td:nth-child(3) { width: 12% !important; }
    [class*="StudyList"] table th:nth-child(4),
    [class*="StudyList"] table td:nth-child(4) { width: 16% !important; }
    [class*="StudyList"] table th:nth-child(5),
    [class*="StudyList"] table td:nth-child(5) { width: 20% !important; }
    [class*="StudyList"] table th:nth-child(6),
    [class*="StudyList"] table td:nth-child(6) { width: 8% !important; }
    [class*="StudyList"] table th:nth-child(7),
    [class*="StudyList"] table td:nth-child(7) { width: 15% !important; }
    [class*="StudyList"] table th:nth-child(8),
    [class*="StudyList"] table td:nth-child(8) { width: 6% !important; }

    /* Tool buttons - softer */
    [class*="ToolbarButton"] {
      border-radius: 8px !important;
      transition: all 0.15s ease !important;
    }
    [class*="ToolbarButton"]:hover {
      background-color: rgba(59, 130, 246, 0.15) !important;
    }

    /* Panel headers */
    [class*="PanelSection"] > div:first-child {
      font-weight: 600 !important;
      letter-spacing: 0.3px;
    }

    /* Viewport border on hover */
    [class*="ViewportPane"]:hover {
      outline: 1px solid rgba(59, 130, 246, 0.3);
    }

    /* Active viewport indicator */
    [class*="ViewportPane"][class*="active"] {
      outline: 2px solid #3B82F6 !important;
    }

    /* Toast notifications */
    .Toastify__toast {
      border-radius: 10px !important;
      font-family: system-ui, -apple-system, sans-serif !important;
    }

    /* Upload button - icon only */
    [class*="StudyListFilter"] .text-primary-active.cursor-pointer {
      background: rgba(37, 99, 235, 0.15);
      border: 1px solid rgba(59, 130, 246, 0.4);
      border-radius: 50%;
      padding: 8px;
      font-size: 0 !important;
      gap: 0 !important;
      transition: all 0.2s;
    }
    [class*="StudyListFilter"] .text-primary-active.cursor-pointer:hover {
      background: rgba(37, 99, 235, 0.3);
      border-color: rgba(59, 130, 246, 0.7);
    }
    [class*="StudyListFilter"] .text-primary-active.cursor-pointer svg {
      width: 18px;
      height: 18px;
      font-size: 18px;
    }

    /* Footer watermark */
    body::after {
      content: 'WeRU.B Medical Viewer';
      position: fixed;
      bottom: 4px;
      right: 12px;
      font-size: 9px;
      color: rgba(100, 116, 139, 0.3);
      font-family: system-ui;
      pointer-events: none;
      z-index: 1;
    }
  `,

  // =========================================================================
  // Functional Settings
  // =========================================================================
  showStudyList: true,
  // Scale decode workers to the client CPU (cores-1, capped at 7) instead of a
  // fixed 3 — faster parallel decode of multi-slice CT/MR on capable reading PCs,
  // while staying modest on low-core machines. (WeRU.B perf #3)
  maxNumberOfWebWorkers: Math.min(
    Math.max((typeof navigator !== 'undefined' && navigator.hardwareConcurrency || 4) - 1, 2),
    7
  ),
  showWarningMessageForCrossOrigin: false,
  investigationalUseDialog: { option: 'never' },
  showCPUFallbackMessage: false,
  showLoadingIndicator: true,
  experimentalStudyBrowserSort: false,
  strictZSpacingForVolumeViewport: true,
  groupEnabledModesFirst: true,
  showPatientInfo: 'visible',
  maxNumRequests: {
    interaction: 100,
    thumbnail: 75,
    prefetch: 50, // raised 25→50: HTTP/2 multiplexing (perf #1) makes more concurrent prefetch efficient → faster volume preload
  },
  showErrorDetails: 'never',

  // Suppress only known-harmless rendering noise. The broad
  // "Cannot read properties of undefined" catch-all was removed (2026-06-06):
  // it masked real bugs (e.g. the SR viewport crash) without any user benefit —
  // this is window.onerror, not the ErrorBoundary toast, so surfacing these
  // only restores console diagnosability and does not add user-visible toasts.
  onError: function(error) {
    var msg = error && error.message || '';
    if (msg.includes('ImageOverlayViewerTool') ||
        msg.includes('extensionDependencies')) {
      console.warn('[WeRU.B] Suppressed (known noise):', msg);
      return true;
    }
    console.error('[WeRU.B] Error:', msg);
    return; // undefined = default behavior
  },

  // Korean language
  language: 'ko-KR',

  // =========================================================================
  // Multi-Monitor Support
  // =========================================================================
  // Usage: append ?multimonitor=dual to URL to activate
  // Each window gets its own OHIF instance, coordinated via cross-window commands
  multimonitor: [
    {
      id: 'dual',
      test: ({ multimonitor }) => multimonitor === 'dual',
      screens: [
        {
          id: 'primary',
          launch: 'source',
          screen: 0,
          location: { width: 1, height: 1, left: 0, top: 0 },
        },
        {
          id: 'secondary',
          screen: 1,
          location: { width: 1, height: 1, left: 0, top: 0 },
          options: 'toolbar=no,menubar=no,location=no',
        },
      ],
    },
    {
      id: 'split',
      test: ({ multimonitor }) => multimonitor === 'split',
      screens: [
        {
          id: 'left',
          launch: 'source',
          screen: 0,
          location: { width: 0.5, height: 1, left: 0, top: 0 },
        },
        {
          id: 'right',
          screen: 0,
          location: { width: 0.5, height: 1, left: 0.5, top: 0 },
          options: 'toolbar=no,menubar=no,location=no',
        },
      ],
    },
  ],

  // =========================================================================
  // DICOMweb Data Source (shared Orthanc - read only)
  // =========================================================================
  defaultDataSourceName: 'dicomweb',
  dataSources: [
    {
      namespace: '@ohif/extension-default.dataSourcesModule.dicomweb',
      sourceName: 'dicomweb',
      configuration: {
        friendlyName: 'WeRU.B PACS',
        name: 'orthanc',
        wadoUriRoot: '/wado',
        qidoRoot: '/dicom-web',
        wadoRoot: '/dicom-web',
        qidoSupportsIncludeField: false,
        supportsReject: false,
        dicomUploadEnabled: true,
        imageRendering: 'wadors',
        thumbnailRendering: 'wadors',
        // Request JPEG 2000 lossless frames via WADO-RS. Storage is uncompressed
        // (Explicit VR LE), so Orthanc transcodes on delivery — frames shrink
        // ~3x (524KB→176KB/slice, measured) with NO quality loss (lossless), and
        // Cornerstone3D decodes J2K natively. Big win for volume load. (perf #4)
        requestTransferSyntaxUID: '1.2.840.10008.1.2.4.90',
        enableStudyLazyLoad: true,
        supportsFuzzyMatching: false,
        supportsWildcard: true,
        omitQuotationForMultipartRequest: true,
        bulkDataURI: {
          // 병리 ANN(Sup222)은 좌표를 bulk data로 저장 → loadAnnotation이 조회하려면 활성 필요(G1 표시 복구).
          enabled: true,
        },
      },
    },
    {
      namespace: '@ohif/extension-default.dataSourcesModule.dicomlocal',
      sourceName: 'dicomlocal',
      configuration: {
        friendlyName: '로컬 파일',
      },
    },
  ],

  // =========================================================================
  // Hotkeys (Korean labels)
  // =========================================================================
  hotkeys: [
    { commandName: 'incrementActiveViewport', label: '다음 뷰포트', keys: ['right'] },
    { commandName: 'decrementActiveViewport', label: '이전 뷰포트', keys: ['left'] },
    { commandName: 'rotateViewportCW', label: '시계방향 회전', keys: ['r'] },
    { commandName: 'flipViewportHorizontal', label: '좌우반전', keys: ['h'] },
    { commandName: 'flipViewportVertical', label: '상하반전', keys: ['v'] },
    { commandName: 'scaleUpViewport', label: '확대', keys: ['='] },
    { commandName: 'scaleDownViewport', label: '축소', keys: ['-'] },
    { commandName: 'fitViewportToWindow', label: '화면 맞춤', keys: ['0'] },
    { commandName: 'resetViewport', label: '초기화', keys: ['space'] },
    { commandName: 'toggleCine', label: '동영상', keys: ['c'] },
    { commandName: 'invertViewport', label: '반전', keys: ['i'] },
    { commandName: 'nextImage', label: '다음 영상', keys: ['down'] },
    { commandName: 'previousImage', label: '이전 영상', keys: ['up'] },
    // W/L presets (숫자 키)
    { commandName: 'setWindowLevelPreset', commandOptions: { presetIndex: 0 }, label: 'W/L 프리셋 1', keys: ['1'] },
    { commandName: 'setWindowLevelPreset', commandOptions: { presetIndex: 1 }, label: 'W/L 프리셋 2', keys: ['2'] },
    { commandName: 'setWindowLevelPreset', commandOptions: { presetIndex: 2 }, label: 'W/L 프리셋 3', keys: ['3'] },
    { commandName: 'setWindowLevelPreset', commandOptions: { presetIndex: 3 }, label: 'W/L 프리셋 4', keys: ['4'] },
    { commandName: 'setWindowLevelPreset', commandOptions: { presetIndex: 4 }, label: 'W/L 프리셋 5', keys: ['5'] },
    // Hanging protocol stages
    { commandName: 'nextStage', label: '다음 레이아웃', keys: ['.'] },
    { commandName: 'previousStage', label: '이전 레이아웃', keys: [','] },
    // Undo/Redo
    { commandName: 'undo', label: '실행취소', keys: ['ctrl+z'] },
    { commandName: 'redo', label: '다시실행', keys: ['ctrl+y'] },
    // 이전검사 원클릭 비교 (viewer-ux B, werub-ai)
    { commandName: 'werubComparePrior', label: '이전검사 비교', keys: ['p'] },
  ],
};

// =========================================================================
// Inject Custom CSS at runtime
// =========================================================================
(function() {
  if (window.config.customCSS) {
    var style = document.createElement('style');
    style.textContent = window.config.customCSS;
    document.head.appendChild(style);
  }
})();

// =========================================================================
// Keyboard shortcuts (runtime — for custom commands not in OHIF registry)
// =========================================================================
(function() {
  document.addEventListener('keydown', function(e) {
    // N key — next unread study
    if (e.key === 'n' && !e.ctrlKey && !e.altKey && !e.metaKey) {
      var tag = e.target && e.target.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      e.preventDefault();
      var params = new URLSearchParams(window.location.search);
      var currentUID = params.get('StudyInstanceUIDs') || '';
      var token = localStorage.getItem('pacs_token');

      fetch('/pacs-api/api/v1/reports/next-unread?current_study_uid=' + currentUID, {
        headers: token ? { 'Authorization': 'Bearer ' + token } : {}
      })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.study_uid) {
          window.location.href = data.viewer_url;
        }
      })
      .catch(function() {});
    }

    // M key — open second viewer window (skip if typing in input/textarea)
    if (e.key === 'm' && !e.ctrlKey && !e.altKey && !e.metaKey) {
      var tag = e.target && e.target.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      var params = new URLSearchParams(window.location.search);
      var studyUIDs = params.get('StudyInstanceUIDs');
      if (!studyUIDs) return;

      e.preventDefault();
      var basePath = window.location.pathname.replace(/\/[^/]*$/, '');
      var url = basePath + '/viewer?StudyInstanceUIDs=' + studyUIDs;
      var sw = window.screen.availWidth;
      var sh = window.screen.availHeight;
      window.open(url, 'werub-secondary',
        'width=' + Math.floor(sw/2) + ',height=' + sh + ',left=' + Math.floor(sw/2) + ',top=0,toolbar=no,menubar=no');
    }
  });
})();

// =========================================================================
// WebSocket Notification Listener
// =========================================================================
(function() {
  var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  var wsBase = protocol + '//' + window.location.host + '/pacs-api/ws/notifications';
  var ws = null;
  var reconnectTimer = null;

  function connect() {
    // A9 fix: the backend requires ?token= and closes with 4001 if absent. The
    // URL had no token → every connect was rejected → reconnect every 5s forever.
    // Read the token per-attempt (it may arrive after page load) and only connect
    // when present; otherwise retry later without hammering the server.
    var token = null;
    try { token = localStorage.getItem('pacs_token'); } catch (e) {}
    if (!token) {
      reconnectTimer = setTimeout(connect, 5000);
      return;
    }
    var wsUrl = wsBase + '?token=' + encodeURIComponent(token);
    try {
      ws = new WebSocket(wsUrl);
      ws.onopen = function() { console.log('[WeRU.B] WebSocket connected'); };
      ws.onmessage = function(event) {
        try {
          var data = JSON.parse(event.data);
          if (data.type === 'report_signed' && data.is_urgent) {
            // Urgent finding — browser notification
            if (Notification.permission === 'granted') {
              new Notification('긴급 소견', {
                body: data.patient_name + ' — ' + (data.impression || '').substring(0, 100),
                icon: '/werub-viewer/werub-logo.svg',
                tag: 'urgent-' + data.study_uid,
              });
            }
          } else if (data.type === 'stable_study') {
            // New study arrived — could refresh study list
            console.log('[WeRU.B] New study:', data.patient_name, data.modality);
          }
        } catch(e) {}
      };
      ws.onclose = function() {
        ws = null;
        reconnectTimer = setTimeout(connect, 5000);
      };
      ws.onerror = function() { ws && ws.close(); };
    } catch(e) {}
  }

  // Request notification permission
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
  }

  // Connect after page load
  setTimeout(connect, 3000);
})();

// =========================================================================
// 비표준 DICOM 검증 경고 배너 (P2-3)
// 현재 스터디에 검증 이슈(JPEG 밀도 불일치 등)가 있으면 상단에 경고 표시.
// 측정값 오류 위험을 판독 전 고지 — 사용자 강조 기능.
// =========================================================================
(function() {
  var lastUID = null;

  function currentStudyUID() {
    var p = new URLSearchParams(window.location.search);
    return p.get('StudyInstanceUIDs') || '';
  }

  function removeBanner() {
    var ex = document.getElementById('werub-validation-banner');
    if (ex) ex.remove();
  }

  function sev(i) { return (i.severity || '').toString().toLowerCase(); }

  function showBanner(issues) {
    removeBanner();
    var counts = { critical: 0, error: 0, warning: 0 };
    issues.forEach(function(i) { var s = sev(i); if (counts[s] != null) counts[s]++; });
    var maxSev = counts.critical ? 'critical' : (counts.error ? 'error' : 'warning');
    var color = maxSev === 'critical' ? '#DC2626' : (maxSev === 'error' ? '#EA580C' : '#D97706');
    var top = issues[0];
    var summary = [];
    if (counts.critical) summary.push('심각 ' + counts.critical);
    if (counts.error) summary.push('오류 ' + counts.error);
    if (counts.warning) summary.push('경고 ' + counts.warning);

    var bar = document.createElement('div');
    bar.id = 'werub-validation-banner';
    bar.style.cssText =
      'position:fixed;top:56px;left:50%;transform:translateX(-50%);z-index:9999;' +
      'max-width:80%;display:flex;align-items:center;gap:10px;' +
      'background:' + color + 'E6;color:#fff;padding:7px 14px;border-radius:8px;' +
      'font:600 12px system-ui,-apple-system,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,0.4);' +
      'cursor:pointer;border:1px solid rgba(255,255,255,0.25);';
    bar.title = '클릭하면 DICOM 이슈 관리 페이지로 이동';
    // K6: 관리자 편집 가능한 룰 메시지/요약이 innerHTML로 들어가는 XSS sink — 동적 부분 HTML 이스케이프.
    var _esc = function (s) {
      return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
      });
    };
    bar.innerHTML =
      '<span style="font-size:15px">⚠</span>' +
      '<span>비표준 DICOM 검증: ' + _esc(summary.join(' · ')) + '</span>' +
      '<span style="opacity:.85;font-weight:400">— ' +
        _esc((top.message || top.rule_code || '').toString().substring(0, 70)) + '</span>' +
      '<span data-x style="margin-left:6px;opacity:.8;font-size:14px;padding:0 4px">✕</span>';

    bar.addEventListener('click', function(e) {
      if (e.target && e.target.getAttribute('data-x') !== null) { removeBanner(); return; }
      window.open('/pacs-admin/dicom-issues', '_blank');
    });
    document.body.appendChild(bar);
  }

  function check() {
    var uid = currentStudyUID();
    if (!uid) { removeBanner(); lastUID = null; return; }
    if (uid === lastUID) return; // already checked this study
    lastUID = uid;
    removeBanner();
    var token = localStorage.getItem('pacs_token');
    fetch('/pacs-api/api/v1/dicom-issues?study_uid=' + encodeURIComponent(uid) + '&page_size=20&days=365', {
      headers: token ? { 'Authorization': 'Bearer ' + token } : {}
    })
    .then(function(r) { return r.ok ? r.json() : null; })
    .then(function(data) {
      if (!data || !data.issues) return;
      // warning 이상만 (info 제외) — severity 대소문자 무관
      var serious = data.issues.filter(function(i) { return sev(i) !== 'info'; });
      if (serious.length) showBanner(serious);
    })
    .catch(function() {});
  }

  // 최초 + 스터디 전환(SPA) 감지를 위해 주기적으로 URL 확인
  setTimeout(check, 4500);
  setInterval(check, 3000);
})();

// © 2026 WeRU.B Inc. | Based on OHIF Viewer v3.12 (MIT) | Orthanc v1.12.11 (GPLv3)
