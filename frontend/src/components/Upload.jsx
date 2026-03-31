import React, { useRef } from "react";

const Upload = ({ onFileSelect, loading, preview, error, onStart }) => {
  const fileInput = useRef(null);

  const onDrop = (e) => {
    e.preventDefault();
    if (loading) return;
    const file = e.dataTransfer.files?.[0];
    if (file) onFileSelect(file);
  };

  const onFileChange = (e) => {
    if (loading) return;
    const file = e.target.files?.[0];
    if (file) onFileSelect(file);
  };

  return (
    <div className="glass-panel upload-view">
      <h2>Forensic Analysis Suite</h2>
      <p className="description">
        Verify image authenticity using multi-layered heuristic algorithms and localized artifacts detection.
      </p>
      <div
        className={`upload-box ${loading ? "disabled" : ""}`}
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        onClick={() => !loading && fileInput.current?.click()}
      >
        {preview ? (
          <div className="preview-wrap">
            <img src={preview} alt="Upload preview" />
            <div className="overlay">Change image</div>
          </div>
        ) : (
          <div className="upload-prompt">
            <span className="upload-icon">Upload</span>
            <p>Select or drop image for analysis</p>
          </div>
        )}
        <input
          type="file"
          ref={fileInput}
          hidden
          accept="image/*"
          onChange={onFileChange}
        />
      </div>
      {error && <div className="error-msg">{error}</div>}
      <button 
        className="btn-primary" 
        disabled={!preview || loading} 
        onClick={onStart}
        style={{ marginTop: '2rem' }}
      >
        {loading ? "Initializing..." : "Execute Pipeline"}
      </button>
    </div>
  );
};

export default Upload;
