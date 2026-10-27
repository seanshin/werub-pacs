'use client';

/**
 * AI Inference Job Monitoring Page (Phase 5 Day 5)
 *
 * Features:
 * - Real-time job queue with live status
 * - Filter by status, model, date range
 * - Live progress indicators (step/total)
 * - Cancel running jobs
 * - Download results (SEG/SR DICOM)
 * - Pagination with 20 items per page
 */

import { useState, useEffect } from 'react';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useInferenceProgress } from '@/hooks/useInferenceProgress';


interface InferenceJob {
  id: string;
  model_id: string;
  study_instance_uid: string;
  series_instance_uid?: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  celery_task_id: string;
  error_message?: string;
  inference_time_ms?: number;
  confidence_score?: number;
  created_at: string;
  updated_at: string;
  created_by: string;
}

export default function InferencesPage() {
  const [jobs, setJobs] = useState<InferenceJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const { progress, isConnected } = useInferenceProgress(selectedJobId);

  const pageSize = 20;

  // Fetch jobs on mount and when filters change
  useEffect(() => {
    fetchJobs();
  }, [statusFilter, page]);

  const fetchJobs = async () => {
    try {
      setLoading(true);
      setError(null);

      const params = new URLSearchParams();
      if (statusFilter) params.append('status', statusFilter);
      params.append('page', String(page));
      params.append('page_size', String(pageSize));

      const response = await fetch(`/pacs-api/api/v1/ai/inferences?${params}`, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('pacs_token')}`,
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch jobs: ${response.statusText}`);
      }

      const data = await response.json();
      setJobs(data.results || []);
      setTotal(data.total || 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const handleCancelJob = async (jobId: string) => {
    if (!confirm('Cancel this job?')) return;

    try {
      const response = await fetch(`/pacs-api/api/v1/ai/inferences/${jobId}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('pacs_token')}`,
        },
      });

      if (!response.ok) {
        throw new Error('Failed to cancel job');
      }

      await fetchJobs();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const handleDownloadResult = async (jobId: string, resultType: 'seg' | 'sr') => {
    try {
      const response = await fetch(`/pacs-api/api/v1/ai/results/${jobId}?result_type=${resultType}`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('pacs_token')}`,
        },
      });

      if (!response.ok) {
        throw new Error('Failed to download result');
      }

      // Create blob and download
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `result_${resultType}.dcm`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const getStatusBadgeColor = (status: string) => {
    switch (status) {
      case 'queued':
        return 'bg-blue-100 text-blue-800';
      case 'running':
        return 'bg-yellow-100 text-yellow-800';
      case 'completed':
        return 'bg-green-100 text-green-800';
      case 'failed':
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Inference Jobs</h1>
        <p className="text-gray-600">Monitor AI model inference in real-time</p>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Active Jobs ({total})</CardTitle>
          <CardDescription>
            Real-time job queue with WebSocket progress streaming
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Filters */}
          <div className="flex gap-4">
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-40">
                <SelectValue placeholder="Filter by status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">All Statuses</SelectItem>
                <SelectItem value="queued">Queued</SelectItem>
                <SelectItem value="running">Running</SelectItem>
                <SelectItem value="completed">Completed</SelectItem>
                <SelectItem value="failed">Failed</SelectItem>
              </SelectContent>
            </Select>

            <Button variant="outline" onClick={() => fetchJobs()}>
              Refresh
            </Button>
          </div>

          {/* Jobs Table */}
          {loading ? (
            <div className="flex items-center justify-center py-8">
              ⏳
            </div>
          ) : jobs.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              No inference jobs found
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Job ID</TableHead>
                      <TableHead>Study UID</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Progress</TableHead>
                      <TableHead>Time (ms)</TableHead>
                      <TableHead>Confidence</TableHead>
                      <TableHead>Created</TableHead>
                      <TableHead>Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {jobs.map((job) => (
                      <TableRow
                        key={job.id}
                        className={
                          selectedJobId === job.id ? 'bg-blue-50' : ''
                        }
                      >
                        <TableCell className="font-mono text-sm">
                          {job.id.substring(0, 8)}...
                        </TableCell>
                        <TableCell className="font-mono text-sm">
                          {job.study_instance_uid.substring(0, 12)}...
                        </TableCell>
                        <TableCell>
                          <Badge className={getStatusBadgeColor(job.status)}>
                            {job.status}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {selectedJobId === job.id && progress ? (
                            <div className="text-xs">
                              <div className="font-medium">
                                Step {progress.step}/{progress.totalSteps}
                              </div>
                              <div className="bg-gray-200 h-2 rounded mt-1">
                                <div
                                  className="bg-blue-500 h-2 rounded transition-all"
                                  style={{
                                    width: `${
                                      ((progress.step || 0) / (progress.totalSteps || 12)) * 100
                                    }%`,
                                  }}
                                />
                              </div>
                            </div>
                          ) : job.status === 'running' ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setSelectedJobId(job.id)}
                            >
                              👁️
                              Track
                            </Button>
                          ) : (
                            '-'
                          )}
                        </TableCell>
                        <TableCell>
                          {job.inference_time_ms
                            ? `${job.inference_time_ms}ms`
                            : '-'}
                        </TableCell>
                        <TableCell>
                          {job.confidence_score
                            ? `${(job.confidence_score * 100).toFixed(1)}%`
                            : '-'}
                        </TableCell>
                        <TableCell className="text-sm text-gray-600">
                          {new Date(job.created_at).toLocaleString()}
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-1">
                            {job.status === 'running' && (
                              <Button
                                variant="destructive"
                                size="sm"
                                onClick={() => handleCancelJob(job.id)}
                              >
                                ✕
                              </Button>
                            )}
                            {job.status === 'completed' && (
                              <>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() =>
                                    handleDownloadResult(job.id, 'seg')
                                  }
                                  title="Download SEG"
                                >
                                  📥
                                </Button>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() =>
                                    handleDownloadResult(job.id, 'sr')
                                  }
                                  title="Download SR"
                                >
                                  📥
                                </Button>
                              </>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {/* Pagination */}
              <div className="flex justify-between items-center mt-4">
                <div className="text-sm text-gray-600">
                  Showing {(page - 1) * pageSize + 1}-
                  {Math.min(page * pageSize, total)} of {total}
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page === 1}
                  >
                    Previous
                  </Button>
                  <div className="px-3 py-2 text-sm">
                    Page {page} of {totalPages}
                  </div>
                  <Button
                    variant="outline"
                    onClick={() =>
                      setPage((p) => Math.min(totalPages, p + 1))
                    }
                    disabled={page === totalPages}
                  >
                    Next
                  </Button>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
