import axios from "axios";

const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api";

export const uploadImage = async (file) => {
  const formData = new FormData();
  formData.append("file", file);
  const response = await axios.post(`${API_BASE}/detect`, formData, {
    timeout: 60000,
    headers: { "Content-Type": "multipart/form-data" },
  });
  return response.data;
};

export const getProgress = async (taskId) => {
  const response = await axios.get(`${API_BASE}/progress/${taskId}`, {
    timeout: 5000,
  });
  return response.data;
};

export const getReport = async (taskId) => {
  const response = await axios.get(`${API_BASE}/report/${taskId}`, {
    timeout: 10000,
  });
  return response.data;
};

export const getMediaUrl = (filename) => {
  if (!filename) return null;
  // Handle absolute paths if returned by backend, otherwise construct
  if (filename.startsWith('http')) return filename;
  return `${API_BASE.replace('/api', '')}${filename.startsWith('/') ? '' : '/'}${filename}`;
};
