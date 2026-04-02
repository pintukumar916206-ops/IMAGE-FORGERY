import axios from "axios";

const configuredBase = import.meta.env.VITE_API_URL || "/api";
const API_BASE = configuredBase.endsWith("/")
  ? configuredBase.slice(0, -1)
  : configuredBase;

const API_USERNAME = import.meta.env.VITE_API_USERNAME || "";
const API_PASSWORD = import.meta.env.VITE_API_PASSWORD || "";

let authToken = null;

const axiosInstance = axios.create({
  baseURL: API_BASE,
  timeout: 60000,
});

axiosInstance.interceptors.request.use((config) => {
  if (authToken) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${authToken}`;
  }
  return config;
});

axiosInstance.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config || {};
    const url = originalRequest.url || "";

    if (
      error.response?.status === 401 &&
      !originalRequest._retry &&
      !url.includes("/auth/")
    ) {
      originalRequest._retry = true;
      await authenticate();
      return axiosInstance(originalRequest);
    }

    return Promise.reject(error);
  },
);

const loginWithCredentials = async (username, password) => {
  const response = await axios.post(`${API_BASE}/auth/token`, {
    username,
    password,
  });
  authToken = response.data.access_token;
  return response.data;
};

export const authenticate = async () => {
  if (!API_USERNAME || !API_PASSWORD) {
    throw new Error(
      "Missing VITE_API_USERNAME or VITE_API_PASSWORD in frontend environment.",
    );
  }

  try {
    return await loginWithCredentials(API_USERNAME, API_PASSWORD);
  } catch (error) {
    if (error.response?.status !== 401) {
      throw error;
    }

    await axios.post(`${API_BASE}/auth/register`, {
      username: API_USERNAME,
      password: API_PASSWORD,
    });

    return loginWithCredentials(API_USERNAME, API_PASSWORD);
  }
};

export const uploadImage = async (file) => {
  const formData = new FormData();
  formData.append("file", file);
  const response = await axiosInstance.post("/detect", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return response.data;
};

export const getProgress = async (taskId) => {
  return axiosInstance.get(`/progress/${taskId}`, { timeout: 5000 });
};

export const getReport = async (taskId) => {
  return axiosInstance.get(`/report/${taskId}`, { timeout: 10000 });
};

export const getMediaUrl = (filename) => {
  if (!filename) return null;
  if (filename.startsWith("http")) return filename;
  const tokenParam = authToken
    ? `?token=${encodeURIComponent(authToken)}`
    : "";
  if (API_BASE.startsWith("http")) {
    return `${API_BASE}/uploads/${encodeURIComponent(filename)}${tokenParam}`;
  }
  return `${window.location.origin}${API_BASE}/uploads/${encodeURIComponent(filename)}${tokenParam}`;
};
