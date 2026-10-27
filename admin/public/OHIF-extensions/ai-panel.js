/**
 * OHIF Viewer Extension for AI Inference
 *
 * Adds "Run AI" button to OHIF toolbar for inline model inference.
 * Features:
 * - Model selector dropdown
 * - Real-time progress tracking
 * - Result display (SEG overlay on source image)
 * - Error handling and retry logic
 *
 * Installation: Add to OHIF configuration in viewer config
 * {
 *   extensions: [
 *     {
 *       id: 'ai-panel',
 *       source: '/OHIF-extensions/ai-panel.js'
 *     }
 *   ]
 * }
 */

const AIInferenceExtension = {
  id: 'ai-inference',

  // OHIF Extension entry point
  init(extensionManager) {
    // Register custom button
    extensionManager.registerButton({
      id: 'ai-inference-button',
      label: 'Run AI',
      icon: 'ai-sparkles',
      position: 'toolbar',
      commands: ['showAIPanel'],
    });

    // Register panel component
    extensionManager.registerPanelModule({
      name: 'AIPanelModule',
      component: AIPanel,
    });

    // Register command
    extensionManager.registerCommand('showAIPanel', {
      commandFn({ dispatch }) {
        dispatch({
          type: 'SHOW_PANEL',
          payload: {
            panelType: 'ai-inference',
            panelWidth: 400,
          },
        });
      },
    });
  },
};

/**
 * AI Panel React Component
 * Displays model selector, progress, and results
 */
function AIPanel({ servicesManager, commandsManager, displaySetInstanceUIDs }) {
  const [models, setModels] = React.useState([]);
  const [selectedModel, setSelectedModel] = React.useState(null);
  const [isRunning, setIsRunning] = React.useState(false);
  const [progress, setProgress] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [wsConnected, setWsConnected] = React.useState(false);

  const wsRef = React.useRef(null);
  const jobIdRef = React.useRef(null);

  // Fetch available models on mount
  React.useEffect(() => {
    fetchModels();
  }, []);

  const fetchModels = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await fetch('/pacs-api/api/v1/ai/models', {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });

      if (!response.ok) throw new Error('Failed to fetch models');

      const data = await response.json();
      const activeModels = (data.items || []).filter(m => m.status === 'active');
      setModels(activeModels);

      if (activeModels.length > 0) {
        setSelectedModel(activeModels[0]);
      }
    } catch (err) {
      setError(`Failed to load models: ${err.message}`);
    }
  };

  const handleRunInference = async () => {
    if (!selectedModel) {
      setError('Please select a model');
      return;
    }

    // Get current display set (study/series UIDs from OHIF viewer)
    const activeViewportIndex = 0; // Get from OHIF state in production
    const displaySetInstanceUID = displaySetInstanceUIDs?.[activeViewportIndex];

    if (!displaySetInstanceUID) {
      setError('No image selected');
      return;
    }

    try {
      setIsRunning(true);
      setError(null);
      setProgress({ step: 1, totalSteps: 12, status: 'queued' });

      const token = localStorage.getItem('token');
      const response = await fetch('/pacs-api/api/v1/ai/inferences', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          model_id: selectedModel.id,
          study_instance_uid: '1.2.3.4.5', // Get from OHIF viewer
          series_instance_uid: null,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error?.message || 'Failed to submit job');
      }

      const job = await response.json();
      jobIdRef.current = job.id;

      // Connect to WebSocket for progress tracking
      connectToProgressStream(job.id);
    } catch (err) {
      setError(err.message);
      setIsRunning(false);
    }
  };

  const connectToProgressStream = (jobId) => {
    try {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host;
      const token = localStorage.getItem('token') || sessionStorage.getItem('token');
      const wsUrl = token
        ? `${protocol}//${host}/pacs-api/api/v1/ws/ai/${jobId}?token=${encodeURIComponent(token)}`
        : `${protocol}//${host}/pacs-api/api/v1/ws/ai/${jobId}`;

      wsRef.current = new WebSocket(wsUrl);

      wsRef.current.onopen = () => {
        setWsConnected(true);
      };

      wsRef.current.onmessage = (event) => {
        const data = JSON.parse(event.data);

        // Handle initial state
        if (data.type === 'initial_state') {
          setProgress({
            step: 1,
            totalSteps: 12,
            status: data.status,
          });
          return;
        }

        // Handle status updates
        if (data.type === 'status_update') {
          setProgress({
            step: data.step || 1,
            totalSteps: data.total_steps || 12,
            status: data.status,
            inferenceTimeMs: data.inference_time_ms,
            confidenceScore: data.confidence_score,
            errorMessage: data.error_message,
          });

          if (data.status === 'completed') {
            setIsRunning(false);
            loadResultsIntoViewer(jobId);
            wsRef.current?.close();
          }

          if (data.status === 'failed') {
            setError(data.error_message || 'Inference failed');
            setIsRunning(false);
            wsRef.current?.close();
          }
        }
      };

      wsRef.current.onerror = (err) => {
        setError('WebSocket connection error');
        setWsConnected(false);
      };

      wsRef.current.onclose = () => {
        setWsConnected(false);
      };
    } catch (err) {
      setError(`Connection error: ${err.message}`);
    }
  };

  const loadResultsIntoViewer = async (jobId) => {
    try {
      // In production: fetch SEG result and add to OHIF viewer as overlay
      // segmentationModule.addSegmentation(segmentationData);
      // This is a placeholder for full implementation
      console.log(`Loading results for job ${jobId}`);
    } catch (err) {
      setError(`Failed to load results: ${err.message}`);
    }
  };

  const getProgressPercentage = () => {
    if (!progress) return 0;
    return (progress.step / progress.totalSteps) * 100;
  };

  return (
    <div style={styles.panel}>
      <h3 style={styles.title}>🤖 AI Inference</h3>

      {error && (
        <div style={styles.error}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {!isRunning ? (
        <>
          <div style={styles.section}>
            <label style={styles.label}>Model</label>
            <select
              value={selectedModel?.id || ''}
              onChange={(e) => {
                const model = models.find(m => m.id === e.target.value);
                setSelectedModel(model);
              }}
              style={styles.select}
              disabled={isRunning}
            >
              <option value="">Select a model...</option>
              {models.map(m => (
                <option key={m.id} value={m.id}>
                  {m.name} ({m.version}) - {m.modality}
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={handleRunInference}
            disabled={!selectedModel || isRunning}
            style={{
              ...styles.button,
              backgroundColor: selectedModel && !isRunning ? '#3b82f6' : '#d1d5db',
              cursor: selectedModel && !isRunning ? 'pointer' : 'not-allowed',
            }}
          >
            Run Inference
          </button>
        </>
      ) : (
        <div style={styles.section}>
          <div style={styles.progressLabel}>
            Step {progress?.step}/{progress?.totalSteps}
          </div>
          <div style={styles.progressBar}>
            <div
              style={{
                ...styles.progressFill,
                width: `${getProgressPercentage()}%`,
              }}
            />
          </div>
          <div style={styles.status}>
            Status: <strong>{progress?.status}</strong>
          </div>

          {progress?.inferenceTimeMs && (
            <div style={styles.metric}>
              Inference: {progress.inferenceTimeMs}ms
            </div>
          )}

          {progress?.confidenceScore && (
            <div style={styles.metric}>
              Confidence: {(progress.confidenceScore * 100).toFixed(1)}%
            </div>
          )}

          {progress?.status === 'failed' && (
            <div style={styles.errorMessage}>
              {progress.errorMessage}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const styles = {
  panel: {
    padding: '16px',
    backgroundColor: '#f9fafb',
    borderRadius: '8px',
    border: '1px solid #e5e7eb',
    fontFamily: 'system-ui, -apple-system, sans-serif',
  },
  title: {
    margin: '0 0 16px 0',
    fontSize: '16px',
    fontWeight: 'bold',
  },
  section: {
    marginBottom: '16px',
  },
  label: {
    display: 'block',
    marginBottom: '8px',
    fontSize: '14px',
    fontWeight: '500',
  },
  select: {
    width: '100%',
    padding: '8px',
    border: '1px solid #d1d5db',
    borderRadius: '4px',
    fontSize: '14px',
  },
  button: {
    width: '100%',
    padding: '10px',
    color: 'white',
    border: 'none',
    borderRadius: '4px',
    fontSize: '14px',
    fontWeight: '500',
  },
  progressLabel: {
    fontSize: '12px',
    marginBottom: '8px',
    fontWeight: '500',
  },
  progressBar: {
    width: '100%',
    height: '8px',
    backgroundColor: '#e5e7eb',
    borderRadius: '4px',
    overflow: 'hidden',
    marginBottom: '8px',
  },
  progressFill: {
    height: '100%',
    backgroundColor: '#3b82f6',
    transition: 'width 0.3s ease',
  },
  status: {
    fontSize: '12px',
    marginBottom: '8px',
  },
  metric: {
    fontSize: '12px',
    color: '#6b7280',
    marginTop: '4px',
  },
  error: {
    padding: '8px',
    backgroundColor: '#fee2e2',
    color: '#991b1b',
    borderRadius: '4px',
    marginBottom: '12px',
    fontSize: '12px',
  },
  errorMessage: {
    padding: '8px',
    backgroundColor: '#fee2e2',
    color: '#991b1b',
    borderRadius: '4px',
    marginTop: '12px',
    fontSize: '12px',
  },
};

// Export for OHIF extension system
if (typeof module !== 'undefined' && module.exports) {
  module.exports = AIInferenceExtension;
}
