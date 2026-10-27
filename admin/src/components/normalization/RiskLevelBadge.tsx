'use client';

const RISK_MAP = {
  safe:   { label: '안전', cls: 'bg-green-50 text-green-700 border-green-200' },
  medium: { label: '중간위험', cls: 'bg-yellow-100 text-yellow-800 border-yellow-300' },
  risky:  { label: '위험', cls: 'bg-red-100 text-red-700 border-red-300' },
} as const;

export function RiskLevelBadge({ level }: { level: keyof typeof RISK_MAP }) {
  const { label, cls } = RISK_MAP[level];
  return (
    <span
      role="status"
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${cls}`}
    >
      {label}
    </span>
  );
}
