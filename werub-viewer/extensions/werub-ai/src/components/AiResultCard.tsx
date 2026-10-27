import React from 'react';

interface Props {
  title: string;
  content: string;
  duration_ms?: number;
  disabled?: boolean;
  onApply?: () => void;
  onCopy?: () => void;
  onSaveSR?: () => void;
}

export default function AiResultCard({ title, content, duration_ms, disabled, onApply, onCopy, onSaveSR }: Props) {
  if (!content) return null;

  return (
    <div className="rounded-lg border border-purple-500/30 bg-purple-900/10 p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-purple-300">{title}</span>
        {duration_ms && (
          <span className="text-[10px] text-gray-500">{duration_ms}ms</span>
        )}
      </div>
      <div className="text-sm text-gray-300 whitespace-pre-wrap mb-2 max-h-[200px] overflow-y-auto">
        {content}
      </div>
      <div className="flex gap-2">
        {onApply && (
          <button
            onClick={onApply}
            disabled={disabled}
            className="rounded bg-purple-600 px-3 py-1 text-xs font-semibold text-white hover:bg-purple-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {disabled ? '적용 중...' : '판독에 적용'}
          </button>
        )}
        {onSaveSR && (
          <button
            onClick={onSaveSR}
            disabled={disabled}
            className="rounded bg-teal-600 px-3 py-1 text-xs font-semibold text-white hover:bg-teal-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {disabled ? '저장 중...' : 'SR 저장'}
          </button>
        )}
        {onCopy && (
          <button
            onClick={onCopy}
            className="rounded border border-[#444] px-3 py-1 text-xs text-gray-400 hover:text-gray-200 transition"
          >
            복사
          </button>
        )}
      </div>
    </div>
  );
}
