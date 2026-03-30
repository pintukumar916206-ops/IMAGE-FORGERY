import React, { useEffect, useRef, useState } from "react";
import axios from "axios";
import { AnimatePresence } from "framer-motion";

const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api";
const API_USERNAME = import.meta.env.VITE_API_USERNAME || "analyst";
const API_PASSWORD = import.meta.env.VITE_API_PASSWORD || "change-me-analyst";
const TOKEN_STORAGE_KEY = "forgery_api_token";

function App() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState(null);
  const [showTechnical, setShowTechnical] = useState(false);

  const fileInput = useRef(null);
  const pollIntervalRef = useRef(null);

  const clearPolling = () => {
    if (pollIntervalRef.current) {
      clearTimeout(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  };

  const setSelectedFile = (selected) => {
    if (!selected) {
      return;
    }

    if (preview) {
      URL.revokeObjectURL(preview);
    }

    setFile(selected);
    setPreview(URL.createObjectURL(selected));
    setReport(null);
    setError(null);
    setProgress(null);
  };

  const onFileChange = (event) => {
    setSelectedFile(event.target.files[0]);
  };

  const onDrop = (event) => {
    event.preventDefault();
    setSelectedFile(event.dataTransfer.files[0]);
  };

  const fetchToken = async () => {
    const existing = localStorage.getItem(TOKEN_STORAGE_KEY);
    if (existing) {
      return existing;
    }

    const payload = new URLSearchParams();
    payload.append("username", API_USERNAME);
    payload.append("password", API_PASSWORD);

    const response = await axios.post(`${API_BASE}/token`, payload, {
      timeout: 10000,
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });

    const token = response.data?.access_token;
    if (!token) {
      throw new Error("Token endpoint did not return an access token.");
    }

    localStorage.setItem(TOKEN_STORAGE_KEY, token);
    return token;
  };

  const buildAuthHeaders = async () => {
    const token = await fetchToken();
    return { Authorization: `Bearer ${token}` };
  };

  const pollProgress = async (taskId) => {
    clearPolling();

    let delay = 1000;
    let elapsedMs = 0;
    const maxDelay = 8000;
    const timeoutMs = 120000;

    const executePoll = async () => {
      if (elapsedMs > timeoutMs) {
        setError("Analysis timed out. Please retry.");
        setLoading(false);
        return;
      }

      try {
        const headers = await buildAuthHeaders();
        const response = await axios.get(`${API_BASE}/progress/${taskId}`, {
          timeout: 5000,
          headers,
        });
        const data = response.data;

        if (data.status === "complete") {
          await fetchReport(taskId);
          return;
        }
        if (data.status === "error") {
          setError(data.stage || "An error occurred during analysis.");
          setLoading(false);
          return;
        }

        setProgress({
          progress: data.progress,
          stage: data.stage,
          status: data.status,
          eta: data.eta_seconds,
        });
      } catch (requestError) {
        if (requestError.response?.status === 401) {
          localStorage.removeItem(TOKEN_STORAGE_KEY);
        }
      }

      elapsedMs += delay;
      delay = Math.min(delay * 1.5, maxDelay);
      pollIntervalRef.current = setTimeout(executePoll, delay);
    };

    executePoll();
  };

  const fetchReport = async (reportId) => {
    try {
      const headers = await buildAuthHeaders();
      const response = await axios.get(`${API_BASE}/report/${reportId}`, {
        timeout: 10000,
        headers,
      });
      setReport(response.data);
      setLoading(false);
      setProgress(null);
    } catch (requestError) {
      if (requestError.response?.status === 401) {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
      }
      if (requestError.response?.data?.detail) {
        setError(`Error: ${requestError.response.data.detail}`);
      } else {
        setError("Failed to fetch report.");
      }
      setLoading(false);
    }
  };

  const processImage = async (retryArg) => {
    const isRetry = retryArg === true;
    
    if (!file) {
      setError("Please select an image first.");
      return;
    }

    if (!isRetry) {
      setLoading(true);
      setError(null);
      setProgress(null);
      setReport(null);
    }

    const formData = new FormData();
    formData.append("file", file);

    try {
      const headers = await buildAuthHeaders();
      const response = await axios.post(`${API_BASE}/detect`, formData, {
        timeout: 65000,
        headers: {
          ...headers,
          "Content-Type": "multipart/form-data",
        },
      });

      if (response.data.task_id) {
        await pollProgress(response.data.task_id);
      } else {
        setReport(response.data);
        setLoading(false);
      }
    } catch (requestError) {
      clearPolling();
      if (requestError.response?.status === 401) {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
        if (!isRetry) {
          return processImage(true);
        }
      }

      if (requestError.code === "ECONNABORTED") {
        setError("Request timeout. Please try with a smaller image.");
      } else if (requestError.response?.data?.detail) {
        setError(`Error: ${requestError.response.data.detail}`);
      } else if (requestError.message === "Network Error") {
        setError("Cannot connect to backend. Ensure server is running.");
      } else {
        setError("Analysis failed. Please try again.");
      }
      setLoading(false);
    }
  };

  useEffect(() => {
    return () => {
      clearPolling();
      if (preview) {
        URL.revokeObjectURL(preview);
      }
    };
  }, [preview]);

  return (
    <div className="app-container">
      <nav className="glass-panel main-nav">
        <div className="brand">
          <span className="logo-icon">ID</span>
          <h1 className="glow-text">Image Forgery Detection</h1>
        </div>
      </nav>

      <main className="container">
        <AnimatePresence mode="wait">
          {report ? (
            <div>
              <div className="glass-panel result-view">
                <div className="result-header">
                  <button
                    className="btn-secondary"
                    onClick={() => {
                      setReport(null);
                      setFile(null);
                      if (preview) {
                        URL.revokeObjectURL(preview);
                      }
                      setPreview(null);
                      setProgress(null);
                      setShowTechnical(false);
                    }}
                  >
                    {"<- New Analysis"}
                  </button>
                </div>

                <div className="verdict-container">
                  <p className="verdict-description">Forensic analysis complete. System verdict:</p>
                  <span className={`huge-badge ${report.is_forged ? "forged" : "clean"}`}>
                    {report.is_forged ? "FAKE" : "ORIGINAL"}
                  </span>
                  <div className="verdict-description" style={{ marginTop: "20px" }}>
                    {report.is_forged
                      ? "This image shows evidence of manipulation and structural inconsistency."
                      : "This image appears to be an authentic capture with no detectable forgery."}
                  </div>

                  <button className="toggle-details-btn" onClick={() => setShowTechnical(!showTechnical)}>
                    {showTechnical ? "Hide Technical Details" : "Show Technical Details"}
                  </button>
                </div>

                <AnimatePresence>
                  {showTechnical && (
                    <div className="technical-details-wrap">
                      <div className="dashboard-grid">
                        <div className="sidebar-metrics glass-panel">
                          <div className="confidence-meter">
                            <h3>Confidence Score</h3>
                            <div className="meter-ring">
                              <span className={report.is_forged ? "text-red" : "text-green"}>
                                {report.confidence}%
                              </span>
                            </div>
                          </div>

                          <div className="reasons-list">
                            <h3>Analysis Results</h3>
                            <ul>
                              {report.reasons?.map((reason, index) => (
                                <li key={index} className={report.is_forged ? "reason-alert" : "reason-ok"}>
                                  {reason}
                                </li>
                              ))}
                            </ul>
                          </div>

                          <div className="exif-data">
                            <h3>Metadata</h3>
                            <p>Editor: {report.evidence?.exif?.software_signature || "Unknown"}</p>
                            {report.evidence?.exif?.warnings?.length > 0 && (
                              <p className="exif-warning">Editing software signature detected</p>
                            )}
                          </div>

                          {report.evidence?.ml?.score !== undefined && (
                            <div className="ml-score">
                              <h3>ML Model Score</h3>
                              <p style={{ fontSize: '1.2rem', fontWeight: 'bold' }}>{report.evidence.ml.score}%</p>
                              
                              {report.evidence.ml.hard_metrics && (
                                <div className="hard-metrics">
                                  <h4>Model Benchmarks</h4>
                                  <div className="metric-row"><span>Dataset:</span> <span>{report.evidence.ml.hard_metrics.benchmark_dataset}</span></div>
                                  <div className="metric-row"><span>Architecture:</span> <span>{report.evidence.ml.hard_metrics.model_architecture}</span></div>
                                  <div className="metric-row summary-metric"><span>Accuracy Verification:</span> <span>{report.evidence.ml.hard_metrics.proven_accuracy}</span></div>
                                  <div className="metric-row summary-metric text-orange"><span>False Pos Rate:</span> <span>{report.evidence.ml.hard_metrics.false_positive_rate}</span></div>
                                  
                                  <div className="confusion-matrix-box">
                                    <h4>Confusion Matrix</h4>
                                    <table className="confusion-table">
                                      <thead>
                                        <tr>
                                          <th></th>
                                          <th>P. Auth</th>
                                          <th>P. Forge</th>
                                        </tr>
                                      </thead>
                                      <tbody>
                                        <tr>
                                          <th>A. Auth</th>
                                          <td className="true-negative">{report.evidence.ml.hard_metrics.confusion_matrix[0][0]}</td>
                                          <td className="false-positive">{report.evidence.ml.hard_metrics.confusion_matrix[0][1]}</td>
                                        </tr>
                                        <tr>
                                          <th>A. Forge</th>
                                          <td className="false-negative">{report.evidence.ml.hard_metrics.confusion_matrix[1][0]}</td>
                                          <td className="true-positive">{report.evidence.ml.hard_metrics.confusion_matrix[1][1]}</td>
                                        </tr>
                                      </tbody>
                                    </table>
                                  </div>
                                </div>
                              )}
                            </div>
                          )}
                        </div>

                        <div className="evidence-grid">
                          <div className="view-card">
                            <h3>Original Image</h3>
                            <img src={preview} alt="Input" />
                          </div>

                          <div className="view-card">
                            <h3>Error Level Analysis</h3>
                            {report.evidence?.ela?.ela_heatmap_b64 ? (
                              <>
                                <img src={report.evidence.ela.ela_heatmap_b64} alt="ELA Heatmap" />
                                <p className="caption">Score: {report.evidence.ela.anomaly_score}</p>
                              </>
                            ) : (
                              <div className="placeholder-box">No anomalies</div>
                            )}
                          </div>

                          <div className="view-card">
                            <h3>Copy-Move Detection</h3>
                            {report.evidence?.sift?.sift_heatmap_b64 ? (
                              <>
                                <img src={report.evidence.sift.sift_heatmap_b64} alt="SIFT Copy-Move" />
                                <p className="caption">Clusters: {report.evidence.sift.clone_clusters_found}</p>
                              </>
                            ) : (
                              <div className="placeholder-box">No clones detected</div>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </AnimatePresence>
              </div>
            </div>
          ) : loading ? (
            <div className="glass-panel loading-view">
              <div className="spinner"></div>
              {progress ? (
                <div className="progress-info">
                  <div className="progress-stage">{progress.stage}</div>
                  <div className="progress-bar">
                    <div className="progress-fill" style={{ width: `${progress.progress}%` }}></div>
                  </div>
                  <div className="progress-percentage">{progress.progress}%</div>
                  {progress.eta && <div className="progress-eta">ETA: {progress.eta.toFixed(1)}s</div>}
                </div>
              ) : (
                <p>Initializing analysis...</p>
              )}
            </div>
          ) : (
            <div className="glass-panel upload-view">
              <h2>Image Forensics Analysis</h2>
              <p className="description">
                Detect manipulation using metadata checks, ELA, copy-move detection, and ML scoring.
              </p>

              <div
                className={`upload-box ${loading ? "disabled" : ""}`}
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => !loading && onDrop(event)}
                onClick={() => !loading && fileInput.current?.click()}
              >
                {preview ? (
                  <div className="preview-wrap">
                    <img src={preview} alt="Preview" />
                    <div className="overlay">Change image</div>
                  </div>
                ) : (
                  <div className="upload-prompt">
                    <span className="upload-icon">Upload</span>
                    <p>Drag & Drop Image or Click to Browse</p>
                    <small>Any image format, any size</small>
                    <div className="performance-badge">
                      ⚡ Performance Benchmark: Processes 50 images/sec (4 workers)
                    </div>
                  </div>
                )}
                <input type="file" ref={fileInput} hidden accept="*/*" onChange={onFileChange} />
              </div>

              {error && <div className="error-msg">{error}</div>}

              <button className="btn-primary" disabled={!file || loading} onClick={processImage}>
                {loading ? "Analyzing..." : "Analyze Image"}
              </button>
            </div>
          )}
        </AnimatePresence>
      </main>
    </div>
  );
}

export default App;
