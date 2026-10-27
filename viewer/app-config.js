// Load OpenPACS Report Panel
(function(){var s=document.createElement('script');s.src='/report-panel.js?v='+Date.now();s.async=true;document.head.appendChild(s);})();

window.config = {
  routerBasename: '/viewer',
  extensions: [],
  modes: [],
  customizationService: {
    // White labeling
    'ohif.overlayItem': {
      topLeft: ['PatientName', 'PatientID', 'PatientBirthDate'],
      topRight: ['InstitutionName', 'StudyDate', 'StudyTime', 'StudyDescription'],
      bottomLeft: ['SeriesNumber', 'SeriesDescription', 'InstanceNumber'],
      bottomRight: ['WindowLevel', 'Zoom', 'SliceLocation'],
    },
  },
  showStudyList: true,
  maxNumberOfWebWorkers: 3,
  showWarningMessageForCrossOrigin: false,
  investigationalUseDialog: { option: 'never' },
  showCPUFallbackMessage: true,
  showLoadingIndicator: true,
  experimentalStudyBrowserSort: false,
  strictZSpacingForVolumeViewport: true,
  groupEnabledModesFirst: true,
  showPatientInfo: 'visible',
  maxNumRequests: {
    interaction: 100,
    thumbnail: 75,
    prefetch: 25,
  },
  showErrorDetails: 'always',
  // Language (ko-KR locale not bundled in OHIF — use WeRU.B Viewer for Korean UI)
  language: 'en-US',
  defaultDataSourceName: 'dicomweb',
  dataSources: [
    {
      namespace: '@ohif/extension-default.dataSourcesModule.dicomweb',
      sourceName: 'dicomweb',
      configuration: {
        friendlyName: 'OpenPACS',
        name: 'orthanc',
        wadoUriRoot: '/wado',
        qidoRoot: '/dicom-web',
        wadoRoot: '/dicom-web',
        qidoSupportsIncludeField: false,
        supportsReject: false,
        dicomUploadEnabled: true,
        imageRendering: 'wadors',
        thumbnailRendering: 'wadors',
        enableStudyLazyLoad: true,
        supportsFuzzyMatching: false,
        supportsWildcard: true,
        omitQuotationForMultipartRequest: true,
        bulkDataURI: {
          enabled: false,
        },
      },
    },
    {
      namespace: '@ohif/extension-default.dataSourcesModule.dicomlocal',
      sourceName: 'dicomlocal',
      configuration: {
        friendlyName: 'Local Files',
      },
    },
  ],
  // Hotkeys
  hotkeys: [
    { commandName: 'incrementActiveViewport', label: 'Next Viewport', keys: ['right'] },
    { commandName: 'decrementActiveViewport', label: 'Previous Viewport', keys: ['left'] },
    { commandName: 'rotateViewportCW', label: 'Rotate CW', keys: ['r'] },
    { commandName: 'flipViewportHorizontal', label: 'Flip H', keys: ['h'] },
    { commandName: 'flipViewportVertical', label: 'Flip V', keys: ['v'] },
    { commandName: 'scaleUpViewport', label: 'Zoom In', keys: ['='] },
    { commandName: 'scaleDownViewport', label: 'Zoom Out', keys: ['-'] },
    { commandName: 'fitViewportToWindow', label: 'Fit to Window', keys: ['0'] },
    { commandName: 'resetViewport', label: 'Reset', keys: ['space'] },
    { commandName: 'toggleCine', label: 'Cine', keys: ['c'] },
    { commandName: 'invertViewport', label: 'Invert', keys: ['i'] },
  ],
};
