'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import {
  Users, Building2, Timer, ScrollText, ScanSearch, SlidersHorizontal, Sparkles,
  EyeOff, Archive, Cpu, Workflow, Activity, Network, Link2, Globe, Upload,
  CheckSquare, ClipboardList, ShieldAlert,
} from 'lucide-react';

type Item = { href: string; icon: LucideIcon; label: string; desc: string };
const SECTIONS: { title: string; items: Item[] }[] = [
  {
    title: '시스템 · 사용자',
    items: [
      { href: '/users', icon: Users, label: '사용자 관리', desc: '계정 생성·삭제, 역할(RBAC) 부여' },
      { href: '/tenants', icon: Building2, label: '테넌트', desc: '다기관 테넌트·소속 사용자 설정' },
      { href: '/sla', icon: Timer, label: 'SLA 설정', desc: '판독 SLA 임계값·자동 에스컬레이션' },
      { href: '/audit', icon: ScrollText, label: '감사 로그', desc: '전 작업 감사 추적·조회' },
    ],
  },
  {
    title: 'DICOM · 영상 처리',
    items: [
      { href: '/dicom-issues', icon: ScanSearch, label: 'DICOM 이슈 컨트롤', desc: '검증 규칙·자동수정·격리/롤백' },
      { href: '/dicom-issues/settings', icon: SlidersHorizontal, label: 'DICOM 이슈 설정', desc: '규칙·모달리티 렌더링·에러 메시지 편집' },
      { href: '/normalization', icon: Sparkles, label: '정규화 설정', desc: '비표준 영상 밀도/태그 정규화' },
      { href: '/anonymize', icon: EyeOff, label: '익명화', desc: 'PS3.15 Basic Confidentiality 비식별' },
      { href: '/archive', icon: Archive, label: '아카이브', desc: 'IOCM 보존 정책·복원' },
    ],
  },
  {
    title: 'AI',
    items: [
      { href: '/ai/models', icon: Cpu, label: 'AI 모델 관리', desc: '모델 등록·활성화·임상/연구 분류' },
      { href: '/ai/orchestration', icon: Workflow, label: 'AI 파이프라인', desc: '오케스트레이션·버전·롤백' },
      { href: '/ai/inferences', icon: Activity, label: 'AI 추론 이력', desc: '추론 작업·결과·거버넌스' },
    ],
  },
  {
    title: '연동',
    items: [
      { href: '/remotes', icon: Network, label: '외부 PACS 연동', desc: 'DICOM 노드 Echo/Query/Retrieve/Send' },
      { href: '/his', icon: Link2, label: 'HIS 연동', desc: '오더 동기화·환자 매핑·병합 재조정' },
      { href: '/xds-export', icon: Globe, label: '기관 간 교환', desc: 'IHE XDS-I/XDM 표준 패키지 생성' },
    ],
  },
  {
    title: '수집 · 규제',
    items: [
      { href: '/upload', icon: Upload, label: '영상 업로드', desc: '관리자 직접 업로드' },
      { href: '/upload-queue', icon: CheckSquare, label: '승인 큐', desc: '환자/외부 업로드 승인·반려' },
      { href: '/irb', icon: ClipboardList, label: 'IRB 레지스트리', desc: '연구 IRB 승인 관리' },
    ],
  },
];

export default function SettingsPage() {
  const [role, setRole] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
    setRole(localStorage.getItem('pacs_role'));
  }, []);

  if (mounted && role !== 'admin') {
    return (
      <div className="mx-auto max-w-md px-4 py-20 text-center">
        <ShieldAlert className="mx-auto h-10 w-10 text-amber-500" strokeWidth={1.5} />
        <h1 className="mt-3 text-lg font-bold text-gray-900 dark:text-gray-100">관리자 전용</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">설정 페이지는 관리자만 접근할 수 있습니다.</p>
        <Link href="/" className="mt-4 inline-block text-sm text-blue-600 hover:underline">← 대시보드로</Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">설정</h1>
      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">시스템 · DICOM · AI · 연동 관리자 설정을 한 곳에서</p>

      <div className="mt-6 space-y-8">
        {SECTIONS.map((sec) => (
          <section key={sec.title}>
            <h2 className="mb-3 text-sm font-bold uppercase tracking-wide text-gray-500 dark:text-gray-400">{sec.title}</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {sec.items.map((it) => {
                const Icon = it.icon;
                return (
                  <Link key={it.href} href={it.href}
                    className="group flex items-start gap-3 rounded-xl border border-gray-200 bg-white p-4 shadow-sm transition hover:border-blue-300 hover:shadow-md dark:border-gray-700 dark:bg-gray-800 dark:hover:border-blue-700">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600 transition group-hover:bg-blue-100 dark:bg-blue-900/30 dark:text-blue-300">
                      <Icon className="h-5 w-5" strokeWidth={1.75} aria-hidden />
                    </div>
                    <div className="min-w-0">
                      <div className="font-semibold text-gray-900 dark:text-gray-100">{it.label}</div>
                      <div className="mt-0.5 text-xs leading-relaxed text-gray-500 dark:text-gray-400">{it.desc}</div>
                    </div>
                  </Link>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
