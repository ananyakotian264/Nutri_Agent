const configuredBase = import.meta.env.VITE_API_URL?.trim();
const BASE_URL = (configuredBase || (import.meta.env.DEV
  ? "http://localhost:8000"
  : "https://nutri-agent-backend.onrender.com")).replace(/\/$/, "");
const TOKEN_KEY = "nutri_access_token";

let accessToken = localStorage.getItem(TOKEN_KEY);

export function setAccessToken(token) {
  accessToken = token || null;
  if (accessToken) localStorage.setItem(TOKEN_KEY, accessToken);
  else localStorage.removeItem(TOKEN_KEY);
}

export function getAccessToken() {
  return accessToken;
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  let response;
  try {
    response = await fetch(`${BASE_URL}${path}`, { ...options, headers });
  } catch {
    throw new Error("Could not reach Nutri-Agent. Check your connection and try again.");
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (response.status === 404 && path === "/predict-food") {
      throw new Error("The prediction API is not deployed on the backend yet. Deploy the updated backend and try again.");
    }
    if (response.status === 401 && accessToken && !["/login", "/signup"].includes(path)) {
      setAccessToken(null);
      window.dispatchEvent(new Event("nutri-session-expired"));
    }
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  if (response.status === 204) return null;
  return response.json();
}

export const api = {
  signup: (credentials) => request("/signup", { method: "POST", body: JSON.stringify(credentials) }),
  login: (credentials) => request("/login", { method: "POST", body: JSON.stringify(credentials) }),
  logout: () => request("/logout", { method: "POST" }),
  getProfile: () => request("/profile"),
  getSummary: () => request("/summary"),
  getHealth: () => request("/health"),
  saveProfile: (data) => request("/profile", { method: "POST", body: JSON.stringify(data) }),
  logFood: (message) => request("/log-food", { method: "POST", body: JSON.stringify({ message }) }),
  predictFood: (message) => request("/predict-food", { method: "POST", body: JSON.stringify({ message }) }),
  logManual: (data) => request("/log-manual", { method: "POST", body: JSON.stringify(data) }),
  deleteMeal: (id) => request(`/meals/${id}`, { method: "DELETE" }),
  getModelPredictions: () => request("/model-predictions"),
  saveModelPredictionActual: (id, data) => request(`/model-predictions/${id}/actual`, { method: "PUT", body: JSON.stringify(data) }),
  deleteModelPrediction: (id) => request(`/model-predictions/${id}`, { method: "DELETE" }),
  getPredictionChecks: () => request("/prediction-checks"),
  savePredictionCheck: (data) => request("/prediction-checks", { method: "POST", body: JSON.stringify(data) }),
  deletePredictionCheck: (id) => request(`/prediction-checks/${id}`, { method: "DELETE" }),
};
