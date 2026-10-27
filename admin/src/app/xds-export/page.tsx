'use client';

import { useState } from 'react';
import { apiFetch } from '@/lib/api';

type ExportStatus = {
  request_id: string;
  status: 'processing' | 'ready' | 'failed' | 'expired';
  study_count?: number;
  package_bytes?: number;
  expires_at?: string;
  download_token?: string;
  error?: string;
};

function fmtBytes(n?: number): string {
  if (!n) return '-';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export default function XdsExportPage() {
  const [uidsText, setUidsText] = useState('');
  const [patientId, setPatientId] = useState('');
  const [job, setJob] = useState<ExportStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: 'ok' | 'err' } | null>(null);

  const showToast = (msg: string, type: 'ok' | 'err' = 'ok') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };

  const parseUids = () =>
    uidsText.split(/[\s,;]+/).map(s => s.trim()).filter(Boolean);

  const start = async () => {
    const uids = parseUids();
    if (uids.length === 0) {
      showToast('Study Instance UID를 1개 이상 입력하세요.', 'err');
      return;
    }
    setBusy(true);
    setJob(null);
    try {
      const created = await apiFetch<ExportStatus>('/api/v1/xds-export/requests', {
        method: 'POST',
        body: JSON.stringify({ study_instance_uids: uids, patient_id: patientId || null }),
      });
      // poll
      let st: ExportStatus = created;
      for (let i = 0; i < 40 && st.status === 'processing'; i++) {
        await new Promise(r => setTimeout(r, 1500));
        st = await apiFetch<ExportStatus>(`/api/v1/xds-export/requests/${created.request_id}`);
      }
      setJob(st);
      if (st.status === 'ready') showToast(`XDM 패키지 생성 완료 (${st.study_count}건)`);
      else if (st.status === 'failed') showToast(`생성 실패: ${st.error || '알 수 없음'}`, 'err');
    } catch (e) {
      showToast(e instanceof Error ? e.message : '요청 실패', 'err');
    } finally {
      setBusy(false);
    }
  };

  const download = async () => {
    if (!job?.download_token) return;
    try {
      const token = localStorage.getItem('pacs_token');
      const res = await fetch(
        `/pacs-api/api/v1/xds-export/requests/${job.request_id}/download?token=${job.download_token}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} }
      );
      if (!res.ok) throw new Error(`다운로드 실패 (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `xdm_${job.request_id.slice(0, 8)}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      showToast(e instanceof Error ? e.message : '다운로드 실패', 'err');
    }
  };

  return (
    <div className="mx-auto max-w-5xl p-4 sm:p-6">
      <div className="mb-1 flex items-center gap-2">
        <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">기관 간 영상 교환 (XDS-I / XDM)</h1>
        <span className="rounded bg-blue-100 px-2 py-0.5 text-[11px] font-semibold text-blue-700 dark:bg-blue-900 dark:text-blue-200">IHE 표준</span>
      </div>
      <p className="mb-5 text-sm text-gray-500 dark:text-gray-400">
        선택한 검사를 받는 기관의 PACS가 그대로 가져갈 수 있는 <b>IHE 표준 패키지(XDM)</b>로 내보냅니다.
      </p>

      {/* 설명 카드 */}
      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        <InfoCard icon="📦" title="무엇이 만들어지나">
          KOS 매니페스트 + 원본 DICOM + <code className="text-[11px]">METADATA.XML</code>(ebRIM)을 담은
          ZIP. 받는 기관이 표준 도구로 import.
        </InfoCard>
        <InfoCard icon="🔗" title="연동 서버가 필요 없음">
          공유 등록소(Registry)에 <em>전송</em>하는 게 아니라 <em>패키지를 생성</em>하므로,
          교류체계 가입 없이 USB/이메일/포털로 전달 가능.
        </InfoCard>
        <InfoCard icon="🆚" title="환자 추출과의 차이">
          환자 결과 추출은 OpenPACS 전용 포맷. 이건 <b>IHE 표준 포맷</b>이라 타 벤더 PACS도 수용.
        </InfoCard>
      </div>

      {/* 패키지 구조 */}
      <details className="mb-6 rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm dark:border-gray-700 dark:bg-gray-800/50">
        <summary className="cursor-pointer font-semibold text-gray-800 dark:text-gray-200">📁 패키지(XDM ZIP) 구조 상세</summary>
        <pre className="mt-3 overflow-x-auto rounded bg-white p-3 text-[12px] leading-relaxed text-gray-700 dark:bg-gray-900 dark:text-gray-300">{`IHE_XDM/SUBSET01/METADATA.XML   ← ebRIM 메타데이터
                                  · SubmissionSet (제출 단위)
                                  · DocumentEntry (검사별, KOS 참조)
                                  · Association (HasMember)
                                  · 코드 6종(class/format/confidentiality
                                    /facility/practice/type)
IHE_XDM/SUBSET01/DOC00001.dcm   ← KOS 매니페스트 (SOPClass 88.59)
DICOM/<studyUID>/dicom.zip      ← 참조 DICOM 원본 (오프라인 자족)
README.TXT · INDEX.HTM          ← 사람이 읽는 설명`}</pre>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-[12px] text-gray-600 dark:text-gray-400">
          <li><b>XDS-I</b>: IHE Cross-Enterprise Document Sharing for Imaging — 기관 간 영상 공유 프로파일</li>
          <li><b>XDM</b>: 그 오프라인(미디어) 교환 형태 — Registry 없이 패키지로 교환</li>
          <li><b>KOS</b>: Key Object Selection (88.59) — 어떤 영상들이 묶였는지 기술하는 표준 매니페스트</li>
          <li>구조적 최소 적합 — 정식 IHE Gazelle 적합성 인증과는 별개</li>
        </ul>
      </details>

      {/* 생성 폼 */}
      <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <h2 className="mb-3 text-base font-semibold text-gray-900 dark:text-gray-100">패키지 생성</h2>
        <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">
          Study Instance UID (줄바꿈 또는 쉼표로 여러 건)
        </label>
        <textarea
          value={uidsText}
          onChange={e => setUidsText(e.target.value)}
          rows={4}
          placeholder="1.2.276.0.7230010.3.1.2..."
          className="mb-3 w-full rounded-lg border border-gray-300 p-2 font-mono text-[12px] dark:border-gray-600 dark:bg-gray-900 dark:text-gray-200"
        />
        <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">
          환자 ID (선택 — 생략 시 DICOM에서 자동)
        </label>
        <input
          value={patientId}
          onChange={e => setPatientId(e.target.value)}
          placeholder="P2026-0005"
          className="mb-4 w-full max-w-xs rounded-lg border border-gray-300 p-2 text-sm dark:border-gray-600 dark:bg-gray-900 dark:text-gray-200"
        />
        <div className="flex items-center gap-3">
          <button
            onClick={start}
            disabled={busy}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {busy ? '생성 중…' : 'XDM 패키지 생성'}
          </button>
          {job && (
            <span className="text-sm text-gray-600 dark:text-gray-400">
              상태: <b>{job.status}</b>
              {job.study_count != null && ` · ${job.study_count}건`}
              {job.package_bytes != null && ` · ${fmtBytes(job.package_bytes)}`}
            </span>
          )}
        </div>

        {job?.status === 'ready' && (
          <div className="mt-4 flex items-center gap-3 rounded-lg bg-green-50 p-3 dark:bg-green-900/30">
            <span className="text-sm text-green-800 dark:text-green-200">✅ 패키지 준비됨 (1시간 내 다운로드)</span>
            <button
              onClick={download}
              className="rounded-lg bg-green-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-green-700"
            >
              ⬇ XDM ZIP 다운로드
            </button>
          </div>
        )}
        {job?.status === 'failed' && (
          <div className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
            생성 실패: {job.error || '알 수 없음'}
          </div>
        )}
      </div>

      <p className="mt-4 text-[11px] text-gray-400 dark:text-gray-500">
        모든 생성·다운로드는 감사로그에 기록됩니다. 패키지는 1시간 후 자동 만료됩니다.
        라이브 전송(ITI-41 Registry 제출)·교차기관 환자식별(PIX)은 멀티기관(v2.0) 도입 시 지원됩니다.
      </p>

      {toast && (
        <div className={`fixed bottom-6 right-6 rounded-lg px-4 py-2 text-sm text-white shadow-lg ${toast.type === 'ok' ? 'bg-green-600' : 'bg-red-600'}`}>
          {toast.msg}
        </div>
      )}
    </div>
  );
}

function InfoCard({ icon, title, children }: { icon: string; title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800">
      <div className="mb-1 text-lg">{icon}</div>
      <div className="mb-1 text-sm font-semibold text-gray-900 dark:text-gray-100">{title}</div>
      <p className="text-[12px] leading-relaxed text-gray-600 dark:text-gray-400">{children}</p>
    </div>
  );
}
