import React, { useState, useRef, useCallback } from 'react';

interface Props {
  findings: string;
  impression: string;
  recommendation: string;
  urgency: string;
  readOnly: boolean;
  onChange: (field: string, value: string) => void;
}

function DictationButton({ field, currentValue, onChange }: { field: string; currentValue: string; onChange: (f: string, v: string) => void }) {
  const [listening, setListening] = useState(false);
  const recRef = useRef<any>(null);

  const toggle = useCallback(() => {
    if (listening) {
      recRef.current?.stop();
      recRef.current = null;
      setListening(false);
      return;
    }
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) return;

    const r = new SR();
    r.lang = 'ko-KR';
    r.continuous = true;
    r.interimResults = false;
    r.onresult = (e: any) => {
      let text = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) text += e.results[i][0].transcript;
      }
      if (text) onChange(field, currentValue + (currentValue ? ' ' : '') + text);
    };
    r.onerror = () => { setListening(false); recRef.current = null; };
    r.onend = () => { if (recRef.current) try { r.start(); } catch {} };
    recRef.current = r;
    r.start();
    setListening(true);
  }, [listening, field, currentValue, onChange]);

  const isSupported = typeof window !== 'undefined' &&
    ('SpeechRecognition' in (window as any) || 'webkitSpeechRecognition' in (window as any));
  if (!isSupported) return null;

  return (
    <button
      onClick={toggle}
      title={listening ? '음성 입력 중지' : '음성 입력'}
      className={`ml-1 px-1.5 py-0.5 rounded text-[11px] transition ${
        listening ? 'bg-red-500 text-white animate-pulse' : 'bg-gray-700 text-gray-400 hover:bg-red-900/40'
      }`}
    >
      {listening ? '■ 중지' : '🎤'}
    </button>
  );
}

export default function ReportForm({ findings, impression, recommendation, urgency, readOnly, onChange }: Props) {
  const inputClass = 'w-full rounded bg-[#0f1629] border border-[#333] text-gray-200 p-2 text-sm resize-y focus:border-blue-500 focus:outline-none';
  const readOnlyClass = 'w-full rounded bg-[#0f1629] p-2 text-sm whitespace-pre-wrap';

  return (
    <div className="space-y-3">
      <div>
        <label className="text-muted-foreground mb-1 flex items-center text-xs font-semibold">
          소견 (Findings)
          {!readOnly && <DictationButton field="findings" currentValue={findings} onChange={onChange} />}
        </label>
        {readOnly ? (
          <div className={readOnlyClass}>{findings || '-'}</div>
        ) : (
          <textarea
            rows={6}
            value={findings}
            onChange={e => onChange('findings', e.target.value)}
            className={inputClass}
            placeholder="소견을 입력하세요..."
          />
        )}
      </div>

      <div>
        <label className="text-muted-foreground mb-1 flex items-center text-xs font-semibold">
          결론 (Impression)
          {!readOnly && <DictationButton field="impression" currentValue={impression} onChange={onChange} />}
        </label>
        {readOnly ? (
          <div className={`${readOnlyClass} text-green-400`}>{impression || '-'}</div>
        ) : (
          <textarea
            rows={3}
            value={impression}
            onChange={e => onChange('impression', e.target.value)}
            className={inputClass}
            placeholder="결론을 입력하세요..."
          />
        )}
      </div>

      <div>
        <label className="text-muted-foreground mb-1 block text-xs font-semibold">권고 사항</label>
        {readOnly ? (
          <div className={readOnlyClass}>{recommendation || '-'}</div>
        ) : (
          <textarea
            rows={2}
            value={recommendation}
            onChange={e => onChange('recommendation', e.target.value)}
            className={inputClass}
            placeholder="권고 사항 (선택)"
          />
        )}
      </div>

      {!readOnly && (
        <div>
          <label className="text-muted-foreground mb-1 block text-xs font-semibold">긴급도</label>
          <select
            value={urgency}
            onChange={e => onChange('urgency', e.target.value)}
            className="w-full rounded bg-[#0f1629] border border-[#333] text-gray-200 p-2 text-sm focus:outline-none"
          >
            <option value="normal">정상</option>
            <option value="non_urgent">비긴급 이상</option>
            <option value="urgent">긴급</option>
          </select>
        </div>
      )}
    </div>
  );
}
