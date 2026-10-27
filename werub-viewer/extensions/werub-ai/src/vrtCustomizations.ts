/**
 * 3D VRT 임상 튜닝 — 경량 스코프 (C2, docs/02-design/vrt-clinical-tuning-c2.design.md §2).
 *
 * 1) VR 프리셋 큐레이션: cornerstone 코어 26종 → 한국 임상 핵심 13종(순서 고정).
 *    preset.name은 cornerstone 룩업 키·아이콘 키이므로 불변 — 한글 표시는
 *    기존 i18n(WindowLevelActionMenu ns, 68f83ef)이 담당한다.
 * 2) 레이아웃 셀렉터 Advanced 목록 한글화·정렬(3D 진입 UX).
 *
 * onModeEnter에서 global scope로 설정 — 확장 로드 순서와 무관하게
 * cornerstone 확장의 default 값을 확정적으로 덮는다($ 키 없음 = 통째 교체).
 */
import { CONSTANTS } from '@cornerstonejs/core';

const CURATED_PRESET_NAMES = [
  'CT-Bone',
  'CT-Soft-Tissue',
  'CT-Lung',
  'CT-Cardiac',
  'CT-Chest-Contrast-Enhanced',
  'CT-Coronary-Arteries',
  'CT-Pulmonary-Arteries',
  'CT-Liver-Vasculature',
  'CT-AAA',
  'CT-MIP',
  'MR-Default',
  'MR-Angio',
  'MR-MIP',
];

// HP id → 한글 타이틀. protocolId는 반드시 hangingProtocolService에 등록된 hp.id를 써야 한다
// (ToolbarLayoutSelector의 하드코딩 폴백 '3d-main' 등은 미등록 id — 클릭해도 "No protocol found").
const HP_TITLES_KO: Record<string, string> = {
  mpr: 'MPR',
  main3D: '3D 메인',
  mprAnd3DVolumeViewport: 'MPR + 3D',
  fourUp: '3D 4분할',
  only3D: '3D 단독',
  primary3D: '3D 주화면',
  primaryAxial: 'Axial 우선',
  '@ohif/frameView': '프레임 뷰',
};

const HP_ORDER = Object.keys(HP_TITLES_KO);

/**
 * cornerstone 기본 layoutSelectorCustomization과 동일하게 등록 HP(isPreset)를 열거하고
 * displaySet 선택자 검증으로 disabled를 계산하되, 타이틀 한글화 + 3D 우선 정렬만 더한다.
 */
function generateAdvancedPresets({ servicesManager }) {
  const { hangingProtocolService, viewportGridService, displaySetService } =
    servicesManager.services;

  const viewportId = viewportGridService.getActiveViewportId();
  if (!viewportId) {
    return [];
  }
  const displaySetInstanceUIDs = viewportGridService.getDisplaySetsUIDsForViewport(viewportId);
  if (!displaySetInstanceUIDs) {
    return [];
  }
  const displaySets = displaySetInstanceUIDs.map(uid => {
    const displaySet = displaySetService.getDisplaySetByUID(uid);
    const referencedDisplaySetUID = displaySet?.measurements?.[0]?.displaySetInstanceUID;
    if (displaySet?.Modality === 'SR' && referencedDisplaySetUID) {
      return displaySetService.getDisplaySetByUID(referencedDisplaySetUID);
    }
    return displaySet;
  });

  const isValid = hp => {
    if (!hp.displaySetSelectors || Object.values(hp.displaySetSelectors).length === 0) {
      return true;
    }
    return hangingProtocolService.areRequiredSelectorsValid(
      Object.values(hp.displaySetSelectors),
      displaySets[0]
    );
  };

  return Array.from(hangingProtocolService.protocols.values())
    .filter(hp => hp.isPreset)
    .map(hp => ({
      icon: hp.icon,
      title: HP_TITLES_KO[hp.id] || hp.name,
      commandOptions: { protocolId: hp.id },
      disabled: !isValid(hp),
    }))
    .sort((a, b) => {
      const ia = HP_ORDER.indexOf(a.commandOptions.protocolId);
      const ib = HP_ORDER.indexOf(b.commandOptions.protocolId);
      return (ia === -1 ? HP_ORDER.length : ia) - (ib === -1 ? HP_ORDER.length : ib);
    });
}

export default function setupVrtCustomizations(servicesManager): void {
  try {
    const { customizationService } = servicesManager.services;
    if (!customizationService) {
      return;
    }
    const all = CONSTANTS.VIEWPORT_PRESETS || [];
    const byName = new Map(all.map(p => [p.name, p]));
    const curated = CURATED_PRESET_NAMES.map(n => byName.get(n)).filter(Boolean);
    customizationService.setCustomizations(
      {
        'cornerstone.3dVolumeRendering': {
          // 코어 버전업으로 이름이 어긋나 큐레이션이 비면 전체 목록으로 폴백
          volumeRenderingPresets: curated.length ? curated : all,
          volumeRenderingQualityRange: { min: 1, max: 4, step: 1 },
        },
        'layoutSelector.advancedPresetGenerator': generateAdvancedPresets,
      },
      'global'
    );
  } catch (e) {
    console.error('[werub-ai] vrt customizations failed:', e);
  }
}
