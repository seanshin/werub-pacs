import { id } from './id';
import React from 'react';
import { ReportService } from './services/ReportService';
import getCommandsModule from './getCommandsModule';

const werubReportExtension = {
  id,

  preRegistration({ servicesManager }) {
    try {
      servicesManager.registerService(ReportService.REGISTRATION);
    } catch (e) {
      console.error('[werub-report] ReportService registration failed:', e);
    }
  },

  getPanelModule({ servicesManager, commandsManager }) {
    return [
      {
        name: 'reportPanel',
        iconName: 'tab-patient-info',
        iconLabel: '판독',
        label: '판독 리포트',
        component: (props) => {
          const ReportPanel = React.lazy(() => import('./panels/ReportPanel'));
          return (
            React.createElement(React.Suspense, {
              fallback: React.createElement('div', {
                style: { padding: '16px', color: '#888' }
              }, '로딩 중...')
            },
              React.createElement(ReportPanel, {
                ...props,
                servicesManager,
                commandsManager,
              })
            )
          );
        },
      },
    ];
  },

  getCommandsModule,
};

export default werubReportExtension;
