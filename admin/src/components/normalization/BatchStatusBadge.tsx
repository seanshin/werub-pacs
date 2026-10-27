'use client';

const STATUS_MAP = {
  queued:     { label: '대기중',  cls: 'bg-gray-100 text-gray-600 border-gray-300' },
  processing: { label: '처리중',  cls: 'bg-blue-100 text-blue-700 border-blue-300' },
  completed:  { label: '완료',    cls: 'bg-green-100 text-green-700 border-green-300' },
  failed:     { label: '실패',    cls: 'bg-red-100 text-red-700 border-red-300' },
} as const;

export function BatchStatusBadge({ status }: { status: keyof typeof STATUS_MAP }) {
  const { label, cls } = STATUS_MAP[status];
  return (
    <span
      role="status"
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${cls}`}
    >
      {label}
    </span>
  );
}
