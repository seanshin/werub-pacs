// admin/src/app/normalization/types.ts
// All shared TypeScript types for DICOM batch normalization feature

export type BatchStatus = 'queued' | 'processing' | 'completed' | 'failed';
export type RiskLevel = 'safe' | 'medium' | 'risky';
export type FileStatus = 'completed' | 'failed' | 'pending';

export type BatchJob = {
  batch_id: string;
  submitted_at: string;         // ISO 8601
  submitted_by: string;
  file_count: number;
  status: BatchStatus;
  success_rate: number | null;  // null when not yet terminal
};

export type BatchDetail = BatchJob & {
  normalized_count: number;
  error_count: number;
  medium_risk_pending: number;
  processing_time_ms: number | null;
};

export type BatchFile = {
  file_id: string;
  filename: string;
  status: FileStatus;
  algorithms_applied: string[];
  risk_level: RiskLevel;
  error_message: string | null;
  error_detail: string | null;  // may be long; truncate at 500 chars in UI
};

export type AlgorithmStat = {
  algorithm: string;
  files_corrected: number;
  percent_of_total: number;
  avg_ms: number;
};

export type SupplierStat = {
  supplier: string;
  file_count: number;
  avg_success_rate: number;
  most_common_correction: string;
};

export type BatchStatistics = {
  batch_id: string;
  total_files: number;
  normalized_count: number;
  error_count: number;
  success_rate: number;
  avg_processing_ms: number;
  pending_reviews: number;
  algorithm_breakdown: AlgorithmStat[];
  supplier_breakdown: SupplierStat[];
};

export type ReviewItem = {
  review_id: string;
  batch_id: string;
  filename: string;
  dicom_tag: string;          // e.g. "(0028,0004)"
  original_value: string;
  proposed_value: string;
  algorithm: string;
  risk_rationale: string;
  supplier: string | null;
  applicable?: boolean;       // 캐논 변경(승인 시 DICOM 자동 적용 대상). false면 기록만.
  schema_version?: number | null;
};

export type ProgressMessage = {
  type: 'progress';
  processed_files: number;
  total_files: number;
  status: BatchStatus;
  files_per_min: number;
  errors: number;
  medium_risk_pending: number;
};

// Paginated wrapper used by batch list, file list, and review list
export type Paginated<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
};
