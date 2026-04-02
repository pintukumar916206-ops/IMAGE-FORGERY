import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { uploadImage, getProgress, getReport, authenticate } from './services/api';
import Result from './components/Result';

function App() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [taskId, setTaskId] = useState(null);
  const [progress, setProgress] = useState(0);
  const [status, setStatus] = useState('idle');
  const [stage, setStage] = useState('');
  const [report, setReport] = useState(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    authenticate().catch(err => console.error('Auth initialization failed:', err));
  }, []);

  const handleFile = (selectedFile) => {
    if (selectedFile && selectedFile.type.startsWith('image/')) {
      if (preview) {
        URL.revokeObjectURL(preview);
      }
      setFile(selectedFile);
      setPreview(URL.createObjectURL(selectedFile));
      setTaskId(null);
      setReport(null);
      setStatus('ready');
    }
  };

  const startAnalysis = async () => {
    if (!file) return;
    setStatus('uploading');
    setStage('Uploading to analysis engine...');

    try {
      const result = await uploadImage(file);
      setTaskId(result.task_id);
      setStatus('processing');
      setProgress(5);
      setStage('Initializing forensic pipeline...');
    } catch (err) {
      setStatus('error');
      setStage(err.response?.data?.detail || 'Upload failed');
    }
  };

  useEffect(() => {
    let interval;
    if (status === 'processing' && taskId) {
      interval = setInterval(async () => {
        try {
          const result = await getProgress(taskId);
          const data = result.data;
          setProgress(data.progress || 10);
          setStage(data.stage || 'Analyzing...');

          if (data.status === 'complete') {
            try {
              const reportResult = await getReport(taskId);
              setReport(reportResult.data);
              setStatus('done');
              clearInterval(interval);
            } catch (err) {
              setStage('Failed to fetch report');
              setStatus('error');
              clearInterval(interval);
            }
          } else if (data.status === 'error') {
            setStatus('error');
            setStage(data.stage || 'Analysis failed');
            clearInterval(interval);
          }
        } catch (err) {
          setStatus('error');
          setStage('Failed to fetch progress');
          clearInterval(interval);
        }
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [status, taskId]);

  useEffect(() => {
    return () => {
      if (preview) {
        URL.revokeObjectURL(preview);
      }
    };
  }, [preview]);

  return (
    <div className="app-container">
      <div className="ambient-orb"></div>

      <motion.nav
        initial={{ y: -30, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        className="glass-panel main-nav"
      >
        <div className="brand">
          <h1>Image Authentication</h1>
        </div>
      </motion.nav>

      <div className="container">
        <AnimatePresence mode="wait">
          {status === 'done' ? (
            <Result key="results" report={report} preview={preview} onReset={() => setStatus('idle')} />
          ) : status === 'error' ? (
            <motion.div
              key="error"
              initial={{ opacity: 0, y: 30 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="glass-panel upload-card"
              style={{ background: 'linear-gradient(135deg, rgba(220, 38, 38, 0.1) 0%, rgba(220, 38, 38, 0.05) 100%)', borderColor: 'var(--red-status)' }}
            >
              <div style={{ textAlign: 'center', padding: '2rem' }}>
                <div style={{ color: 'var(--red-status)', fontSize: '3.5rem', marginBottom: '1.5rem' }}>
                  <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
                  </svg>
                </div>
                <p style={{ fontWeight: 600, color: 'var(--red-status)', marginBottom: '0.5rem' }}>Analysis Failed</p>
                <span className="tiny-label" style={{ color: '#666' }}>{stage}</span>
              </div>
              <div className="upload-actions">
                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => setStatus('idle')}
                  className="btn-primary"
                  style={{ background: 'var(--red-status)' }}
                >
                  Try Again
                </motion.button>
              </div>
            </motion.div>
          ) : (
            <motion.div
              key="uploader"
              initial={{ opacity: 0, y: 30 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="glass-panel upload-card"
            >
              <div
                className={`drop-zone ${status === 'ready' ? 'breathing' : ''}`}
                onClick={() => fileInputRef.current.click()}
              >
                {preview ? (
                  <motion.img
                    initial={{ scale: 0.8 }}
                    animate={{ scale: 1 }}
                    src={preview}
                    alt="Preview"
                    className="upload-preview"
                  />
                ) : (
                  <div style={{ textAlign: 'center', opacity: 0.6 }}>
                    <div style={{ color: 'var(--accent-main)', fontSize: '3.5rem', marginBottom: '1.5rem' }}>
                      <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" />
                      </svg>
                    </div>
                    <p style={{ fontWeight: 600 }}>Upload image for authentication</p>
                    <span className="tiny-label" style={{ marginTop: '0.5rem' }}>JPEG, PNG, or WebP (max 50MB)</span>
                  </div>
                )}
                <input
                  type="file"
                  className="hidden"
                  ref={fileInputRef}
                  onChange={(e) => handleFile(e.target.files[0])}
                  accept="image/*"
                />
              </div>

              <div className="upload-actions">
                {status === 'idle' || status === 'ready' ? (
                  <motion.button
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    onClick={startAnalysis}
                    disabled={!file}
                    className="btn-primary"
                  >
                    Authenticate Image
                  </motion.button>
                ) : (
                  <div className="medical-loader">
                    <span className="tiny-label" style={{ color: 'var(--accent-main)', fontWeight: 800 }}>
                      {stage}
                    </span>
                    <div className="progress-track">
                      <motion.div
                        className="progress-fill"
                        initial={{ width: '0%' }}
                        animate={{ width: `${progress}%` }}
                        transition={{ type: 'spring', damping: 20 }}
                      />
                    </div>
                    <div style={{ fontFamily: 'JetBrains Mono', fontSize: '1.2rem', fontWeight: 800, color: 'var(--accent-main)' }}>
                      {progress.toFixed(0)}%
                    </div>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

export default App;
