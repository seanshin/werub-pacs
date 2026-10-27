import React, { useState, useEffect } from 'react';

interface Props {
  aiService: any;
}

export default function ServerStatus({ aiService }: Props) {
  const [status, setStatus] = useState<string>('checking');

  useEffect(() => {
    if (!aiService) return;
    let mounted = true;
    aiService.getServerStatus().then((res: any) => {
      if (!mounted) return;
      setStatus(res?.healthy || res?.ollama_running || res?.status === 'ok' ? 'online' : 'offline');
    }).catch(() => mounted && setStatus('offline'));
    return () => { mounted = false; };
  }, [aiService]);

  const colors = {
    checking: 'text-gray-500',
    online: 'text-green-400',
    offline: 'text-red-400',
  };
  const labels = {
    checking: '확인 중',
    online: '정상',
    offline: '오프라인',
  };

  return (
    <span className={`text-[11px] font-medium ${colors[status]}`}>
      {status === 'online' ? '●' : status === 'offline' ? '●' : '○'} {labels[status]}
    </span>
  );
}
