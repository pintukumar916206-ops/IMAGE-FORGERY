import React, { useCallback } from "react";
import { motion } from "framer-motion";

const Upload = ({ onFileSelect, onStart, preview, loading, error }) => {
  const handleDrop = useCallback((e) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith("image/")) {
      onFileSelect(file);
    }
  }, [onFileSelect]);

  const handleChange = (e) => {
    const file = e.target.files[0];
    if (file) onFileSelect(file);
  };

  return (
    <div className="glass-panel upload-card">
      <div 
        className={`drop-zone ${preview ? 'has-preview' : ''}`}
        onDrop={handleDrop}
        onDragOver={(e) => e.preventDefault()}
      >
        {preview ? (
          <img src={preview} alt="Preview" className="upload-preview" />
        ) : (
          <div className="upload-prompt">
            <span className="upload-icon">📁</span>
            <p>Drag or browse image to begin forensic scan</p>
          </div>
        )}
        <input 
          type="file" 
          id="file-input" 
          className="hidden" 
          onChange={handleChange} 
          accept="image/*" 
        />
        <label htmlFor="file-input" className="overlay-label"></label>
      </div>

      <div className="upload-actions">
        {error && <div className="error-message">{error}</div>}
        <button 
          className="btn-primary" 
          onClick={onStart} 
          disabled={!preview || loading}
        >
          {loading ? "Initializing..." : "Start Core Analysis"}
        </button>
      </div>
    </div>
  );
};

export default Upload;
