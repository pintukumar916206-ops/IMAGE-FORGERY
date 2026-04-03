import { useEffect, useMemo, useState } from "react";

import Loader from "../components/Loader";
import Result from "../components/Result";
import Upload from "../components/Upload";
import {
  bootstrapSession,
  getProgress,
  getReport,
  getToken,
  loginUser,
  logoutUser,
  registerUser,
  uploadImage,
} from "../services/api";

const Home = () => {
  const [authMode, setAuthMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [isAuthenticated, setIsAuthenticated] = useState(Boolean(getToken()));
  const [authBootstrapped, setAuthBootstrapped] = useState(false);

  const [selectedFile, setSelectedFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [taskId, setTaskId] = useState(null);
  const [status, setStatus] = useState("idle");
  const [stage, setStage] = useState("");
  const [progress, setProgress] = useState(0);
  const [report, setReport] = useState(null);

  useEffect(() => {
    let active = true;
    const init = async () => {
      if (getToken()) {
        if (active) {
          setIsAuthenticated(true);
          setAuthBootstrapped(true);
        }
        return;
      }
      const ok = await bootstrapSession();
      if (active) {
        setIsAuthenticated(ok);
        setAuthBootstrapped(true);
      }
    };
    init();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
    };
  }, [previewUrl]);

  useEffect(() => {
    if (!taskId || status !== "processing") return undefined;

    const timer = setInterval(async () => {
      try {
        const progressResponse = await getProgress(taskId);
        const data = progressResponse.data;
        setProgress(data.progress || 0);
        setStage(data.stage || "");

        if (data.status === "complete") {
          const reportResponse = await getReport(taskId);
          setReport(reportResponse.data);
          setStatus("done");
          clearInterval(timer);
        }
        if (data.status === "error") {
          setStatus("error");
          setStage(data.stage || "Analysis failed");
          clearInterval(timer);
        }
      } catch (error) {
        setStatus("error");
        setStage(error.response?.data?.detail || "Unable to read task progress");
        clearInterval(timer);
      }
    }, 2000);

    return () => clearInterval(timer);
  }, [taskId, status]);

  const authTitle = useMemo(() => (authMode === "login" ? "Sign In" : "Create Account"), [authMode]);

  const handleAuthenticate = async () => {
    setAuthError("");
    try {
      if (authMode === "register") {
        await registerUser(username, password);
      }
      await loginUser(username, password);
      setIsAuthenticated(true);
    } catch (error) {
      setAuthError(error.response?.data?.detail || "Authentication failed. Use a valid username and at least 8 characters for password.");
    }
  };

  const handleFileSelect = (file) => {
    if (!file || !file.type.startsWith("image/")) return;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setSelectedFile(file);
    setPreviewUrl(URL.createObjectURL(file));
    setReport(null);
    setTaskId(null);
    setStatus("ready");
    setStage("");
    setProgress(0);
  };

  const handleStart = async () => {
    if (!selectedFile) return;
    try {
      setStatus("processing");
      setStage("Uploading image...");
      setProgress(5);
      const response = await uploadImage(selectedFile);
      setTaskId(response.task_id);
    } catch (error) {
      setStatus("error");
      setStage(error.response?.data?.detail || "Failed to submit image");
    }
  };

  const handleReset = () => {
    setSelectedFile(null);
    setReport(null);
    setTaskId(null);
    setStatus("idle");
    setStage("");
    setProgress(0);
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      setPreviewUrl(null);
    }
  };

  if (!authBootstrapped) {
    return (
      <div className="app-shell">
        <section className="panel auth-panel">
          <h1>Image Forensic Analysis</h1>
          <p className="helper">Restoring secure session...</p>
        </section>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="app-shell">
        <section className="panel auth-panel">
          <h1>Image Forensic Analysis</h1>
          <p className="helper">Upload an image and get a clear forensic score. Passwords require at least 8 characters.</p>

          <h2>{authTitle}</h2>
          <input
            type="text"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="Username"
            className="text-input"
            minLength={3}
            maxLength={64}
            pattern="[A-Za-z0-9._@+-]+"
          />
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="Password"
            className="text-input"
            minLength={8}
            maxLength={128}
          />

          {authError ? <p className="error-text">{authError}</p> : null}

          <button type="button" className="primary-btn" onClick={handleAuthenticate} disabled={!username || !password}>
            {authTitle}
          </button>

          <button
            type="button"
            className="link-btn"
            onClick={() => setAuthMode((current) => (current === "login" ? "register" : "login"))}
          >
            {authMode === "login" ? "Need an account? Register" : "Already have an account? Sign in"}
          </button>
        </section>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="top-bar">
        <h1>Image Forensic Analysis</h1>
        <button
          type="button"
          className="secondary-btn"
          onClick={async () => {
            await logoutUser();
            setIsAuthenticated(false);
            setUsername("");
            setPassword("");
          }}
        >
          Sign Out
        </button>
      </header>

      {status === "processing" ? (
        <Loader stage={stage} progress={progress} />
      ) : status === "done" && report ? (
        <Result report={report} previewUrl={previewUrl} onReset={handleReset} />
      ) : (
        <Upload preview={previewUrl} onFileSelect={handleFileSelect} onStart={handleStart} disabled={!selectedFile} />
      )}

      {status === "error" ? <p className="error-text">{stage || "Unexpected error"}</p> : null}
    </div>
  );
};

export default Home;
