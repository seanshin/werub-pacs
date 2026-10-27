'use client';

import { Suspense, useEffect, useState, useRef } from 'react';
import { useSearchParams } from 'next/navigation';

const API_BASE = '/pacs-api';

export default function PatientUploadPage() {
  return <Suspense fallback={<div className="min-h-screen flex items-center justify-center">불러오는 중...</div>}><PatientUploadInner /></Suspense>;
}

function PatientUploadInner() {
  const searchParams = useSearchParams();
  const token = searchParams.get('token') || '';

  const [step, setStep] = useState<'verify' | 'consent' | 'upload' | 'done' | 'error'>('verify');
  const [patient, setPatient] = useState<{ patient_id: string; patient_name: string } | null>(null);
  const [error, setError] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<any>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!token) { setStep('error'); setError('업로드 링크가 유효하지 않습니다.'); return; }
    verifyToken();
  }, [token]);

  const verifyToken = async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/v1/patient-upload/verify?token=${token}`);
      const data = await resp.json();
      if (data.valid) {
        setPatient({ patient_id: data.patient_id, patient_name: data.patient_name });
        setStep(data.consent_agreed ? 'upload' : 'consent');
      } else {
        setStep('error');
        setError(data.error === 'Token expired' ? '링크가 만료되었습니다. 접수 데스크에 문의하세요.' :
                 data.error === 'Token already used' ? '이미 사용된 링크입니다.' : '유효하지 않은 링크입니다.');
      }
    } catch { setStep('error'); setError('서버 연결에 실패했습니다.'); }
  };

  const submitConsent = async () => {
    try {
      const resp = await fetch(`${API_BASE}/api/v1/patient-upload/consent?token=${token}`, { method: 'POST' });
      const data = await resp.json();
      if (data.ok) setStep('upload');
      else setError('동의 처리에 실패했습니다.');
    } catch { setError('서버 연결에 실패했습니다.'); }
  };

  const doUpload = async () => {
    if (files.length === 0) return;
    setUploading(true);
    const fd = new FormData();
    files.forEach(f => fd.append('files', f));
    try {
      const resp = await fetch(`${API_BASE}/api/v1/patient-upload/files?token=${token}`, { method: 'POST', body: fd });
      const data = await resp.json();
      if (data.ok) { setUploadResult(data); setStep('done'); }
      else setError(data.error || '업로드에 실패했습니다.');
    } catch { setError('업로드 중 오류가 발생했습니다.'); }
    setUploading(false);
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-blue-50 to-white flex items-center justify-center p-4">
      <div className="bg-white rounded-3xl shadow-xl w-full max-w-md overflow-hidden">
        {/* Header */}
        <div className="bg-blue-600 text-white p-6 text-center">
          <h1 className="text-xl font-bold">WeRU.B PACS</h1>
          <p className="text-blue-200 text-sm mt-1">영상 업로드</p>
        </div>

        <div className="p-6">
          {/* Error */}
          {step === 'error' && (
            <div className="text-center py-8">
              <div className="text-5xl mb-4">⚠️</div>
              <p className="text-gray-700 font-medium">{error}</p>
              <p className="text-sm text-gray-400 mt-2">접수 데스크에서 새 링크를 발급받으세요.</p>
            </div>
          )}

          {/* Verify */}
          {step === 'verify' && (
            <div className="text-center py-8">
              <div className="animate-spin text-3xl mb-4">⏳</div>
              <p className="text-gray-500">확인 중...</p>
            </div>
          )}

          {/* Consent */}
          {step === 'consent' && patient && (
            <div>
              <p className="text-lg font-medium mb-1">안녕하세요, {patient.patient_name}님</p>
              <p className="text-sm text-gray-500 mb-4">영상 업로드 전 아래 동의가 필요합니다.</p>

              <div className="bg-gray-50 rounded-xl p-4 text-xs text-gray-600 space-y-2 mb-4 max-h-40 overflow-y-auto">
                <p className="font-bold">개인정보 수집·이용 동의</p>
                <p>1. 수집 목적: 의료 영상 진단 및 판독을 위한 DICOM 영상 데이터 수집</p>
                <p>2. 수집 항목: DICOM 파일 (환자명, 생년월일, 영상 데이터 포함)</p>
                <p>3. 보유 기간: 의료법에 따라 5년 보존 후 파기</p>
                <p>4. 동의 거부 시: 영상 업로드가 불가합니다</p>
                <p>5. 업로드된 영상은 담당 의료진 승인 후 시스템에 등록됩니다</p>
              </div>

              <button onClick={submitConsent}
                className="w-full py-3 bg-blue-600 text-white rounded-xl font-medium text-lg hover:bg-blue-700 transition">
                동의하고 계속하기
              </button>
            </div>
          )}

          {/* Upload */}
          {step === 'upload' && patient && (
            <div>
              <p className="text-lg font-medium mb-1">{patient.patient_name}님</p>
              <p className="text-sm text-gray-500 mb-4">아래 방법으로 영상을 업로드하세요.</p>

              {error && <p className="text-red-500 text-sm mb-3 bg-red-50 p-2 rounded">{error}</p>}

              <div className="grid grid-cols-2 gap-3 mb-4">
                <button onClick={() => inputRef.current?.click()}
                  className="p-4 border-2 border-dashed rounded-xl text-center hover:border-blue-400 hover:bg-blue-50 transition">
                  <div className="text-3xl mb-1">📁</div>
                  <div className="text-sm font-medium">파일 선택</div>
                  <div className="text-[10px] text-gray-400">CD/USB에서</div>
                </button>
                <button onClick={() => {
                  const inp = document.createElement('input');
                  inp.type = 'file'; inp.accept = 'image/*'; inp.capture = 'environment'; inp.multiple = true;
                  inp.onchange = () => inp.files && setFiles(prev => [...prev, ...Array.from(inp.files!)]);
                  inp.click();
                }}
                  className="p-4 border-2 border-dashed rounded-xl text-center hover:border-blue-400 hover:bg-blue-50 transition">
                  <div className="text-3xl mb-1">📷</div>
                  <div className="text-sm font-medium">사진 촬영</div>
                  <div className="text-[10px] text-gray-400">필름/문서</div>
                </button>
              </div>

              <input ref={inputRef} type="file" multiple accept=".dcm,.zip,.dicom,application/dicom,image/*"
                onChange={e => e.target.files && setFiles(prev => [...prev, ...Array.from(e.target.files!)])}
                className="hidden" />

              {files.length > 0 && (
                <div className="mb-4">
                  <div className="text-sm font-medium mb-1">선택된 파일 ({files.length}건)</div>
                  <div className="bg-gray-50 rounded-xl p-2 max-h-32 overflow-y-auto space-y-1">
                    {files.map((f, i) => (
                      <div key={i} className="flex items-center gap-2 text-xs">
                        <span>📄</span>
                        <span className="flex-1 truncate text-gray-600">{f.name}</span>
                        <span className="text-gray-400">{(f.size / 1024).toFixed(0)}KB</span>
                        <button onClick={() => setFiles(prev => prev.filter((_, j) => j !== i))}
                          className="text-red-400 hover:text-red-600">✕</button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <button onClick={doUpload} disabled={files.length === 0 || uploading}
                className="w-full py-3 bg-blue-600 text-white rounded-xl font-medium text-lg hover:bg-blue-700 disabled:opacity-50 transition">
                {uploading ? '업로드 중...' : '업로드 제출'}
              </button>
            </div>
          )}

          {/* Done */}
          {step === 'done' && (
            <div className="text-center py-8">
              <div className="text-5xl mb-4">✅</div>
              <p className="text-lg font-bold text-green-700">업로드 완료</p>
              <p className="text-sm text-gray-500 mt-2">{uploadResult?.files_saved}개 파일이 제출되었습니다.</p>
              <p className="text-xs text-gray-400 mt-1">담당 의료진이 확인 후 시스템에 등록합니다.</p>
              <div className="mt-6 bg-gray-50 rounded-xl p-3 text-xs text-gray-500">
                이 페이지를 닫아도 됩니다.
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
