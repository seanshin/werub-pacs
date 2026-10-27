import React from 'react';

const STATUS_MAP: Record<string, { label: string; className: string }> = {
  final: { label: '판독 완료', className: 'bg-green-700/40 text-green-400' },
  draft: { label: '작성 중', className: 'bg-yellow-700/40 text-yellow-400' },
  preliminary: { label: '예비 판독', className: 'bg-blue-700/40 text-blue-400' },
};

export default function StatusBadge({ status }: { status?: string }) {
  if (!status) {
    return <span className="rounded px-2 py-0.5 text-xs font-medium bg-gray-700/40 text-gray-400">미판독</span>;
  }
  const { label, className } = STATUS_MAP[status] || { label: status, className: 'bg-gray-700/40 text-gray-400' };
  return <span className={`rounded px-2 py-0.5 text-xs font-semibold ${className}`}>{label}</span>;
}
