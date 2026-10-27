'use client';

import { useEffect, useState } from 'react';

const roleLabels: Record<string, string> = {
  admin: '관리자', radiologist: '영상의학과', physician: '임상의',
  technologist: '기사', researcher: '연구자',
};

export default function UserMenu() {
  const [user, setUser] = useState<string | null>(null);
  const [role, setRole] = useState<string | null>(null);

  useEffect(() => {
    setUser(localStorage.getItem('pacs_user'));
    setRole(localStorage.getItem('pacs_role'));
  }, []);

  const handleLogout = () => {
    localStorage.removeItem('pacs_token');
    localStorage.removeItem('pacs_user');
    localStorage.removeItem('pacs_role');
    window.location.href = '/pacs-admin';
  };

  if (!user) return null;

  return (
    <>
      <span className="text-xs text-gray-500 hidden sm:inline">
        👤 {user} ({roleLabels[role || ''] || role})
      </span>
      <button onClick={handleLogout}
        className="text-xs bg-gray-100 hover:bg-red-100 text-gray-600 hover:text-red-600 px-2 py-1 rounded transition">
        로그아웃
      </button>
    </>
  );
}
