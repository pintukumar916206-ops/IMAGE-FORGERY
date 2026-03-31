import React from "react";

const getMediaUrl = (filename) => {
  if (!filename) return null;
  const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api";
  const base = API_BASE.replace('/api', '');
  return `${base}${filename.startsWith('/') ? '' : '/'}${filename}`;
};

const Result = ({ report, onReset }) => {
  const isForged = report.is_forged;
  const confidence = report.confidence;
  const reasons = report.reasons || [];
  const evidence = report.evidence || {};

  return (
    <div className="glass-panel result-view">
      <div className="result-header">
        <button className="btn-secondary" onClick={onReset}>Reset Analysis</button>
      </div>

      <div className="verdict-container">
        <span className={`huge-badge ${isForged ? "forged" : "clean"}`}>
          {isForged ? "TAMPERED" : "AUTHENTIC"}
        </span>
        <div className="verdict-description" style={{ marginTop: "1rem" }}>
          {isForged 
            ? "Multiple forensic indicators suggest local manipulation." 
            : "No structural or compression anomalies detected."}
        </div>
      </div>

      <div className="technical-details-wrap">
        <div className="dashboard-grid">
          <div className="sidebar-metrics glass-panel">
            <div className="confidence-meter">
              <h3>Detection Confidence</h3>
              <div className="meter-ring">
                <span className={isForged ? "text-red" : "text-green"}>{confidence}%</span>
              </div>
            </div>

            <div className="reasons-list">
              <h3>Heuristic Logs</h3>
              <ul>
                {reasons.map((r, i) => (
                  <li key={i} className={isForged ? "reason-alert" : "reason-ok"}>{r}</li>
                ))}
              </ul>
            </div>

            <div className="metric-row">
              <h3>Metadata Scan</h3>
              <p>Signatures: {evidence.exif?.software_signature || "None"}</p>
            </div>

            {evidence.ml && (
              <div className="metric-row">
                <h3>Signal Processing</h3>
                <p><strong>{evidence.ml.method}</strong> ({evidence.ml.score}%)</p>
                {evidence.ml.fallback_used && (
                  <span className="badge-warning">Heuristic Fallback</span>
                )}
              </div>
            )}
            
            <div className="metric-row">
                <h3>Processing Duration</h3>
                <p>{report.total_duration_ms}ms</p>
            </div>
          </div>

          <div className="evidence-grid">
            <div className="view-card">
                <h3>Error Level Analysis</h3>
                {evidence.ela?.ela_heatmap_url ? (
                    <img src={getMediaUrl(evidence.ela.ela_heatmap_url)} alt="ELA Map" />
                ) : (
                    <div className="placeholder-box">No Signal</div>
                )}
            </div>
            <div className="view-card">
                <h3>Copy-Move Localization</h3>
                {evidence.sift?.sift_heatmap_url ? (
                    <img src={getMediaUrl(evidence.sift.sift_heatmap_url)} alt="SIFT Map" />
                ) : (
                    <div className="placeholder-box">No Signal</div>
                )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Result;
