import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useViewportGrid } from '@ohif/ui-next';
import { getRawAnnotation, hydrateAnnotations } from '../services/measurementHydration';

interface KeyImage {
  sop: string;
  label: string;
}

interface SavedMeasurement {
  uid?: string;
  label?: string;
  type?: string;
  displayText?: any;
  SOPInstanceUID?: string;
}

/**
 * 핵심영상(KOS) 마킹 + 측정값 영속화 UI.
 *
 * - 현재 뷰포트의 영상을 핵심영상으로 마킹/해제
 * - 마킹된 영상을 표준 KOS(88.59) 문서로 생성·Orthanc 저장 (POST /reports/key-images)
 * - Cornerstone 측정값을 /studies/{uid}/annotations 에 저장하고 다음 세션에 복원 표시
 */
function KeyImagesBar({ servicesManager, reportService, studyUID, readOnly }: any) {
  const { displaySetService, cornerstoneViewportService, measurementService, uiNotificationService } =
    servicesManager?.services || {};
  const [viewportGrid] = useViewportGrid();

  const [keyImages, setKeyImages] = useState<KeyImage[]>([]);
  const [savedMeas, setSavedMeas] = useState<SavedMeasurement[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const loadedFor = useRef<string | null>(null);

  // --- Restore saved annotations when study changes ---
  useEffect(() => {
    if (!studyUID || !reportService?.loadAnnotations) return;
    if (loadedFor.current === studyUID) return;
    loadedFor.current = studyUID;
    // Reset immediately so the previous study's markings never linger (or get
    // mis-saved onto the new studyUID) while/if the load fails or returns null.
    setKeyImages([]);
    setSavedMeas([]);
    let cancelled = false;
    reportService.loadAnnotations(studyUID).then((data: any) => {
      if (cancelled) return;
      const ki = Array.isArray(data?.key_images) ? data.key_images : [];
      setKeyImages(
        ki
          .map((k: any) => (typeof k === 'string' ? { sop: k, label: '저장됨' } : k))
          .filter((k: any) => k?.sop)
      );
      const meas = Array.isArray(data?.measurements) ? data.measurements : [];
      setSavedMeas(meas);
      // Re-draw saved measurements onto the viewport. Best-effort: if cornerstone
      // isn't ready yet, retry shortly; failures degrade to text-only restore.
      const raws = meas.map((m: any) => m?.raw).filter(Boolean);
      if (raws.length) {
        const tryHydrate = (attempt: number) => {
          if (cancelled) return;
          const n = hydrateAnnotations(raws);
          if (n === 0 && attempt < 3) setTimeout(() => tryHydrate(attempt + 1), 800);
        };
        setTimeout(() => tryHydrate(0), 600);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [studyUID, reportService]);

  // --- Get current displayed image's SOP Instance UID ---
  const getActiveImage = useCallback((): KeyImage | null => {
    try {
      const { viewports, activeViewportId } = viewportGrid;
      const vp = viewports?.get(activeViewportId);
      const dsUID = vp?.displaySetInstanceUIDs?.[0];
      if (!dsUID) return null;
      const ds = displaySetService?.getDisplaySetByUID(dsUID);
      const images = ds?.images || ds?.instances || [];

      const csVp = cornerstoneViewportService?.getCornerstoneViewport?.(activeViewportId);
      // Only StackViewport exposes getCurrentImageId(); VolumeViewport (MPR/3D)
      // does not. Without it we cannot know which slice the user sees, and idx
      // would silently fall back to 0 → the FIRST instance gets marked regardless
      // of the displayed slice. Refuse to mark on non-stack viewports rather than
      // persist a wrong SOP into a standard KOS document.
      if (typeof csVp?.getCurrentImageId !== 'function') return null;

      let imageId: string | undefined;
      let idx = 0;
      try {
        imageId = csVp.getCurrentImageId();
        if (typeof csVp.getCurrentImageIdIndex === 'function') idx = csVp.getCurrentImageIdIndex() || 0;
      } catch {
        return null;
      }

      // Prefer SOP parsed from the actual displayed imageId; fall back to the
      // displaySet instance at the current index.
      let sop: string | undefined;
      if (imageId) {
        const m = imageId.match(/instances\/([0-9.]+)/) || imageId.match(/objectUID=([0-9.]+)/);
        sop = m?.[1];
      }
      if (!sop) sop = images?.[idx]?.SOPInstanceUID;
      if (!sop) return null;
      const num = images?.[idx]?.InstanceNumber ?? idx + 1;
      return { sop, label: `#${num}` };
    } catch {
      return null;
    }
  }, [viewportGrid, displaySetService, cornerstoneViewportService]);

  const handleMark = useCallback(() => {
    const img = getActiveImage();
    if (!img) {
      uiNotificationService?.show({
        title: '마킹 불가',
        message: 'MPR/3D 뷰포트에서는 핵심영상 마킹이 지원되지 않습니다. 2D(stack) 뷰포트로 전환하세요.',
        type: 'warning',
        duration: 4000,
      });
      return;
    }
    setKeyImages(prev => (prev.some(k => k.sop === img.sop) ? prev : [...prev, img]));
  }, [getActiveImage, uiNotificationService]);

  const handleRemove = useCallback((sop: string) => {
    setKeyImages(prev => prev.filter(k => k.sop !== sop));
  }, []);

  // --- Serialize current Cornerstone measurements ---
  const serializeMeasurements = useCallback((): SavedMeasurement[] => {
    if (!measurementService?.getMeasurements) return [];
    const list = measurementService.getMeasurements() || [];
    // Whitelist plain/scalar fields only. Raw cornerstone measurements can carry
    // circular refs, functions, or typed-arrays (esp. in points/metadata) that
    // make JSON.stringify throw — which would leave the save button stuck.
    const num = (v: any) => (typeof v === 'number' ? v : undefined);
    return list.map((m: any) => ({
      uid: m.uid,
      label: m.label || m.type,
      type: m.type,
      displayText: Array.isArray(m.displayText) ? m.displayText : m.displayText ? [m.displayText] : [],
      SOPInstanceUID: m.SOPInstanceUID || m.referencedImageId,
      referenceSeriesUID: m.referenceSeriesUID,
      referenceStudyUID: m.referenceStudyUID,
      points: Array.isArray(m.points)
        ? m.points.map((p: any) => (Array.isArray(p) ? p.map(num) : p))
        : undefined,
      metadata: m.metadata
        ? {
            FrameOfReferenceUID: m.metadata.FrameOfReferenceUID,
            referencedImageId: m.metadata.referencedImageId,
            toolName: m.metadata.toolName,
          }
        : undefined,
      // raw cornerstone annotation for canvas re-hydration next session (null if unavailable)
      raw: getRawAnnotation(m.uid),
    }));
  }, [measurementService]);

  // --- Generate KOS from marked key images ---
  const handleCreateKos = useCallback(async () => {
    if (readOnly || !keyImages.length || !reportService?.saveKeyImages) return;
    setBusy('kos');
    let result: any = null;
    try {
      const sops = keyImages.map(k => k.sop);
      result = await reportService.saveKeyImages(sops, `핵심영상 ${sops.length}건`);
      // Persist key images + current measurements alongside, for session restore
      if (studyUID && reportService.saveAnnotations) {
        await reportService.saveAnnotations(studyUID, {
          measurements: serializeMeasurements(),
          key_images: keyImages,
        });
      }
    } finally {
      setBusy(null);
    }
    if (result) {
      const miss = result.missing?.length ? ` (미발견 ${result.missing.length})` : '';
      uiNotificationService?.show({
        title: 'KOS 생성',
        message: `핵심영상 ${result.key_image_count}건 KOS 저장 완료${miss}`,
        type: 'success',
        duration: 4000,
      });
    } else {
      uiNotificationService?.show({
        title: 'KOS 실패',
        message: 'KOS 생성에 실패했습니다 (권한/로그인 확인)',
        type: 'error',
        duration: 4000,
      });
    }
  }, [readOnly, keyImages, reportService, studyUID, serializeMeasurements, uiNotificationService]);

  // --- Save measurements (+key images) to annotations ---
  const handleSaveMeas = useCallback(async () => {
    if (readOnly || !studyUID || !reportService?.saveAnnotations) return;
    setBusy('meas');
    const meas = serializeMeasurements();
    let result: any = null;
    try {
      result = await reportService.saveAnnotations(studyUID, {
        measurements: meas,
        key_images: keyImages,
      });
    } finally {
      setBusy(null);
    }
    if (result) {
      setSavedMeas(meas);
      uiNotificationService?.show({
        title: '측정 저장',
        message: `측정 ${meas.length}건 · 핵심영상 ${keyImages.length}건 저장됨`,
        type: 'success',
        duration: 3000,
      });
    } else {
      uiNotificationService?.show({
        title: '저장 실패',
        message: '측정값 저장에 실패했습니다',
        type: 'error',
        duration: 3000,
      });
    }
  }, [readOnly, studyUID, reportService, serializeMeasurements, keyImages, uiNotificationService]);

  const measText = (m: SavedMeasurement) => {
    const dt = Array.isArray(m.displayText)
      ? m.displayText.map((x: any) => (typeof x === 'string' ? x : x?.value || x?.label || '')).filter(Boolean).join(', ')
      : '';
    return `[${m.label || m.type || '측정'}]${dt ? ' ' + dt : ''}`;
  };

  return (
    <div className="rounded border border-[#2a3550] bg-[#0f1629]">
      <button
        onClick={() => setCollapsed(c => !c)}
        className="flex w-full items-center justify-between px-2 py-1.5 text-xs font-semibold text-gray-300"
      >
        <span>핵심영상 / 측정 {keyImages.length > 0 && <span className="text-amber-400">★{keyImages.length}</span>}</span>
        <span className="text-gray-500">{collapsed ? '▸' : '▾'}</span>
      </button>

      {!collapsed && (
        <div className="space-y-2 px-2 pb-2">
          {!readOnly && (
            <button
              onClick={handleMark}
              className="w-full rounded bg-[#1a2540] py-1.5 text-xs font-medium text-amber-300 hover:bg-[#22305a]"
            >
              ★ 현재 영상 핵심영상으로 마킹
            </button>
          )}

          {/* Marked key images list */}
          {keyImages.length > 0 && (
            <ul className="space-y-1">
              {keyImages.map(k => (
                <li
                  key={k.sop}
                  className="flex items-center justify-between rounded bg-[#0b101f] px-2 py-1 text-[11px] text-gray-300"
                >
                  <span className="truncate">
                    <span className="text-amber-400">★</span> {k.label}
                    <span className="ml-1 text-gray-600">…{k.sop.slice(-8)}</span>
                  </span>
                  {!readOnly && (
                    <button onClick={() => handleRemove(k.sop)} className="ml-2 text-gray-500 hover:text-red-400">
                      ✕
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}

          {!readOnly && (
            <div className="flex gap-1.5">
              <button
                onClick={handleCreateKos}
                disabled={!keyImages.length || busy === 'kos'}
                className="flex-1 rounded bg-amber-700 py-1.5 text-xs font-semibold text-white hover:bg-amber-600 disabled:opacity-40"
              >
                {busy === 'kos' ? '생성 중…' : 'KOS 생성·저장'}
              </button>
              <button
                onClick={handleSaveMeas}
                disabled={busy === 'meas'}
                className="flex-1 rounded bg-blue-700 py-1.5 text-xs font-semibold text-white hover:bg-blue-600 disabled:opacity-40"
              >
                {busy === 'meas' ? '저장 중…' : '측정 저장'}
              </button>
            </div>
          )}

          {/* Restored / saved measurements from previous session */}
          {savedMeas.length > 0 && (
            <div className="rounded bg-[#0b101f] p-1.5">
              <div className="mb-1 text-[10px] font-semibold text-gray-500">저장된 측정 {savedMeas.length}건</div>
              <ul className="space-y-0.5">
                {savedMeas.map((m, i) => (
                  <li key={m.uid || i} className="truncate text-[11px] text-gray-400">
                    {measText(m)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default KeyImagesBar;
