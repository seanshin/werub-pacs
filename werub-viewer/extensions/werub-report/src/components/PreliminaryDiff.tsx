import React, { useState } from 'react';
import type { Report } from '../services/ReportService';

export function PreliminaryInfo({ report }: { report: Report }) {
  return (
    <div className="rounded bg-purple-900/20 border border-purple-700/30 p-2 text-xs">
      <div className="text-purple-400 font-semibold mb-1">예비 판독 — 검토 후 최종 서명하세요</div>
      <div className="text-gray-400">
        예비판독: <span className="text-purple-300">{report.preliminary_by_name}</span>
        {report.preliminary_at && <> · {new Date(report.preliminary_at).toLocaleString('ko-KR')}</>}
      </div>
    </div>
  );
}

export function PreliminaryDiff({ content }: { content: { findings: string; impression: string; recommendation: string } }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded bg-[#0f1629] border border-[#333]">
      <button onClick={() => setOpen(!open)}
        className="w-full px-2 py-1.5 text-left text-[11px] text-gray-500 hover:text-gray-300 flex items-center gap-1">
        <span>{open ? '▼' : '▶'}</span>
        <span>예비 판독 원본</span>
      </button>
      {open && (
        <div className="px-2 pb-2 space-y-1.5 text-xs border-t border-[#333] pt-1.5">
          <div>
            <div className="text-gray-600 text-[10px]">소견 (원본)</div>
            <div className="text-gray-400 whitespace-pre-wrap">{content.findings || '-'}</div>
          </div>
          <div>
            <div className="text-gray-600 text-[10px]">결론 (원본)</div>
            <div className="text-gray-400 whitespace-pre-wrap">{content.impression || '-'}</div>
          </div>
          {content.recommendation && (
            <div>
              <div className="text-gray-600 text-[10px]">권고 (원본)</div>
              <div className="text-gray-400 whitespace-pre-wrap">{content.recommendation}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
