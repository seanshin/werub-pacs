'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { getStudyViewability } from '@/lib/dicom-renderability';

interface Props {
  url: string;
  label?: string;
  size?: 'sm' | 'md';
  modality?: string | null;
  studyUID?: string | null;
}

export default function ViewerButton({ url, label = '영상 보기', size = 'md', modality, studyUID }: Props) {
  const [open, setOpen] = useState(false);
  const [showWarning, setShowWarning] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  // Extract studyUID from URL if not provided
  const extractedUID = studyUID || (() => {
    const m = url.match(/StudyInstanceUIDs=([^&]+)/);
    return m ? m[1] : null;
  })();
  const viewability = getStudyViewability(extractedUID, modality);

  const openViewer = useCallback((mode: 'tab' | 'window' | 'monitor2') => {
    setOpen(false);
    setShowWarning(false);
    const fullUrl = url.startsWith('http') ? url : window.location.origin + url;

    if (mode === 'tab') {
      window.open(fullUrl, '_blank');
    } else if (mode === 'window') {
      window.open(fullUrl, '_blank', 'width=1400,height=900,menubar=no,toolbar=no,location=no,status=no');
    } else if (mode === 'monitor2') {
      const x = window.screen.width;
      window.open(fullUrl, '_blank', `width=1920,height=1080,left=${x},top=0,menubar=no,toolbar=no,location=no,status=no`);
    }
  }, [url]);

  // Create/destroy menu via direct DOM manipulation to escape overflow containers
  useEffect(() => {
    if (!open || !btnRef.current) {
      if (menuRef.current) {
        menuRef.current.remove();
        menuRef.current = null;
      }
      return;
    }

    const rect = btnRef.current.getBoundingClientRect();
    const menuW = 176;
    let left = rect.right - menuW;
    if (left + menuW > window.innerWidth - 8) left = window.innerWidth - menuW - 8;
    if (left < 8) left = 8;
    const top = rect.bottom + 4;

    // Backdrop
    const backdrop = document.createElement('div');
    backdrop.style.cssText = 'position:fixed;inset:0;z-index:9998;';
    backdrop.onclick = () => setOpen(false);

    // Menu
    const menu = document.createElement('div');
    menu.style.cssText = `position:fixed;top:${top}px;left:${left}px;z-index:9999;width:${menuW}px;`;
    menu.className = 'bg-white border rounded-lg shadow-xl py-1 text-sm';

    const items = [
      { label: '새 탭', mode: 'tab' as const },
      { label: '새 창', mode: 'window' as const },
      { label: '두 번째 모니터', mode: 'monitor2' as const },
    ];

    items.forEach(item => {
      const btn = document.createElement('button');
      btn.className = 'w-full text-left px-3 py-2 hover:bg-gray-100';
      btn.textContent = item.label;
      btn.onclick = () => openViewer(item.mode);
      menu.appendChild(btn);
    });

    const container = document.createElement('div');
    container.appendChild(backdrop);
    container.appendChild(menu);
    document.body.appendChild(container);
    menuRef.current = container;

    return () => {
      container.remove();
      menuRef.current = null;
    };
  }, [open, openViewer]);

  const btnClass = size === 'sm'
    ? 'px-2 py-1 text-xs'
    : 'px-3 py-2 text-sm';

  const handleMainClick = () => {
    if (!viewability.viewable) {
      setShowWarning(true);
    } else {
      openViewer('tab');
    }
  };

  return (
    <div className="shrink-0">
      <div className="flex">
        <button onClick={handleMainClick}
          className={`${viewability.viewable ? 'bg-blue-600 hover:bg-blue-700' : 'bg-slate-500 hover:bg-slate-600'} text-white rounded-l font-semibold ${btnClass}`}>
          {label}
        </button>
        <button ref={btnRef} onClick={() => setOpen(!open)}
          className={`${viewability.viewable ? 'bg-blue-700 hover:bg-blue-800 border-blue-500' : 'bg-slate-600 hover:bg-slate-700 border-slate-400'} text-white rounded-r border-l ${size === 'sm' ? 'px-1 py-1 text-xs' : 'px-1.5 py-2 text-sm'}`}>
          ▾
        </button>
      </div>

      {/* Non-renderable warning dialog */}
      {showWarning && (
        <div className="fixed inset-0 bg-black/40 z-[10000] flex items-center justify-center" onClick={() => setShowWarning(false)}>
          <div className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-sm mx-4" onClick={e => e.stopPropagation()}>
            <div className="text-center mb-4">
              <div className="w-12 h-12 bg-amber-100 rounded-full flex items-center justify-center mx-auto mb-3">
                <svg className="w-6 h-6 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                </svg>
              </div>
              <h3 className="text-lg font-bold text-slate-900">영상 표시 불가</h3>
              <div className="mt-2 space-y-1">
                {viewability.issue?.type === 'invalid_uid' ? (
                  <>
                    <p className="text-sm font-semibold text-red-700">{viewability.issue.label}</p>
                    <p className="text-sm text-slate-500 mt-1">{viewability.issue.description}</p>
                    <p className="text-[10px] text-slate-400 mt-2 font-mono truncate max-w-[280px] mx-auto" title={extractedUID || ''}>{extractedUID}</p>
                  </>
                ) : (
                  <>
                    <p className="text-sm font-semibold text-slate-700">
                      모달리티: <span className="text-amber-700">{modality}</span>
                      {viewability.issue?.label && <span className="text-slate-500 font-normal"> ({viewability.issue.label})</span>}
                    </p>
                    <p className="text-sm text-slate-500">{viewability.issue?.description}</p>
                  </>
                )}
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={() => setShowWarning(false)}
                className={`${viewability.issue?.type === 'invalid_uid' ? 'flex-1' : ''} px-4 py-2.5 border border-slate-300 rounded-xl text-sm font-medium text-slate-600 hover:bg-slate-50 transition`}>
                닫기
              </button>
              {viewability.issue?.type !== 'invalid_uid' && (
                <button onClick={() => openViewer('tab')}
                  className="flex-1 px-4 py-2.5 bg-slate-600 text-white rounded-xl text-sm font-medium hover:bg-slate-700 transition">
                  그래도 열기
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
