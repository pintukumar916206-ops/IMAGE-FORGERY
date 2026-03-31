import React, { useState, useEffect, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";
import * as api from "./services/api";
import Upload from "./components/Upload";
import Result from "./components/Result";

function App() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState(null);
  
  const pollIntervalRef = useRef(null);

  const clearPolling = () => {
    if (pollIntervalRef.current) {
      clearTimeout(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  };

  const handleFileSelect = (selectedFile) => {
    if (preview) URL.revokeObjectURL(preview);
    setFile(selectedFile);
    setPreview(URL.createObjectURL(selectedFile));
    setReport(null);
    setError(null);
    setProgress(null);
  };

  const pollProgress = async (taskId) => {
    const executePoll = async () => {
      try {
        const data = await api.getProgress(taskId);
        if (data.status === "complete") {
          const reportData = await api.getReport(taskId);
          setReport(reportData);
          setLoading(false);
          setProgress(null);
          return;
        }
        if (data.status === "error") {
          setError(data.stage || "Analysis pipeline failed.");
          setLoading(false);
          return;
        }
        setProgress(data);
        pollIntervalRef.current = setTimeout(executePoll, 1000);
      } catch (err) {
        // Soft fail on polling errors
        pollIntervalRef.current = setTimeout(executePoll, 2000);
      }
    };
    executePoll();
  };

  const startAnalysis = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const response = await api.uploadImage(file);
      if (response.task_id) {
        pollProgress(response.task_id);
      }
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to initialize processing.");
      setLoading(false);
    }
  };

  const reset = () => {
    setFile(null);
    setPreview(null);
    setReport(null);
    setError(null);
    setProgress(null);
    clearPolling();
  };

  useEffect(() => {
    return () => {
      clearPolling();
      if (preview) URL.revokeObjectURL(preview);
    };
  }, [preview]);

  return (
    <div className="app-container">
      <nav className="glass-panel main-nav">
        <div className="brand">
          <span className="logo-icon">ID</span>
          <h1 className="glow-text">Forensic Image Suite</h1>
        </div>
      </nav>

      <main className="container">
        <AnimatePresence mode="wait">
          {report ? (
            <motion.div 
              key="result"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
            >
              <Result report={report} onReset={reset} />
            </motion.div>
          ) : loading ? (
            <motion.div 
              key="loading" 
              className="glass-panel loading-view"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              <div className="spinner"></div>
              {progress ? (
                <div className="progress-info">
                  <div className="progress-stage">{progress.stage}</div>
                  <div className="progress-bar">
                    <div className="progress-fill" style={{ width: `${progress.progress}%` }}></div>
                  </div>
                  <div className="progress-percentage">{progress.progress}%</div>
                </div>
              ) : (
                <div className="progress-info">
                    <div className="progress-stage">Initializing Forensic Core...</div>
                </div>
              )}
            </motion.div>
          ) : (
            <motion.div 
              key="upload"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
            >
              <Upload 
                onFileSelect={handleFileSelect} 
                onStart={startAnalysis} 
                preview={preview} 
                loading={loading} 
                error={error} 
              />
            </motion.div>
          )}
        </AnimatePresence>
      </main>
    </div>
  );
}

export default App;
