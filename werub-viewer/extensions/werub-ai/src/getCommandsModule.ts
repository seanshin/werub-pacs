import { comparePrior } from './priorCompare';

function getCommandsModule({ servicesManager }) {
  return {
    definitions: {
      runAiAnalysis: {
        commandFn: () => {
          const { aiService } = servicesManager.services;
          // StudyUID would need to be passed or read from viewport
          if (aiService) console.log('[werub-ai] runAiAnalysis command invoked');
        },
      },
      // 이전검사 원클릭 비교 (viewer-ux B) — 툴바 버튼·단축키 p
      werubComparePrior: {
        commandFn: () => comparePrior(servicesManager),
      },
    },
    defaultContext: 'VIEWER',
  };
}

export default getCommandsModule;
