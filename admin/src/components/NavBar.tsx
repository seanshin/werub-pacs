'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import UserMenu from '@/components/UserMenu';
import NotificationBell from '@/components/NotificationBell';
import DarkModeToggle from '@/components/DarkModeToggle';

// roles = 메뉴가 노출되는 역할(백엔드 RequireRole과 정합). 없으면 전체 공개.
// admin은 전체 노출, resident는 radiologist로 취급(백엔드 RBAC와 동일).
type NavItem = { href: string; label: string; roles?: string[]; external?: boolean };
const RAD = ['radiologist'];
const RAD_TECH = ['radiologist', 'technologist'];
const CLINICAL = ['radiologist', 'physician', 'technologist'];

const navLeft: NavItem[] = [
  { href: '/', label: '대시보드' },
  { href: '/my-patients', label: '내 환자', roles: ['physician', 'radiologist'] }, // 백엔드 ADMIN/PHYSICIAN/RAD
  { href: '/reading', label: '판독', roles: RAD },
  { href: '/assignments', label: '배정', roles: RAD_TECH },
  { href: '/worklist', label: '워크리스트', roles: ['technologist'] },
  { href: '/templates', label: '템플릿', roles: RAD },
  { href: '/audit', label: '감사로그', roles: [] },           // admin 전용
  { href: '/technologist', label: '방사선사', roles: ['technologist'] },
  { href: '/emergency', label: '응급', roles: CLINICAL },
  { href: '/consults', label: '협진', roles: ['radiologist'] },              // 백엔드 conferences=ADMIN/RAD
  { href: '/retake', label: '재촬영', roles: ['radiologist', 'physician'] }, // 백엔드 retake=ADMIN/RAD/PHYSICIAN
];

const navRight: NavItem[] = [
  { href: '/bi', label: '경영BI', roles: RAD },               // 백엔드 bi=ADMIN/RAD
  { href: '/settings', label: '설정', roles: [] },            // admin 전용 — 통합 설정 허브
  { href: '/users', label: '사용자', roles: [] },             // admin 전용
  { href: '/ai', label: 'AI', roles: [] },                    // admin 전용
  { href: '/upload', label: '업로드', roles: ['technologist'] },
  { href: '/upload-queue', label: '승인큐', roles: [] },      // admin 전용
  { href: '/patient-links', label: '열람링크', roles: [] },   // admin 전용 — 환자 결과 열람 토큰 발급 (백엔드 patient-view=ADMIN)
  { href: '/reception', label: '수신모니터', roles: RAD_TECH },
  { href: '/remotes', label: '외부연동', roles: [] },         // admin 전용
  { href: '/xds-export', label: '기관간교환', roles: RAD },
  { href: '/normalization', label: '정규화', roles: ['technologist'] },
  { href: '/dicom-issues', label: 'DICOM이슈', roles: [] },   // admin 전용
  { href: '/sla', label: 'SLA', roles: RAD },
  { href: '/archive', label: '아카이브', roles: RAD_TECH },
  { href: '/anonymize', label: '익명화', roles: ['researcher'] },
  { href: '/irb', label: 'IRB', roles: ['researcher'] },
  { href: '/teaching', label: '📚 티칭파일', roles: RAD },   // 백엔드 teaching=ADMIN/RAD/RESIDENT(승격)
  { href: '/pacs-admin/manual.html', label: '📖 매뉴얼', external: true }, // 정적 HTML 사용 설명서 (전체 공개)
  { href: '/about', label: '소개' },
];

export default function NavBar() {
  const [reviewCount, setReviewCount] = useState(0);
  const [role, setRole] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    setRole(localStorage.getItem('pacs_role'));
    const readReviewCount = () => {
      const count = localStorage.getItem('pacs_review_count');
      setReviewCount(Number(count || 0));
    };
    readReviewCount();
    const id = setInterval(readReviewCount, 60_000);
    return () => clearInterval(id);
  }, []);

  // admin sees everything; resident inherits radiologist (matches backend RBAC).
  // no `roles` = public; `roles: []` = admin-only.
  const effRole = role === 'resident' ? 'radiologist' : role;
  const visible = (item: NavItem) =>
    !item.roles || role === 'admin' || (!!effRole && item.roles.includes(effRole));
  // Before mount we don't know the role — show only public items (never leak admin menus).
  const leftItems = mounted ? navLeft.filter(visible) : navLeft.filter((i) => !i.roles);
  const rightItems = mounted ? navRight.filter(visible) : navRight.filter((i) => !i.roles);

  return (
    <nav className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 shadow-sm">
      <div className="mx-auto px-3 py-2">
        <div className="flex items-center justify-between">
          <Link href="/" className="text-lg font-bold text-primary shrink-0">WeRU.B PACS</Link>
          <div className="flex items-center gap-1.5">
            <a href="/werub-viewer/" target="_blank" className="text-[11px] bg-blue-600 text-white px-2 py-0.5 rounded hover:bg-blue-700">WeRU.B ↗</a>
            <a href="/pacs-api/docs" target="_blank" className="hidden sm:inline text-[11px] text-gray-500 dark:text-gray-400 hover:text-primary">API ↗</a>
            <DarkModeToggle />
            <NotificationBell />
            <UserMenu />
          </div>
        </div>
        <div className="flex items-center mt-1.5 overflow-x-auto pb-0.5 -mb-0.5 scrollbar-hide">
          <div className="flex items-center">
            {leftItems.map(nav => (
              <Link key={nav.href} href={nav.href}
                className="text-[11px] text-gray-600 dark:text-gray-400 hover:text-primary whitespace-nowrap px-1.5 py-0.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 transition relative">
                {nav.label}
              </Link>
            ))}
          </div>
          <div className="flex-1" />
          {rightItems.length > 0 && <div className="flex-shrink-0 w-px h-4 bg-gray-200 dark:bg-gray-600 mx-1.5" />}
          <div className="flex items-center">
            {rightItems.map(nav => (
              nav.external ? (
                <a key={nav.href} href={nav.href} target="_blank" rel="noopener noreferrer"
                  className="text-[11px] text-gray-500 dark:text-gray-400 hover:text-primary whitespace-nowrap px-1.5 py-0.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 transition relative">
                  {nav.label}
                </a>
              ) : (
                <Link key={nav.href} href={nav.href}
                  className="text-[11px] text-gray-500 dark:text-gray-400 hover:text-primary whitespace-nowrap px-1.5 py-0.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 transition relative">
                  {nav.label}
                  {nav.label === '정규화' && reviewCount > 0 && (
                    <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[8px] font-bold rounded-full w-4 h-4 flex items-center justify-center">
                      {reviewCount > 99 ? '99+' : reviewCount}
                    </span>
                  )}
                </Link>
              )
            ))}
          </div>
        </div>
      </div>
    </nav>
  );
}
