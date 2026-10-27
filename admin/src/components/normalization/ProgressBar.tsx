'use client';

interface ProgressBarProps {
  processed: number;
  total: number;
  animated?: boolean;   // default true; pass false when job is terminal
}

export function ProgressBar({ processed, total, animated = true }: ProgressBarProps) {
  const pct = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm text-gray-600">
        <span>{processed.toLocaleString()} / {total.toLocaleString()} 파일</span>
        <span className="font-medium">{pct}%</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-3 overflow-hidden">
        <div
          className={`h-3 rounded-full bg-blue-500 transition-all duration-500 ${
            animated && pct > 0 && pct < 100 ? 'animate-pulse' : ''
          }`}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`처리 진행률 ${pct}%`}
        />
      </div>
    </div>
  );
}
