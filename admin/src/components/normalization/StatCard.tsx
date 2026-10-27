'use client';

interface StatCardProps {
  label: string;
  value: number | string;
  sub?: string;
  color?: string;   // Tailwind text color class; default 'text-gray-900'
}

export function StatCard({ label, value, sub, color }: StatCardProps) {
  return (
    <div className="bg-white rounded-lg border p-4 shadow-sm">
      <p className="text-sm text-gray-500">{label}</p>
      <p className={`text-3xl font-bold mt-1 ${color || 'text-gray-900'}`}>{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}
