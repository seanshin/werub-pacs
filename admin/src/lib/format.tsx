/** 날짜/환자명 포맷 유틸리티 */

export function formatDate(dicomDate: string | null | undefined): string {
  if (!dicomDate) return '-';
  const d = dicomDate.replace(/[^0-9]/g, '');
  if (d.length !== 8) return dicomDate;
  return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`;
}

export function formatPatientName(name: string | null | undefined): string {
  if (!name || name === '-') return '(이름 없음)';
  return name.replace(/\^+/g, ' ').replace(/\s+/g, ' ').trim() || '(이름 없음)';
}

export const modalityColor: Record<string, string> = {
  CR: 'bg-blue-100 text-blue-700',
  DX: 'bg-blue-100 text-blue-700',
  CT: 'bg-purple-100 text-purple-700',
  MR: 'bg-green-100 text-green-700',
  US: 'bg-yellow-100 text-yellow-700',
  SR: 'bg-gray-100 text-gray-600',
  PT: 'bg-orange-100 text-orange-700',
  NM: 'bg-pink-100 text-pink-700',
  SM: 'bg-rose-100 text-rose-700',
};

export function ModalityBadge({ modality }: { modality: string | null | undefined }) {
  if (!modality) return <span className="text-gray-400">-</span>;
  const mods = modality.split(/[,\\\/]/).filter(Boolean);
  return (
    <span className="flex gap-0.5 flex-wrap">
      {mods.map(m => (
        <span key={m} className={`px-1.5 py-0.5 rounded text-[11px] font-semibold ${modalityColor[m.trim()] || 'bg-gray-100 text-gray-600'}`}>
          {m.trim()}
        </span>
      ))}
    </span>
  );
}
