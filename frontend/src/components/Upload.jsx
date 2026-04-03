import { useRef } from "react";

const Upload = ({ preview, onFileSelect, onStart, disabled }) => {
  const inputRef = useRef(null);

  return (
    <section className="panel upload-panel">
      <h2>Upload Image</h2>
      <p className="helper">Supported: JPG, PNG, WebP (up to 50 MB)</p>

      <button type="button" className="drop-zone" onClick={() => inputRef.current?.click()}>
        {preview ? <img src={preview} alt="Preview" className="preview-image" /> : <span>Select an image</span>}
      </button>

      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => onFileSelect(event.target.files?.[0] || null)}
      />

      <button type="button" className="primary-btn" onClick={onStart} disabled={disabled}>
        Run Analysis
      </button>
    </section>
  );
};

export default Upload;
