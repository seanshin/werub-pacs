/**
 * DICOM 모달리티 렌더링 가능 여부 판별
 * 픽셀 데이터가 없는 모달리티를 사전 감지하여 사용자에게 안내
 *
 * v9.0: API에서 동적으로 설정을 로드하되, 하드코딩 폴백 유지
 */

// ─── Hardcoded fallbacks (API 로드 실패 시 사용) ────────────────────────────

const FALLBACK_NON_RENDERABLE = new Set([
  'RTSTRUCT', 'RTPLAN', 'RTDOSE', 'SR', 'PR', 'KO', 'ANN',
]);

const FALLBACK_PARTIAL = new Set(['SEG']);

const FALLBACK_INFO: Record<string, { label: string; description: string; action: string }> = {
  RTSTRUCT: { label: '방사선 치료 구조물', description: '윤곽선/구조물 데이터로, 영상 픽셀이 포함되어 있지 않습니다.', action: '연결된 CT 영상과 함께 열어야 구조물이 표시됩니다.' },
  RTPLAN: { label: '방사선 치료 계획', description: '치료 계획 데이터로, 영상 픽셀이 포함되어 있지 않습니다.', action: '전용 RT 뷰어가 필요합니다.' },
  RTDOSE: { label: '방사선 선량 분포', description: '3D 선량 데이터로, 일반 뷰어에서 정확히 표시되지 않을 수 있습니다.', action: '전용 RT 뷰어 사용을 권장합니다.' },
  SR: { label: '구조화 리포트', description: '텍스트 기반 리포트로, 영상 데이터가 포함되어 있지 않습니다.', action: '판독 리포트에서 내용을 확인하세요.' },
  PR: { label: 'Presentation State', description: '영상 표시 설정 데이터로, 단독 표시가 불가능합니다.', action: '참조 영상에 적용되는 표시 설정입니다.' },
  KO: { label: 'Key Object Selection', description: '주요 영상 참조 목록으로, 영상 자체가 아닙니다.', action: '참조된 원본 영상을 확인하세요.' },
  SEG: { label: '분할 데이터', description: '세그멘테이션 오버레이로, 원본 영상과 함께 표시됩니다.', action: '원본 영상과 함께 열어야 합니다.' },
  DOC: { label: '문서', description: '캡슐화된 문서(PDF 등)입니다.', action: 'OHIF PDF Extension으로 표시 가능합니다.' },
  ANN: { label: '주석 데이터', description: '영상 주석(Annotation)으로, 단독 표시가 불가능합니다.', action: '참조 영상에 오버레이로 표시됩니다.' },
};

// ─── Dynamic config cache (loaded from API) ─────────────────────────────────

type ApiModalityConfig = {
  modality: string; render_type: string; display_label: string;
  description: string; action_text: string | null; enabled: boolean;
};

let _configCache: ApiModalityConfig[] | null = null;
let _configLoadedAt = 0;
const CONFIG_TTL_MS = 5 * 60 * 1000; // 5 minutes

export async function loadModalityConfig(): Promise<void> {
  if (_configCache && Date.now() - _configLoadedAt < CONFIG_TTL_MS) return;
  try {
    const resp = await fetch('/pacs-api/api/v1/dicom-issues/modality-config');
    if (resp.ok) {
      const data = await resp.json();
      _configCache = data.configs || [];
      _configLoadedAt = Date.now();
    }
  } catch {
    // Silently fall back to hardcoded values
  }
}

// Sync access with dynamic data if available
function getDynamicConfig(mod: string): ApiModalityConfig | undefined {
  return _configCache?.find(c => c.modality === mod && c.enabled);
}

// ─── Public exports (backwards compatible) ──────────────────────────────────

export const NON_RENDERABLE_MODALITIES = FALLBACK_NON_RENDERABLE;
export const PARTIALLY_RENDERABLE = FALLBACK_PARTIAL;

type ModalityInfo = {
  renderable: boolean;
  partial: boolean;
  label: string;
  description: string;
  action: string;
};

export function getModalityRenderability(modality: string | null | undefined): ModalityInfo {
  if (!modality) return { renderable: true, partial: false, label: '', description: '', action: '' };

  const mod = modality.toUpperCase().trim();

  // Try dynamic config first
  const dynamic = getDynamicConfig(mod);
  if (dynamic) {
    const renderable = dynamic.render_type === 'renderable' || dynamic.render_type === 'partial';
    const partial = dynamic.render_type === 'partial';
    return {
      renderable: dynamic.render_type !== 'non_renderable',
      partial,
      label: dynamic.display_label,
      description: dynamic.description,
      action: dynamic.action_text || '',
    };
  }

  // Fallback to hardcoded
  if (FALLBACK_NON_RENDERABLE.has(mod)) {
    const info = FALLBACK_INFO[mod] || { label: mod, description: '이 모달리티는 뷰어에서 표시할 수 없습니다.', action: '' };
    return { renderable: false, partial: false, ...info };
  }

  if (FALLBACK_PARTIAL.has(mod)) {
    const info = FALLBACK_INFO[mod] || { label: mod, description: '이 모달리티는 일부만 표시될 수 있습니다.', action: '' };
    return { renderable: true, partial: true, ...info };
  }

  return { renderable: true, partial: false, label: '', description: '', action: '' };
}

export function isNonRenderable(modality: string | null | undefined): boolean {
  if (!modality) return false;
  // For multi-modality studies (e.g. "CT\SR"), renderable if ANY modality is renderable
  const mods = modality.toUpperCase().trim().split(/[\\\\/,]/);
  return mods.every(m => NON_RENDERABLE_MODALITIES.has(m.trim()));
}

/**
 * DICOM UID 유효성 검사.
 * 표준 UID: 숫자와 점(.)으로만 구성, 최대 64자.
 * 비표준 UID (hex 문자열 등)는 DICOMweb에서 조회 불가.
 */
export function isValidDicomUID(uid: string | null | undefined): boolean {
  if (!uid || uid.length === 0) return false;
  if (uid.length > 64) return false;
  return /^[0-9]+(\.[0-9]+)+$/.test(uid);
}

type StudyIssue = {
  type: 'invalid_uid' | 'non_renderable' | 'partial';
  label: string;
  description: string;
};

/**
 * Study의 뷰어 표시 가능 여부를 종합 판단.
 * UID 유효성 + 모달리티 렌더링 가능 여부 모두 확인.
 */
export function getStudyViewability(
  studyUID: string | null | undefined,
  modality: string | null | undefined,
): { viewable: boolean; issue: StudyIssue | null } {
  if (!isValidDicomUID(studyUID)) {
    return {
      viewable: false,
      issue: {
        type: 'invalid_uid',
        label: '비표준 Study UID',
        description: 'DICOM 표준 UID 형식이 아니어서 뷰어에서 열 수 없습니다.',
      },
    };
  }

  // For multi-modality studies, check if ANY modality is renderable
  const mods = (modality || '').toUpperCase().trim().split(/[\\\\/,]/).map(m => m.trim()).filter(Boolean);
  const renderabilities = mods.map(m => getModalityRenderability(m));
  const hasRenderable = renderabilities.some(r => r.renderable);
  const allNonRenderable = renderabilities.length > 0 && renderabilities.every(r => !r.renderable);
  const nonRenderableInfo = renderabilities.find(r => !r.renderable);

  if (allNonRenderable && nonRenderableInfo) {
    return {
      viewable: false,
      issue: {
        type: 'non_renderable',
        label: nonRenderableInfo.label,
        description: nonRenderableInfo.description,
      },
    };
  }

  const partialInfo = renderabilities.find(r => r.partial);
  if (partialInfo && !hasRenderable) {
    return {
      viewable: true,
      issue: {
        type: 'partial',
        label: partialInfo.label,
        description: partialInfo.description,
      },
    };
  }

  return { viewable: true, issue: null };
}
