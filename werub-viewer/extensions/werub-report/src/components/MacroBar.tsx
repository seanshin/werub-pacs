import React from 'react';
import type { Template } from '../services/ReportService';

interface Props {
  templates: Template[];
  onInsert: (text: string) => void;
}

export default function MacroBar({ templates, onInsert }: Props) {
  const macros = templates.flatMap(t =>
    Object.entries(t.macros || {}).map(([key, val]) => ({ key, val, tid: t.id }))
  );
  if (!macros.length) return null;

  return (
    <div className="mb-2">
      <div className="text-muted-foreground mb-1 text-xs font-semibold">단축어</div>
      <div className="flex flex-wrap gap-1">
        {macros.map(m => (
          <button
            key={`${m.tid}-${m.key}`}
            onClick={() => onInsert(m.val)}
            title={m.val}
            className="rounded border border-blue-800/40 px-1.5 py-0.5 text-[11px] text-blue-400 hover:bg-blue-900/30 transition"
          >
            {m.key}
          </button>
        ))}
      </div>
    </div>
  );
}
