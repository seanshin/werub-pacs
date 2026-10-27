/**
 * 3D 사용 텔레메트리 (vrt-rendering Phase 1 §1.2-5).
 *
 * 레이아웃이 3D 계열 행잉 프로토콜로 전환될 때 백엔드에 기록한다 —
 * 서버사이드 GPU 렌더링(Phase 2)의 수요 근거 데이터.
 */
const API_BASE = '/pacs-api/api/v1';

const THREE_D_PROTOCOLS = new Set([
  'main3D',
  'only3D',
  'primary3D',
  'mprAnd3DVolumeViewport',
  'fourUp',
]);

let subscription: { unsubscribe: () => void } | null = null;
let presetListener: ((e: Event) => void) | null = null;
let wasIn3D = false;

function post(path: string, payload: Record<string, unknown>): void {
  const token = typeof localStorage !== 'undefined' ? localStorage.getItem('pacs_token') : null;
  if (!token) {
    return;
  }
  fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => {
    /* telemetry must never break the viewer */
  });
}

function currentStudyUid(): string {
  const params = new URLSearchParams(window.location.search);
  return (params.get('StudyInstanceUIDs') || '').split(/[,;]/)[0]?.trim() || '';
}

export function startVrtTelemetry(servicesManager): void {
  stopVrtTelemetry();
  try {
    const { hangingProtocolService, uiNotificationService } = servicesManager.services;
    subscription = hangingProtocolService.subscribe(
      hangingProtocolService.EVENTS.PROTOCOL_CHANGED,
      () => {
        try {
          const { protocol } = hangingProtocolService.getActiveProtocol();
          const in3D = Boolean(protocol?.id && THREE_D_PROTOCOLS.has(protocol.id));
          if (in3D) {
            post('/vrt/events/protocol', {
              study_instance_uid: currentStudyUid(),
              protocol_id: protocol.id,
            });
            // 참고용 3D 안내 — 3D 뷰포트는 HP가 hideOverlays:true로 오버레이 전체를
            // 숨기므로 뷰포트 배지가 불가(v11.6 배지가 렌더된 적 없던 이유). 토스트로 대체.
            if (!wasIn3D) {
              uiNotificationService?.show?.({
                title: '참고용 3D 렌더링',
                message: '3D 화면은 참고용입니다 — 측정은 MPR 뷰포트에서 하세요.',
                type: 'info',
                duration: 8000,
              });
            }
          }
          wasIn3D = in3D;
        } catch {
          /* ignore */
        }
      }
    );
  } catch (e) {
    console.error('[werub-ai] vrt telemetry init failed:', e);
  }
  // VR 프리셋 적용 텔레메트리 (C2) — VolumeRenderingPresetsContent(werub-source.patch)가 발행
  presetListener = (e: Event) => {
    try {
      const preset = (e as CustomEvent).detail?.preset;
      if (preset) {
        post('/vrt/events/preset', {
          study_instance_uid: currentStudyUid(),
          preset_name: String(preset).slice(0, 64),
        });
      }
    } catch {
      /* ignore */
    }
  };
  document.addEventListener('werub:vrt-preset-applied', presetListener);
}

export function stopVrtTelemetry(): void {
  subscription?.unsubscribe?.();
  subscription = null;
  wasIn3D = false;
  if (presetListener) {
    document.removeEventListener('werub:vrt-preset-applied', presetListener);
    presetListener = null;
  }
}
