'use client';

import { useState, useRef, useEffect } from 'react';
import { apiFetch } from '@/lib/api';

type Step = 'idle' | 'patient' | 'uploading' | 'done' | 'error';

export default function KioskPage() {
  const [step, setStep] = useState<Step>('idle');
  const [patientInput, setPatientInput] = useState('');
  const [patient, setPatient] = useState<{ id: string; name: string } | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [progress, setProgress] = useState(0);
  const [uploaded, setUploaded] = useState(0);
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const barcodeRef = useRef<HTMLInputElement>(null);
  const idleTimer = useRef<any>(null);

  // 3min inactivity → reset
  const resetIdleTimer = () => {
    if (idleTimer.current) clearTimeout(idleTimer.current);
    idleTimer.current = setTimeout(() => reset(), 180000);
  };

  useEffect(() => {
    resetIdleTimer();
    document.addEventListener('click', resetIdleTimer);
    document.addEventListener('keydown', resetIdleTimer);
    return () => {
      document.removeEventListener('click', resetIdleTimer);
      document.removeEventListener('keydown', resetIdleTimer);
      if (idleTimer.current) clearTimeout(idleTimer.current);  // 언마운트 후 reset() 호출 방지
    };
  }, []);

  const reset = () => {
    setStep('idle'); setPatientInput(''); setPatient(null);
    setFiles([]); setProgress(0); setUploaded(0); setError('');
  };

  const matchPatient = async () => {
    if (!patientInput.trim()) return;
    try {
      // Try to find patient in the system
      const resp = await apiFetch<any>(`/api/v1/patients?search=${encodeURIComponent(patientInput)}&limit=1`);
      const patients = resp.patients || resp.results || [];
      if (patients.length > 0) {
        setPatient({ id: patients[0].patient_id, name: patients[0].patient_name });
      } else {
        setPatient({ id: patientInput, name: patientInput });
      }
      setStep('patient');
    } catch {
      setPatient({ id: patientInput, name: patientInput });
      setStep('patient');
    }
  };

  const handleBarcode = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') matchPatient();
  };

  const selectFiles = () => {
    if (inputRef.current) inputRef.current.click();
  };

  const doUpload = async () => {
    if (files.length === 0 || !patient) return;
    setStep('uploading');
    setProgress(0);

    const fd = new FormData();
    files.forEach(f => fd.append('files', f));

    try {
      const res = await apiFetch<any>(
        `/api/v1/upload/files?auto_validate=true&source=kiosk`,
        { method: 'POST', body: fd, headers: {} }
      );
      setUploaded(res.uploaded || 0);
      setStep('done');
    } catch (e: any) {
      setError(e.message || '업로드에 실패했습니다.');
      setStep('error');
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-800 to-slate-900 text-white flex flex-col items-center justify-center p-8"
         onClick={resetIdleTimer}>

      {/* Header */}
      <div className="text-center mb-8">
        <h1 className="text-3xl font-bold">WeRU.B PACS</h1>
        <p className="text-slate-400 mt-1">영상 업로드 키오스크</p>
      </div>

      {/* IDLE */}
      {step === 'idle' && (
        <div className="w-full max-w-lg space-y-6">
          <div className="bg-slate-700/50 rounded-3xl p-8 text-center">
            <div className="text-6xl mb-4">💿</div>
            <p className="text-xl font-medium mb-2">CD/DVD 또는 USB를 넣어주세요</p>
            <p className="text-slate-400">또는 아래에서 파일을 선택하세요</p>
          </div>

          <div className="bg-slate-700/50 rounded-3xl p-6">
            <p className="text-sm text-slate-400 mb-3">환자 확인</p>
            <div className="flex gap-2">
              <input ref={barcodeRef} type="text" value={patientInput}
                onChange={e => setPatientInput(e.target.value)}
                onKeyDown={handleBarcode}
                placeholder="바코드 스캔 또는 환자번호 입력"
                className="flex-1 px-4 py-4 bg-slate-600 rounded-2xl text-white text-lg placeholder-slate-400 outline-none focus:ring-2 ring-blue-400"
                autoFocus />
              <button onClick={matchPatient}
                className="px-6 py-4 bg-blue-600 rounded-2xl text-lg font-medium hover:bg-blue-700 transition min-w-[80px]">
                확인
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Patient confirmed */}
      {step === 'patient' && patient && (
        <div className="w-full max-w-lg space-y-6">
          <div className="bg-green-900/30 border border-green-700 rounded-3xl p-6 text-center">
            <div className="text-4xl mb-2">✅</div>
            <p className="text-xl font-medium">{patient.name}</p>
            <p className="text-green-400 text-sm">환자번호: {patient.id}</p>
          </div>

          <button onClick={selectFiles}
            className="w-full bg-blue-600 hover:bg-blue-700 rounded-3xl p-8 text-center transition">
            <div className="text-5xl mb-3">📂</div>
            <p className="text-xl font-medium">파일 선택</p>
            <p className="text-blue-300 text-sm">CD/DVD/USB에서 DICOM 파일을 선택하세요</p>
          </button>

          <input ref={inputRef} type="file" multiple
            // @ts-ignore
            webkitdirectory="" directory=""
            onChange={e => {
              if (e.target.files) {
                const dcms = Array.from(e.target.files).filter(f =>
                  f.name.endsWith('.dcm') || f.name.endsWith('.dicom') || !f.name.includes('.') || f.size > 10000
                );
                setFiles(dcms);
              }
            }} className="hidden" />

          {files.length > 0 && (
            <>
              <div className="bg-slate-700/50 rounded-3xl p-4 text-center">
                <p className="text-2xl font-bold">{files.length}</p>
                <p className="text-slate-400">개 파일 선택됨</p>
                <p className="text-xs text-slate-500">{(files.reduce((s, f) => s + f.size, 0) / 1024 / 1024).toFixed(1)} MB</p>
              </div>

              <button onClick={doUpload}
                className="w-full py-5 bg-green-600 hover:bg-green-700 rounded-3xl text-xl font-bold transition">
                업로드 시작
              </button>
            </>
          )}

          <button onClick={reset} className="w-full py-3 text-slate-400 hover:text-white text-sm">처음으로</button>
        </div>
      )}

      {/* Uploading */}
      {step === 'uploading' && (
        <div className="w-full max-w-lg text-center space-y-6">
          <div className="text-6xl animate-pulse">🔄</div>
          <p className="text-2xl font-medium">업로드 중...</p>
          <div className="w-full bg-slate-700 rounded-full h-4">
            <div className="bg-blue-500 h-4 rounded-full transition-all animate-pulse" style={{ width: '60%' }} />
          </div>
          <p className="text-slate-400">잠시만 기다려주세요</p>
        </div>
      )}

      {/* Done */}
      {step === 'done' && (
        <div className="w-full max-w-lg text-center space-y-6">
          <div className="text-6xl">✅</div>
          <p className="text-2xl font-bold">업로드 완료</p>
          <p className="text-slate-300">{uploaded}개 파일이 성공적으로 업로드되었습니다.</p>
          <p className="text-sm text-slate-400">CD를 꺼내주세요.</p>
          <button onClick={reset}
            className="w-full py-5 bg-blue-600 hover:bg-blue-700 rounded-3xl text-xl font-medium transition mt-8">
            처음으로
          </button>
        </div>
      )}

      {/* Error */}
      {step === 'error' && (
        <div className="w-full max-w-lg text-center space-y-6">
          <div className="text-6xl">❌</div>
          <p className="text-2xl font-bold text-red-400">오류 발생</p>
          <p className="text-slate-300">직원에게 문의하세요.</p>
          <p className="text-xs text-slate-500 bg-slate-800 rounded-xl p-3">{error}</p>
          <button onClick={reset}
            className="w-full py-5 bg-slate-600 hover:bg-slate-700 rounded-3xl text-xl font-medium transition">
            처음으로
          </button>
        </div>
      )}
    </div>
  );
}
