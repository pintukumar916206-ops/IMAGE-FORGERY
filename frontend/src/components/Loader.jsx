const Loader = ({ stage, progress }) => {
  return (
    <section className="panel loader-panel">
      <h2>Processing</h2>
      <p className="helper">{stage || "Running checks..."}</p>

      <div className="progress-shell">
        <div className="progress-fill" style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} />
      </div>

      <p className="score-badge">{Math.round(progress || 0)}%</p>
    </section>
  );
};

export default Loader;
