'use client';

import { useState, useRef } from 'react';
import { apiFetch } from '@/lib/api';
import Breadcrumb from '@/components/ui/Breadcrumb';

type FileResult = {
  filename: string; status: string; reason?: string;
  orthanc_id?: string; validation?: any;
};

export default function UploadCenterPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState<FileResult[]>([]);
  const [progress, setProgress] = useState(0);
  const [autoValidate, setAutoValidate] = useState(true);
  const [autoNormalize, setAutoNormalize] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: string } | null>(null);
  const dropRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = (newFiles: FileList | File[]) => {
    const arr = Array.from(newFiles).filter(f => {
      const ext = f.name.toLowerCase();
      return ext.endsWith('.dcm') || ext.endsWith('.zip') || ext.endsWith('.dicom') || !ext.includes('.');
    });
    setFiles(prev => [...prev, ...arr]);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer.files.length > 0) addFiles(e.dataTransfer.files);
  };

  const uploadAll = async () => {
    if (files.length === 0) return;
    setUploading(true);
    setResults([]);
    setProgress(0);

    const zipFiles = files.filter(f => f.name.toLowerCase().endsWith('.zip'));
    const dcmFiles = files.filter(f => !f.name.toLowerCase().endsWith('.zip'));
    const allResults: FileResult[] = [];
    let done = 0;

    // Upload ZIPs
    for (const zf of zipFiles) {
      const fd = new FormData();
      fd.append('file', zf);
      try {
        const res = await apiFetch<any>(`/api/v1/upload/zip?auto_validate=${autoValidate}`, { method: 'POST', body: fd, headers: {} });
        allResults.push({ filename: zf.name, status: 'uploaded', reason: `${res.uploaded} files from ZIP` });
      } catch (e: any) {
        allResults.push({ filename: zf.name, status: 'failed', reason: e.message });
      }
      done++;
      setProgress(Math.round((done / files.length) * 100));
      setResults([...allResults]);
    }

    // Upload DICOMs in batches of 10
    for (let i = 0; i < dcmFiles.length; i += 10) {
      const batch = dcmFiles.slice(i, i + 10);
      const fd = new FormData();
      batch.forEach(f => fd.append('files', f));
      try {
        const res = await apiFetch<any>(`/api/v1/upload/files?auto_validate=${autoValidate}&auto_normalize=${autoNormalize}`, { method: 'POST', body: fd, headers: {} });
        allResults.push(...(res.results || []));
      } catch (e: any) {
        batch.forEach(f => allResults.push({ filename: f.name, status: 'failed', reason: e.message }));
      }
      done += batch.length;
      setProgress(Math.round((done / files.length) * 100));
      setResults([...allResults]);
    }

    setUploading(false);
    setProgress(100);
    const uploaded = allResults.filter(r => r.status === 'uploaded').length;
    setToast({ msg: `업로드 완료: ${uploaded}/${allResults.length}건 성공`, type: uploaded > 0 ? 'success' : 'error' });
    setTimeout(() => setToast(null), 5000);
  };

  const uploadedCount = results.filter(r => r.status === 'uploaded').length;
  const failedCount = results.filter(r => r.status === 'failed').length;
  const skippedCount = results.filter(r => r.status === 'skipped').length;

  return (
    <div className="p-4 sm:p-6 max-w-[1200px] mx-auto">
      {toast && (
        <div className={`fixed top-4 right-4 z-[9999] px-4 py-3 rounded-xl shadow-lg text-sm font-medium ${toast.type === 'error' ? 'bg-red-500' : 'bg-green-600'} text-white`}>
          {toast.msg}
        </div>
      )}

      <Breadcrumb items={[{ label: '관리', href: '/' }, { label: 'DICOM 업로드' }]} />
      <h1 className="text-2xl font-bold mt-1 mb-6">DICOM 업로드 센터</h1>

      {/* Drop zone */}
      <div ref={dropRef}
        onDragOver={e => { e.preventDefault(); e.stopPropagation(); }}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className="border-2 border-dashed border-gray-300 rounded-2xl p-10 text-center cursor-pointer hover:border-indigo-400 hover:bg-indigo-50/30 transition mb-4">
        <div className="text-4xl mb-2">📂</div>
        <p className="text-gray-600 font-medium">DICOM 파일, 폴더, 또는 ZIP을 여기에 드래그하세요</p>
        <p className="text-xs text-gray-400 mt-1">지원: .dcm, .zip, DICOM 파일 (최대 2GB)</p>
        <input ref={inputRef} type="file" multiple accept=".dcm,.zip,.dicom,application/dicom"
          onChange={e => e.target.files && addFiles(e.target.files)} className="hidden" />
      </div>

      {/* Options */}
      <div className="flex gap-4 mb-4 text-sm">
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={autoValidate} onChange={e => setAutoValidate(e.target.checked)} className="rounded" />
          자동 검증
        </label>
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={autoNormalize} onChange={e => setAutoNormalize(e.target.checked)} className="rounded" />
          자동 정규화
        </label>
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div className="bg-white rounded-xl border shadow-sm mb-4">
          <div className="p-3 border-b bg-gray-50 flex items-center justify-between">
            <span className="text-sm font-medium">{files.length}개 파일 선택됨</span>
            <div className="flex gap-2">
              <button onClick={() => { setFiles([]); setResults([]); setProgress(0); }}
                className="px-3 py-1.5 text-xs border rounded-lg hover:bg-gray-100">초기화</button>
              <button onClick={uploadAll} disabled={uploading}
                className="px-4 py-1.5 bg-indigo-600 text-white rounded-lg text-xs font-medium hover:bg-indigo-700 disabled:opacity-50">
                {uploading ? `업로드 중... ${progress}%` : '업로드 시작'}
              </button>
            </div>
          </div>

          {/* Progress bar */}
          {uploading && (
            <div className="px-3 py-2 border-b">
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div className="bg-indigo-500 h-2 rounded-full transition-all" style={{ width: `${progress}%` }} />
              </div>
              <div className="flex justify-between text-[10px] text-gray-400 mt-1">
                <span>완료 {uploadedCount} / 실패 {failedCount} / 건너뜀 {skippedCount}</span>
                <span>{progress}%</span>
              </div>
            </div>
          )}

          {/* Results */}
          {results.length > 0 && (
            <div className="max-h-60 overflow-y-auto divide-y">
              {results.map((r, i) => (
                <div key={i} className="px-3 py-1.5 flex items-center gap-2 text-xs">
                  <span>{r.status === 'uploaded' ? '✅' : r.status === 'skipped' ? '⏭️' : '❌'}</span>
                  <span className="font-mono text-gray-600 flex-1 truncate">{r.filename}</span>
                  {r.validation && (
                    <span className="text-[9px] text-gray-400">
                      {r.validation.counts?.critical > 0 && <span className="text-red-500 mr-1">C:{r.validation.counts.critical}</span>}
                      {r.validation.counts?.error > 0 && <span className="text-orange-500 mr-1">E:{r.validation.counts.error}</span>}
                      {r.validation.counts?.warning > 0 && <span className="text-yellow-600 mr-1">W:{r.validation.counts.warning}</span>}
                      {r.validation.normalized && <span className="text-green-600">정규화</span>}
                    </span>
                  )}
                  {r.reason && <span className="text-gray-400">{r.reason}</span>}
                </div>
              ))}
            </div>
          )}

          {/* Pending files (before upload) */}
          {results.length === 0 && (
            <div className="max-h-40 overflow-y-auto divide-y">
              {files.map((f, i) => (
                <div key={i} className="px-3 py-1.5 flex items-center gap-2 text-xs">
                  <span>📄</span>
                  <span className="font-mono text-gray-600 flex-1 truncate">{f.name}</span>
                  <span className="text-gray-400">{(f.size / 1024).toFixed(0)} KB</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
