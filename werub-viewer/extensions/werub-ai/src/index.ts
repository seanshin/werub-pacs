import { id } from './id';
import React from 'react';
import { AiService } from './services/AiService';
import getCommandsModule from './getCommandsModule';
import { startStudyOpenTracking, stopStudyOpenTracking } from './prefetchEvents';
import { startVrtTelemetry, stopVrtTelemetry } from './vrtTelemetry';
import setupVrtCustomizations from './vrtCustomizations';
import getHangingProtocolModule from './getHangingProtocolModule';

const werubAiExtension = {
  id,

  preRegistration({ servicesManager }) {
    try {
      servicesManager.registerService(AiService.REGISTRATION);
    } catch (e) {
      console.error('[werub-ai] AiService registration failed:', e);
    }
  },

  onModeEnter({ servicesManager }) {
    try {
      startStudyOpenTracking();
    } catch (e) {
      console.error('[werub-ai] study-open tracking failed:', e);
    }
    startVrtTelemetry(servicesManager);
    setupVrtCustomizations(servicesManager);
    // 자동 HP 매칭용 커스텀 속성 — werubAutoMPR의 required 규칙이 참조.
    // 확장 onModeEnter는 mode의 HP run보다 먼저 실행된다(Mode.tsx 순서 보장).
    try {
      const { hangingProtocolService } = servicesManager.services;
      hangingProtocolService?.addCustomAttribute?.(
        'werubHasReconstructable',
        '재구성 가능 시리즈 존재 여부',
        (_study, options) =>
          Boolean(options?.displaySets?.some(ds => ds?.isReconstructable === true))
      );
    } catch (e) {
      console.error('[werub-ai] custom HP attribute registration failed:', e);
    }
  },

  onModeExit() {
    stopStudyOpenTracking();
    stopVrtTelemetry();
  },

  getPanelModule({ servicesManager, commandsManager }) {
    return [
      {
        name: 'aiPanel',
        iconName: 'tab-segmentation',
        iconLabel: 'AI',
        label: 'AI 분석',
        component: (props) => {
          const AiPanel = React.lazy(() => import('./panels/AiPanel'));
          return React.createElement(
            React.Suspense,
            { fallback: React.createElement('div', { style: { padding: '16px', color: '#888' } }, '로딩 중...') },
            React.createElement(AiPanel, { ...props, servicesManager, commandsManager })
          );
        },
      },
    ];
  },

  getCommandsModule,
  getHangingProtocolModule,
};

export default werubAiExtension;
