import axios from "axios";

const configuredBase = import.meta.env.VITE_API_URL || "/api";
const API_BASE = configuredBase.endsWith("/") ? configuredBase.slice(0, -1) : configuredBase;

let authToken = null;
let csrfToken = null;
const CSRF_COOKIE_NAME = "forensic_csrf";

const client = axios.create({
  baseURL: API_BASE,
  timeout: 60000,
  withCredentials: true,
});

client.interceptors.request.use((config) => {
  if (authToken) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${authToken}`;
  }
  return config;
});

let refreshPromise = null;

const readCookie = (name) => {
  const token = `${name}=`;
  const cookies = document.cookie ? document.cookie.split(";") : [];
  for (const cookie of cookies) {
    const item = cookie.trim();
    if (item.startsWith(token)) {
      return decodeURIComponent(item.slice(token.length));
    }
  }
  return null;
};

const requestRefresh = async () => {
  const csrfHeader = csrfToken || readCookie(CSRF_COOKIE_NAME);
  if (!csrfHeader) {
    throw new Error("Missing CSRF token");
  }
  const response = await client.post("/auth/refresh", null, {
    __skipRefresh: true,
    headers: { "X-CSRF-Token": csrfHeader },
  });
  const nextToken = response.data?.access_token || null;
  const nextCsrf = response.data?.csrf_token || null;
  if (!nextToken) {
    throw new Error("Refresh did not return access token");
  }
  setSession(nextToken, nextCsrf);
  return nextToken;
};

const performRefresh = async () => {
  if (!refreshPromise) {
    refreshPromise = requestRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
};

client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error?.config;
    const status = error?.response?.status;
    if (!originalRequest || status !== 401 || originalRequest.__skipRefresh || originalRequest.__retry) {
      return Promise.reject(error);
    }

    const requestPath = String(originalRequest.url || "");
    if (
      requestPath.includes("/auth/token") ||
      requestPath.includes("/auth/login") ||
      requestPath.includes("/auth/refresh") ||
      requestPath.includes("/auth/logout")
    ) {
      clearToken();
      return Promise.reject(error);
    }

    originalRequest.__retry = true;
    try {
      const nextToken = await performRefresh();
      originalRequest.headers = originalRequest.headers || {};
      originalRequest.headers.Authorization = `Bearer ${nextToken}`;
      return client(originalRequest);
    } catch (refreshError) {
      clearToken();
      return Promise.reject(refreshError);
    }
  },
);

export const getToken = () => authToken;

export const getCsrfToken = () => csrfToken;

export const setSession = (token, csrf) => {
  authToken = token || null;
  csrfToken = csrf || null;
};

export const clearToken = () => setSession(null, null);

export const bootstrapSession = async () => {
  if (authToken) return true;
  try {
    await performRefresh();
    return true;
  } catch {
    clearToken();
    return false;
  }
};

export const registerUser = async (username, password) => {
  const response = await client.post("/auth/register", { username, password });
  return response.data;
};

export const loginUser = async (username, password) => {
  const response = await client.post("/auth/token", { username, password });
  setSession(response.data.access_token, response.data.csrf_token);
  return response.data;
};

export const logoutUser = async () => {
  try {
    const csrfHeader = csrfToken || readCookie(CSRF_COOKIE_NAME);
    if (csrfHeader) {
      await client.post("/auth/logout", null, {
        __skipRefresh: true,
        headers: { "X-CSRF-Token": csrfHeader },
      });
    }
  } finally {
    clearToken();
  }
};

export const uploadImage = async (file) => {
  const formData = new FormData();
  formData.append("file", file);
  const response = await client.post("/detect", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return response.data;
};

export const getProgress = async (taskId) => client.get(`/progress/${taskId}`);

export const getReport = async (taskId) => client.get(`/report/${taskId}`);

export const getMediaBlobUrl = async (filename) => {
  if (!filename) return null;
  const encodedFilename = encodeURIComponent(filename);
  const response = await client.get(`/uploads/${encodedFilename}`, { responseType: "blob" });
  return URL.createObjectURL(response.data);
};
