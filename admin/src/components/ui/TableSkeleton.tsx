'use client';

export default function TableSkeleton({ rows = 5, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div className="bg-white rounded-lg border shadow-sm overflow-hidden">
      {/* Header */}
      <div className="bg-gray-50 px-4 py-3 flex gap-4">
        {Array.from({ length: cols }).map((_, i) => (
          <div key={i} className="h-3 bg-slate-200 rounded animate-pulse" style={{ width: `${60 + Math.random() * 80}px` }} />
        ))}
      </div>
      {/* Rows */}
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="px-4 py-3.5 border-t flex gap-4 items-center">
          {Array.from({ length: cols }).map((_, c) => (
            <div key={c} className={`h-3 bg-slate-100 rounded animate-pulse`}
              style={{ width: `${40 + Math.random() * 100}px`, animationDelay: `${(r * cols + c) * 50}ms` }} />
          ))}
        </div>
      ))}
    </div>
  );
}
