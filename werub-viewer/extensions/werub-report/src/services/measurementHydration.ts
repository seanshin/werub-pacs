/**
 * Measurement canvas re-hydration helpers.
 *
 * Persisting `measurementService.getMeasurements()` only captures display text.
 * To actually re-draw editable measurements on the viewport in a later session
 * we must round-trip the raw Cornerstone3D annotation objects.
 *
 * Singleton note: `@cornerstonejs/tools` is hoisted to a single node_modules copy
 * in the OHIF monorepo, so importing it here resolves to the SAME annotation-state
 * instance the cornerstone extension uses (no duplicate-module split).
 *
 * Everything is wrapped in try/catch: if hydration ever fails (e.g. a module split
 * or a malformed saved annotation) it degrades silently to the text-only restore —
 * no regression, no crash.
 */
import { annotation as csAnnotation } from '@cornerstonejs/tools';
import { getRenderingEngines } from '@cornerstonejs/core';

/**
 * Return a JSON-serializable copy of the raw cornerstone annotation for a given
 * measurement UID (measurement.uid === annotation.annotationUID), or null.
 */
export function getRawAnnotation(uid?: string): any | null {
  if (!uid) return null;
  try {
    const a = csAnnotation.state.getAnnotation(uid);
    if (!a?.metadata) return null;
    return JSON.parse(
      JSON.stringify({
        annotationUID: a.annotationUID,
        metadata: a.metadata,
        data: a.data,
        isLocked: false,
        isVisible: true,
      })
    );
  } catch {
    return null;
  }
}

/**
 * Re-add saved raw annotations to the cornerstone annotation state and re-render.
 * Skips annotations already present (avoids duplicates on revisit). Returns the
 * number actually hydrated.
 */
export function hydrateAnnotations(raws: any[]): number {
  if (!Array.isArray(raws) || !raws.length) return 0;
  let n = 0;
  for (const raw of raws) {
    try {
      if (!raw?.metadata) continue;
      if (raw.annotationUID && csAnnotation.state.getAnnotation(raw.annotationUID)) continue;
      // annotationGroupSelector = FrameOfReferenceUID (string) groups stack/volume annotations
      csAnnotation.state.addAnnotation(raw, raw.metadata.FrameOfReferenceUID);
      n++;
    } catch {
      /* skip this annotation, keep going */
    }
  }
  if (n > 0) {
    try {
      getRenderingEngines().forEach((re: any) => re.render());
    } catch {
      /* render best-effort */
    }
  }
  return n;
}
