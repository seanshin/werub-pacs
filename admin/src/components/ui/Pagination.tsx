'use client';

interface PaginationProps {
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}

export default function Pagination({ page, totalPages, total, pageSize, onPageChange }: PaginationProps) {
  if (total <= 0) return null;

  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);

  return (
    <div className="flex items-center justify-between mt-4 text-sm">
      <div className="text-gray-600 dark:text-gray-400">
        총 {total.toLocaleString()}건 중 {start.toLocaleString()}-{end.toLocaleString()}건 표시
      </div>
      <div className="flex gap-1">
        <button
          onClick={() => onPageChange(1)}
          disabled={page === 1}
          className="px-2 py-1 border rounded disabled:opacity-50 hover:bg-gray-50 dark:hover:bg-gray-700 text-xs dark:border-gray-600"
        >
          처음
        </button>
        <button
          onClick={() => onPageChange(Math.max(1, page - 1))}
          disabled={page === 1}
          className="px-3 py-1 border rounded disabled:opacity-50 hover:bg-gray-50 dark:hover:bg-gray-700 dark:border-gray-600"
        >
          이전
        </button>
        <span className="px-3 py-1 text-gray-600 dark:text-gray-400">{page} / {totalPages}</span>
        <button
          onClick={() => onPageChange(Math.min(totalPages, page + 1))}
          disabled={page >= totalPages}
          className="px-3 py-1 border rounded disabled:opacity-50 hover:bg-gray-50 dark:hover:bg-gray-700 dark:border-gray-600"
        >
          다음
        </button>
        <button
          onClick={() => onPageChange(totalPages)}
          disabled={page >= totalPages}
          className="px-2 py-1 border rounded disabled:opacity-50 hover:bg-gray-50 dark:hover:bg-gray-700 text-xs dark:border-gray-600"
        >
          마지막
        </button>
      </div>
    </div>
  );
}
