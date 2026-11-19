import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const client = axios.create({ baseURL: API_BASE_URL });

client.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 401) {
      localStorage.removeItem("access_token");
      window.location.href = "/login";
    }
    return Promise.reject(error);
  }
);

export const authApi = {
  register: (username, email, password) =>
    client.post("/auth/register", { username, email, password }),
  login: (identifier, password) =>
    client.post("/auth/login", { identifier, password }),
  forgotPassword: (identifier) =>
    client.post("/auth/forgot-password", { identifier }),
  resetPassword: (token, newPassword) =>
    client.post("/auth/reset-password", { token, new_password: newPassword }),
  otpRequest: (identifier) =>
    client.post("/auth/otp/request", { identifier }),
  otpVerify: (identifier, code) =>
    client.post("/auth/otp/verify", { identifier, code }),
};

export const casesApi = {
  list: () => client.get("/cases"),
  create: (title, legalBasis) =>
    client.post("/cases", { title, legal_basis: legalBasis }),
  ingest: (caseId, posts) =>
    client.post(`/cases/${caseId}/ingest`, { posts }),
  getGraph: (caseId) => client.get(`/cases/${caseId}/graph`),
  getPosts: (caseId) => client.get(`/cases/${caseId}/posts`),
};

export const analysisApi = {
  compareText: (payload) => client.post("/analyze/text", payload),
  correlatePgp: (payload) => client.post("/correlate/pgp", payload),
  correlateUsername: (payload) => client.post("/correlate/username", payload),
  traceWallet: (address, chain) =>
    client.post("/trace/wallet", { address, chain }),
};

export const nlpApi = {
  query: (caseId, query) => client.post(`/cases/${caseId}/query`, { query }),
  getSuggestions: (caseId) => client.get(`/cases/${caseId}/suggestions`),
};

export const reportsApi = {
  getReport: (caseId) => client.get(`/cases/${caseId}/report`),

  // TXT/PDF downloads need the Authorization header, so a plain <a href>
  // won't work (the browser's direct navigation wouldn't carry it) —
  // fetch as a blob via axios instead, then trigger the save through a
  // throwaway object URL + anchor click.
  downloadTxt: (caseId) => _downloadFile(`/cases/${caseId}/export/txt`, `case_${caseId}_report.txt`),
  downloadPdf: (caseId) => _downloadFile(`/cases/${caseId}/export/pdf`, `case_${caseId}_report.pdf`),
};

async function _downloadFile(path, filename) {
  const response = await client.get(path, { responseType: "blob" });
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export default client;
