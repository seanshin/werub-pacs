import type { Metadata } from 'next';
import './globals.css';
import NavBar from '@/components/NavBar';

export const metadata: Metadata = {
  title: 'WeRU.B PACS Admin',
  description: '병원 PACS 관리 포털',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="bg-gray-50 dark:bg-gray-900 min-h-screen text-gray-900 dark:text-gray-100 transition-colors">
        <NavBar />
        <main className="px-2 sm:px-3 lg:px-4 py-3 sm:py-4 [&_*]:transition-colors">
          <div className="[&_.bg-white]:dark:bg-gray-800 [&_.border]:dark:border-gray-700 [&_.text-gray-900]:dark:text-gray-100 [&_.text-gray-700]:dark:text-gray-300 [&_.text-gray-600]:dark:text-gray-400 [&_.text-gray-500]:dark:text-gray-400 [&_.text-gray-400]:dark:text-gray-500 [&_.bg-gray-50]:dark:bg-gray-800/50 [&_.bg-slate-50]:dark:bg-gray-800/50 [&_.border-gray-200]:dark:border-gray-700 [&_.border-slate-200]:dark:border-gray-700 [&_.shadow-sm]:dark:shadow-gray-900/20 [&_.hover\:bg-gray-50:hover]:dark:bg-gray-700 [&_.hover\:bg-slate-50:hover]:dark:bg-gray-700">
            {children}
          </div>
        </main>
      </body>
    </html>
  );
}
