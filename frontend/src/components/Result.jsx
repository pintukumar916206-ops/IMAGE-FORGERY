import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { getMediaUrl } from '../services/api';

const Result = ({ report, preview, onReset }) => {
  const [sliderPos, setSliderPos] = useState(50);
  const { isForged } = report;
  const confidence = report.confidence_display ?? report.confidence ?? 0;
  const copyMove = report.analyses.copy_move ?? report.analyses.sift;

  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      className="container"
    >
      <div className="dashboard-layout glass-panel" style={{ background: '#fff' }}>
        <div className="left-panel" style={{ background: isForged ? 'var(--red-status)' : 'var(--accent-main)' }}>
          <div>
            <span className="tiny-label" style={{ opacity: 0.8 }}>VERDICT</span>
            <h2 style={{ fontSize: '2.5rem', fontWeight: 900, textTransform: 'uppercase' }}>
              {isForged ? 'FORGED' : 'AUTHENTIC'}
            </h2>

            <div style={{ marginTop: '2rem' }}>
              <span className="tiny-label" style={{ opacity: 0.8 }}>CONFIDENCE</span>
              <span className="big-stat" style={{ fontSize: '4.5rem' }}>{confidence.toFixed(1)}%</span>
            </div>
          </div>

          <div className="footer-meta">
            <div style={{ marginBottom: '1.5rem', fontWeight: 600, fontSize: '0.8rem', opacity: 0.7 }}>
              Image Analysis Profile<br />
              Processing Time: {(report.execution_time_ms ?? 0).toFixed(0)}ms
            </div>
            <button
              onClick={onReset}
              className="btn-primary"
              style={{ width: '100%', background: '#fff', color: isForged ? 'var(--red-status)' : 'var(--accent-main)', border: 'none', boxShadow: 'none' }}
            >
              NEW ANALYSIS
            </button>
          </div>
        </div>

        <div className="right-panel">
          <div className="analysis-grid">
            <div className="signal-card" style={{ gridColumn: 'span 2' }}>
              <span className="tiny-label">INTERACTIVE ELA COMPARISON</span>
              <div style={{ position: 'relative', width: '100%', marginTop: '0.8rem', cursor: 'ew-resize' }}>
                <div style={{
                  position: 'relative',
                  width: '100%',
                  aspectRatio: '16/9',
                  backgroundColor: '#000',
                  borderRadius: '10px',
                  overflow: 'hidden',
                  border: '2px solid #000'
                }}>
                  <img
                    src={preview}
                    alt="Original"
                    style={{ width: '100%', height: '100%', objectFit: 'contain', position: 'absolute' }}
                  />
                  <div style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: `${sliderPos}%`,
                    height: '100%',
                    overflow: 'hidden'
                  }}>
                    <img
                      src={getMediaUrl(report.analyses.ela.map)}
                      alt="ELA Map"
                      style={{ width: `${100 / (sliderPos || 1)}%`, height: '100%', objectFit: 'contain' }}
                    />
                  </div>
                  <div style={{
                    position: 'absolute',
                    top: 0,
                    left: `${sliderPos}%`,
                    width: '4px',
                    height: '100%',
                    backgroundColor: '#fff',
                    boxShadow: '0 0 8px rgba(0,0,0,0.5)'
                  }} />
                  <div style={{
                    position: 'absolute',
                    top: '50%',
                    left: `${sliderPos}%`,
                    transform: 'translate(-50%, -50%)',
                    backgroundColor: '#fff',
                    padding: '4px 8px',
                    borderRadius: '4px',
                    fontSize: '0.7rem',
                    fontWeight: 800,
                    color: '#000'
                  }}>
                    ← ORIGINAL | ELA →
                  </div>
                </div>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={sliderPos}
                  onChange={(e) => setSliderPos(Number(e.target.value))}
                  style={{
                    width: '100%',
                    marginTop: '0.8rem',
                    cursor: 'pointer',
                    height: '6px'
                  }}
                />
              </div>
              <p className="description" style={{ marginTop: '0.8rem' }}>
                {isForged
                  ? "Bright areas indicate compression inconsistencies. High variance suggests manipulation."
                  : "ELA map should show uniform low values across image. Isolated bright areas are suspicious."}
              </p>
            </div>

            <div className="signal-card">
              <span className="tiny-label">SIGNAL_ELA</span>
              <div style={{ padding: '1rem', background: '#f8faf9', borderRadius: '8px', marginBottom: '1rem' }}>
                <div style={{ fontSize: '1.4rem', fontWeight: 900, color: report.analyses.ela.score > 0.6 ? 'var(--red-status)' : 'var(--accent-main)' }}>
                  {(report.analyses.ela.score * 100).toFixed(1)}%
                </div>
                <div style={{ fontSize: '0.7rem', marginTop: '0.3rem', opacity: 0.7 }}>Compression Variance</div>
              </div>
              <p className="description">Thresholds calibrated for JPEG bitstreams.</p>
            </div>

            <div className="signal-card">
              <span className="tiny-label">SIGNAL_COPY-MOVE</span>
              <div style={{ padding: '1rem', background: '#f8faf9', borderRadius: '8px', marginBottom: '1rem' }}>
                <div style={{ fontSize: '1.4rem', fontWeight: 900 }}>{copyMove?.matches ?? 0}</div>
                <div style={{ fontSize: '0.7rem', marginTop: '0.3rem', opacity: 0.7 }}>Matching Clusters</div>
              </div>
              <p className="description">ORB-based feature matching between regions.</p>
            </div>

            {report.analyses.wavelet_noise && (
              <div className="signal-card">
                <span className="tiny-label">SIGNAL_WAVELET_NOISE</span>
                <div style={{ padding: '1rem', background: '#f8faf9', borderRadius: '8px', marginBottom: '1rem' }}>
                  <div style={{ fontSize: '1.4rem', fontWeight: 900, color: report.analyses.wavelet_noise.entropy > 4.5 ? 'var(--red-status)' : 'var(--accent-main)' }}>
                    {report.analyses.wavelet_noise.entropy.toFixed(3)}
                  </div>
                  <div style={{ fontSize: '0.7rem', marginTop: '0.3rem', opacity: 0.7 }}>High-Freq Noise Entropy</div>
                </div>
                <p className="description">Detects signal irregularities in the DWT HH band.</p>
              </div>
            )}

            {report.analyses.cnn_inference !== undefined && (
              <div className="signal-card">
                <span className="tiny-label">MODEL_CNN_SCORE</span>
                <div style={{ padding: '1rem', background: '#f8faf9', borderRadius: '8px', marginBottom: '1rem' }}>
                  <div style={{ fontSize: '1.4rem', fontWeight: 900, color: report.analyses.cnn_inference > 0.7 ? 'var(--red-status)' : 'var(--accent-main)' }}>
                    {(report.analyses.cnn_inference * 100).toFixed(1)}%
                  </div>
                  <div style={{ fontSize: '0.7rem', marginTop: '0.3rem', opacity: 0.7 }}>Deep Feature Probability</div>
                </div>
                <p className="description">Deep learning extraction score</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
};

export default Result;
