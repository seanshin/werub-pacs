'use client';

interface ReviewDecisionFormProps {
  reviewId: string;
  filename: string;           // used for aria-label
  comment: string;
  onCommentChange: (reviewId: string, value: string) => void;
  onDecision: (reviewId: string, decision: 'approve' | 'reject') => void;
  submitting: boolean;
}

export function ReviewDecisionForm({
  reviewId, filename, comment, onCommentChange, onDecision, submitting
}: ReviewDecisionFormProps) {
  return (
    <div className="flex items-center gap-2 mt-2 pl-2">
      <button
        onClick={() => onDecision(reviewId, 'approve')}
        disabled={submitting}
        aria-label={`${filename} 승인`}
        className="px-3 py-1 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        승인
      </button>
      <button
        onClick={() => onDecision(reviewId, 'reject')}
        disabled={submitting}
        aria-label={`${filename} 거부`}
        className="px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        거부
      </button>
      <input
        type="text"
        placeholder="코멘트 (선택)"
        value={comment}
        onChange={e => onCommentChange(reviewId, e.target.value)}
        disabled={submitting}
        className="flex-1 border rounded px-2 py-1 text-sm disabled:bg-gray-50"
        maxLength={500}
        aria-label="검토 코멘트"
      />
    </div>
  );
}
