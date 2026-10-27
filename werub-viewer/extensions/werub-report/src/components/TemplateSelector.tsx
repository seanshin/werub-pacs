import React from 'react';
import type { Template } from '../services/ReportService';

interface Props {
  templates: Template[];
  onApply: (template: Template) => void;
}

export default function TemplateSelector({ templates, onApply }: Props) {
  if (!templates.length) return null;
  return (
    <div className="mb-2">
      <div className="text-muted-foreground mb-1 text-xs font-semibold">템플릿</div>
      <div className="flex flex-wrap gap-1">
        {templates.map(t => (
          <button
            key={t.id}
            onClick={() => onApply(t)}
            className="rounded bg-[#1e293b] px-2 py-1 text-xs text-gray-300 hover:bg-[#334155] hover:text-white transition"
          >
            {t.modality} {t.name.split('(')[0].trim()}
          </button>
        ))}
      </div>
    </div>
  );
}
