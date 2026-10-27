import React from 'react';

interface Props {
  label: string;
  description: string;
  loading: boolean;
  disabled?: boolean;
  disabledReason?: string;
  variant?: 'primary' | 'secondary';
  onClick: () => void;
}

export default function AiActionButton({ label, description, loading, disabled, disabledReason, variant = 'secondary', onClick }: Props) {
  const isPrimary = variant === 'primary';
  const isDisabled = disabled || loading;

  return (
    <button
      onClick={onClick}
      disabled={isDisabled}
      title={disabled ? disabledReason : undefined}
      className={`w-full rounded-lg px-3 py-2.5 text-left transition ${
        isDisabled
          ? 'opacity-40 cursor-not-allowed'
          : isPrimary
            ? 'bg-purple-600/20 border border-purple-500/40 hover:bg-purple-600/30'
            : 'bg-[#1e293b] border border-[#334155] hover:bg-[#334155]'
      }`}
    >
      <div className="flex items-center justify-between">
        <span className={`text-sm font-semibold ${isPrimary ? 'text-purple-300' : 'text-gray-200'}`}>
          {label}
        </span>
        {loading && (
          <span className="text-xs text-gray-400 animate-pulse">분석 중...</span>
        )}
      </div>
      <div className="text-xs text-gray-500 mt-0.5">{description}</div>
    </button>
  );
}
