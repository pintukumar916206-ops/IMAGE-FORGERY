import { useEffect, useMemo, useState } from "react";
import { getMediaBlobUrl } from "../services/api";

const formatLabel = (label) => {
  if (label === "likely_tampered") return "Likely edited";
  if (label === "likely_authentic") return "Likely original";
  if (label === "inconclusive") return "Inconclusive";
  if (label === "invalid_input") return "Invalid image";
  if (label === "failed") return "Failed";
  return "Unknown";
};

const statusClass = (label) => {
  if (label === "likely_tampered") return "status-bad";
  if (label === "likely_authentic") return "status-good";
  return "status-warn";
};

const safePercent = (value) => {
  const number = Number(value || 0);
  return `${(number * 100).toFixed(1)}%`;
};

const Result = ({ report, previewUrl, onReset }) => {
  const [elaMapUrl, setElaMapUrl] = useState(null);
  const score = Number(report.forensic_score ?? (report.score || 0) * 100).toFixed(1);
  const details = report.details || {};
  const elaMap = report.artifacts?.ela_map;
  const label = report.label || "unknown";
  const method = useMemo(() => {
    const text = String(report.method || "forensic");
    return text.replace(/_/g, " ");
  }, [report.method]);

  useEffect(() => {
    let cancelled = false;
    let objectUrl = null;

    const load = async () => {
      if (!elaMap) {
        setElaMapUrl(null);
        return;
      }
      try {
        objectUrl = await getMediaBlobUrl(elaMap);
        if (cancelled) {
          if (objectUrl) URL.revokeObjectURL(objectUrl);
          return;
        }
        setElaMapUrl(objectUrl);
      } catch {
        if (!cancelled) {
          setElaMapUrl(null);
        }
      }
    };

    load();

    return () => {
      cancelled = true;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [elaMap]);

  return (
    <section className="panel result-panel">
      <div className="result-header">
        <h2>Analysis Result</h2>
        <button type="button" className="secondary-btn" onClick={onReset}>
          Analyze Another Image
        </button>
      </div>

      <div className="result-grid">
        <div className="result-card">
          <p className="label">Score</p>
          <p className="value">{score}%</p>
        </div>

        <div className="result-card">
          <p className="label">Status</p>
          <p className={`status-chip ${statusClass(label)}`}>{formatLabel(label)}</p>
        </div>

        <div className="result-card">
          <p className="label">Method</p>
          <p className="value">{method}</p>
        </div>

        <div className="result-card">
          <p className="label">Time</p>
          <p className="value">{Math.round(report.execution_time_ms || 0)} ms</p>
        </div>
      </div>

      <div className="details-grid">
        <div className="detail-card">
          <p className="label">ELA</p>
          <p className="value">{safePercent(details.ela)}</p>
        </div>

        <div className="detail-card">
          <p className="label">Feature Match</p>
          <p className="value">{safePercent(details.orb)}</p>
        </div>

        <div className="detail-card">
          <p className="label">Wavelet</p>
          <p className="value">{safePercent(details.wavelet)}</p>
        </div>

        <div className="detail-card">
          <p className="label">Metadata</p>
          <p className="value">{safePercent(details.metadata)}</p>
        </div>
      </div>

      <div className="ela-compare">
        <div className="image-pane">
          <p className="label">Original</p>
          {previewUrl ? <img src={previewUrl} alt="Original" className="result-image" /> : <p className="helper">No preview</p>}
        </div>

        <div className="image-pane">
          <p className="label">ELA Map</p>
          {elaMapUrl ? <img src={elaMapUrl} alt="ELA map" className="result-image" /> : <p className="helper">Not available</p>}
        </div>
      </div>
    </section>
  );
};

export default Result;
