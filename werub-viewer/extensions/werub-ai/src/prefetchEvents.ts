/**
 * Study-open instrumentation + prefetch trigger (3d-ai-performance Track A).
 *
 * DICOMweb traffic goes nginx -> Orthanc and never touches the PACS backend,
 * so the viewer must announce study opens itself:
 *  - study-opened fires immediately on mode enter (starts server-side warming
 *    of the predicted next studies — must not wait for rendering)
 *  - load-measured fires once the first image renders (baseline/effect metric)
 *  - volume-complete reports full 3D volume load (progressive-loading measurement)
 */
import { eventTarget } from '@cornerstonejs/core';

const API_BASE = '/pacs-api/api/v1';

// @cornerstonejs/core Events.IMAGE_RENDERED. Hardcoded to avoid a build-time
// dependency; it is dispatched on the viewport element without bubbling, so we
// listen in the capture phase on document.
const IMAGE_RENDERED_EVENT = 'CORNERSTONE_IMAGE_RENDERED';
const RENDER_TIMEOUT_MS = 60_000;
// Full-volume load completion (progressive-loading measurement). This fires on
// cornerstone's eventTarget (NOT the DOM), so we attach there. Resolved from the
// monorepo even though it's not a package.json dep (other extensions import it).
const VOLUME_COMPLETE_EVENT = 'IMAGE_VOLUME_LOADING_COMPLETED';
const VOLUME_TIMEOUT_MS = 300_000;  // big CT volumes can take minutes

let cleanupFns: Array<() => void> = [];

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
    /* instrumentation must never break the viewer */
  });
}

function currentStudyUids(): string[] {
  const params = new URLSearchParams(window.location.search);
  const raw = params.get('StudyInstanceUIDs') || '';
  return raw.split(/[,;]/).map(s => s.trim()).filter(Boolean);
}

export function startStudyOpenTracking(): void {
  stopStudyOpenTracking();
  const uids = currentStudyUids();
  if (!uids.length) {
    return;
  }

  const t0 = performance.now();
  uids.forEach(uid => post('/prefetch/events/study-opened', { study_instance_uid: uid }));

  // Load time is attributed to the primary (first) study of the URL.
  const primaryUid = uids[0];
  let reported = false;
  const onRendered = () => {
    if (reported) {
      return;
    }
    reported = true;
    post('/prefetch/events/load-measured', {
      study_instance_uid: primaryUid,
      load_ms: Math.round(performance.now() - t0),
    });
    // Do NOT stop tracking here — the volume-complete listener fires later.
    // onModeExit() calls stopStudyOpenTracking() for cleanup.
  };

  document.addEventListener(IMAGE_RENDERED_EVENT, onRendered, { capture: true, once: true });
  const timer = window.setTimeout(() => {
    reported = true; // never rendered within budget — skip the metric
  }, RENDER_TIMEOUT_MS);

  // Full-volume load completion — the gap from t0 vs first image is the
  // progressive-loading benefit. Independent of onRendered (fires later).
  let volumeReported = false;
  const onVolumeComplete = () => {
    if (volumeReported) {
      return;
    }
    volumeReported = true;
    post('/prefetch/events/load-measured', {
      study_instance_uid: primaryUid,
      volume_complete_ms: Math.round(performance.now() - t0),
    });
  };
  try {
    eventTarget.addEventListener(VOLUME_COMPLETE_EVENT, onVolumeComplete);
  } catch (e) {
    console.error('[werub-ai] volume-complete listener failed:', e);
  }
  const volTimer = window.setTimeout(() => {
    volumeReported = true;
  }, VOLUME_TIMEOUT_MS);

  cleanupFns = [
    () => document.removeEventListener(IMAGE_RENDERED_EVENT, onRendered, { capture: true } as EventListenerOptions),
    () => window.clearTimeout(timer),
    () => { try { eventTarget.removeEventListener(VOLUME_COMPLETE_EVENT, onVolumeComplete); } catch { /* noop */ } },
    () => window.clearTimeout(volTimer),
  ];
}

export function stopStudyOpenTracking(): void {
  cleanupFns.forEach(fn => fn());
  cleanupFns = [];
}
