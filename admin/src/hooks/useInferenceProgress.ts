/**
 * WebSocket hook for real-time AI inference job progress tracking.
 *
 * Usage:
 *   const { status, step, confidence, error } = useInferenceProgress(jobId);
 *
 * Features:
 * - Auto-connects to /api/v1/ws/ai/{jobId}
 * - Auto-reconnects on disconnect
 * - Parses progress messages and updates state
 * - Handles connection errors gracefully
 */

import { useEffect, useState, useCallback, useRef } from 'react';

export interface InferenceProgress {
  jobId: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  step?: number;
  totalSteps?: number;
  inferenceTimeMs?: number;
  confidenceScore?: number;
  errorMessage?: string;
  timestamp: string;
}

interface UseInferenceProgressOptions {
  onUpdate?: (progress: InferenceProgress) => void;
  onComplete?: (progress: InferenceProgress) => void;
  onError?: (error: Error) => void;
  autoReconnect?: boolean;
  maxReconnectAttempts?: number;
}

export function useInferenceProgress(
  jobId: string | null,
  options: UseInferenceProgressOptions = {}
) {
  const {
    onUpdate,
    onComplete,
    onError,
    autoReconnect = true,
    maxReconnectAttempts = 5,
  } = options;

  const [progress, setProgress] = useState<InferenceProgress | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionError, setConnectionError] = useState<Error | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectCountRef = useRef(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  // Set before we deliberately close on a terminal job state so onclose does
  // not auto-reconnect to an already-finished job.
  const closedIntentionallyRef = useRef(false);

  // Connect to WebSocket
  const connect = useCallback(() => {
    if (!jobId) return;
    closedIntentionallyRef.current = false;

    try {
      // Build WebSocket URL
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host;
      const wsUrl = `${protocol}//${host}/pacs-api/api/v1/ws/ai/${jobId}`;

      // Get JWT token from localStorage for authentication (admin 앱 공통 키는 pacs_token)
      const token = localStorage.getItem('pacs_token');
      const urlWithAuth = token ? `${wsUrl}?token=${encodeURIComponent(token)}` : wsUrl;

      const ws = new WebSocket(urlWithAuth);

      ws.onopen = () => {
        console.log(`✅ WebSocket connected for job ${jobId}`);
        setIsConnected(true);
        setConnectionError(null);
        reconnectCountRef.current = 0;
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          console.log(`📬 Progress update:`, data);

          // Handle initial state
          if (data.type === 'initial_state') {
            const progressData: InferenceProgress = {
              jobId: data.job_id,
              status: data.status,
              step: data.step,
              totalSteps: 12,
              inferenceTimeMs: data.inference_time_ms,
              confidenceScore: data.confidence_score,
              errorMessage: data.error_message,
              timestamp: data.timestamp || new Date().toISOString(),
            };
            setProgress(progressData);
            onUpdate?.(progressData);
            return;
          }

          // Handle status updates
          if (data.type === 'status_update') {
            const progressData: InferenceProgress = {
              jobId: data.job_id,
              status: data.status,
              step: data.step || progress?.step,
              totalSteps: data.total_steps || 12,
              inferenceTimeMs: data.inference_time_ms || progress?.inferenceTimeMs,
              confidenceScore: data.confidence_score || progress?.confidenceScore,
              errorMessage: data.error_message,
              timestamp: data.timestamp || new Date().toISOString(),
            };
            setProgress(progressData);
            onUpdate?.(progressData);

            // Call completion callback if job is done
            if (data.status === 'completed') {
              onComplete?.(progressData);
              closedIntentionallyRef.current = true;
              ws.close();
              setIsConnected(false);
            }

            // Call error callback if job failed
            if (data.status === 'failed') {
              const error = new Error(data.error_message || 'Inference job failed');
              onError?.(error);
              setConnectionError(error);
              closedIntentionallyRef.current = true;
              ws.close();
              setIsConnected(false);
            }
          }

          // Handle errors
          if (data.type === 'error') {
            const error = new Error(data.message || 'WebSocket error');
            setConnectionError(error);
            onError?.(error);
            closedIntentionallyRef.current = true;
            ws.close();
            setIsConnected(false);
          }
        } catch (parseError) {
          console.error('Failed to parse WebSocket message:', parseError);
        }
      };

      ws.onerror = (event) => {
        console.error('❌ WebSocket error:', event);
        const error = new Error('WebSocket connection error');
        setConnectionError(error);
        onError?.(error);
        setIsConnected(false);
      };

      ws.onclose = () => {
        console.log(`🔌 WebSocket closed for job ${jobId}`);
        setIsConnected(false);

        // Deliberate close on a terminal job state — do not reconnect.
        if (closedIntentionallyRef.current) {
          return;
        }

        // Auto-reconnect logic
        if (autoReconnect && reconnectCountRef.current < maxReconnectAttempts) {
          reconnectCountRef.current += 1;
          const delay = Math.min(1000 * Math.pow(2, reconnectCountRef.current - 1), 10000); // Exponential backoff
          console.log(`🔄 Reconnecting in ${delay}ms... (attempt ${reconnectCountRef.current}/${maxReconnectAttempts})`);

          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, delay);
        } else if (reconnectCountRef.current >= maxReconnectAttempts) {
          const error = new Error(`Failed to connect after ${maxReconnectAttempts} attempts`);
          setConnectionError(error);
          onError?.(error);
        }
      };

      wsRef.current = ws;
    } catch (error) {
      const err = error instanceof Error ? error : new Error('Unknown connection error');
      setConnectionError(err);
      onError?.(err);
    }
  }, [jobId, onUpdate, onComplete, onError, autoReconnect, maxReconnectAttempts]);

  // Connect on mount, disconnect on unmount
  useEffect(() => {
    connect();

    return () => {
      // Clear reconnect timeout
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }

      // Close WebSocket
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  // Disconnect function
  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }
    if (wsRef.current) {
      wsRef.current.close();
    }
    setIsConnected(false);
  }, []);

  // Reconnect function
  const reconnect = useCallback(() => {
    reconnectCountRef.current = 0;
    disconnect();
    setTimeout(() => connect(), 500);
  }, [connect, disconnect]);

  return {
    progress,
    isConnected,
    connectionError,
    disconnect,
    reconnect,
  };
}
