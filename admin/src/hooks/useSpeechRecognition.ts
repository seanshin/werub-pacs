'use client';

import { useState, useRef, useCallback, useEffect } from 'react';

/**
 * Speech-to-text hook using browser Web Speech API.
 *
 * Usage:
 *   const { isListening, transcript, startListening, stopListening, error } = useSpeechRecognition({
 *     language: 'ko-KR',
 *     continuous: true,
 *     onResult: (text) => setFindings(prev => prev + ' ' + text),
 *   });
 */

interface SpeechRecognitionOptions {
  language?: string;
  continuous?: boolean;
  interimResults?: boolean;
  onResult?: (transcript: string, isFinal: boolean) => void;
  onEnd?: () => void;
  onError?: (error: string) => void;
}

interface SpeechRecognitionReturn {
  isListening: boolean;
  isSupported: boolean;
  transcript: string;
  interimTranscript: string;
  startListening: () => void;
  stopListening: () => void;
  error: string | null;
}

export function useSpeechRecognition(options: SpeechRecognitionOptions = {}): SpeechRecognitionReturn {
  const {
    language = 'ko-KR',
    continuous = true,
    interimResults = true,
    onResult,
    onEnd,
    onError,
  } = options;

  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [interimTranscript, setInterimTranscript] = useState('');
  const [error, setError] = useState<string | null>(null);
  const recognitionRef = useRef<any>(null);

  const isSupported = typeof window !== 'undefined' &&
    ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window);

  const startListening = useCallback(() => {
    if (!isSupported) {
      setError('음성 인식이 지원되지 않는 브라우저입니다. Chrome 또는 Edge를 사용하세요.');
      onError?.('Browser not supported');
      return;
    }

    setError(null);
    setInterimTranscript('');

    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    const recognition = new SpeechRecognition();

    recognition.lang = language;
    recognition.continuous = continuous;
    recognition.interimResults = interimResults;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      setIsListening(true);
    };

    recognition.onresult = (event: any) => {
      let final = '';
      let interim = '';

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) {
          final += result[0].transcript;
        } else {
          interim += result[0].transcript;
        }
      }

      if (final) {
        setTranscript(prev => prev + final);
        onResult?.(final, true);
      }
      setInterimTranscript(interim);
      if (interim) {
        onResult?.(interim, false);
      }
    };

    recognition.onerror = (event: any) => {
      const errorMsg = event.error === 'no-speech' ? '음성이 감지되지 않았습니다'
        : event.error === 'audio-capture' ? '마이크를 찾을 수 없습니다'
        : event.error === 'not-allowed' ? '마이크 권한이 거부되었습니다'
        : `음성 인식 오류: ${event.error}`;
      setError(errorMsg);
      onError?.(errorMsg);
      setIsListening(false);
    };

    recognition.onend = () => {
      setIsListening(false);
      setInterimTranscript('');
      onEnd?.();

      // Auto-restart if continuous mode and not manually stopped
      if (continuous && recognitionRef.current === recognition) {
        try {
          recognition.start();
        } catch (e) {
          // Already started or other error
        }
      }
    };

    recognitionRef.current = recognition;
    recognition.start();
  }, [isSupported, language, continuous, interimResults, onResult, onEnd, onError]);

  const stopListening = useCallback(() => {
    if (recognitionRef.current) {
      const recognition = recognitionRef.current;
      recognitionRef.current = null; // Prevent auto-restart
      recognition.stop();
      setIsListening(false);
      setInterimTranscript('');
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.stop();
        recognitionRef.current = null;
      }
    };
  }, []);

  return {
    isListening,
    isSupported,
    transcript,
    interimTranscript,
    startListening,
    stopListening,
    error,
  };
}
