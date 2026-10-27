function getCommandsModule({ servicesManager }) {
  return {
    definitions: {
      saveReport: {
        commandFn: () => {
          const { reportService } = servicesManager.services;
          if (reportService) reportService.save({});
        },
      },
      signReport: {
        commandFn: () => {
          const { reportService } = servicesManager.services;
          if (reportService) reportService.sign();
        },
      },
      toggleReportPanel: {
        commandFn: () => {
          const { panelService } = servicesManager.services;
          if (panelService) {
            panelService.activatePanel('@ohif/extension-werub-report.panelModule.reportPanel');
          }
        },
      },
      openSecondWindow: {
        commandFn: () => {
          // Get current StudyInstanceUIDs from URL
          const params = new URLSearchParams(window.location.search);
          const studyUIDs = params.get('StudyInstanceUIDs') || '';
          if (!studyUIDs) return;

          // Open a second viewer window with the same study
          const basePath = window.location.pathname.replace(/\/[^/]*$/, '');
          const url = `${basePath}/viewer?StudyInstanceUIDs=${studyUIDs}`;
          const screenWidth = window.screen.availWidth;
          const screenHeight = window.screen.availHeight;

          // Position: right half of screen
          window.open(
            url,
            'werub-secondary',
            `width=${Math.floor(screenWidth / 2)},height=${screenHeight},left=${Math.floor(screenWidth / 2)},top=0,toolbar=no,menubar=no,location=no`
          );
        },
      },
    },
    defaultContext: 'VIEWER',
  };
}

export default getCommandsModule;
