// Thin API client for the FixFinance backend. The browser calls the API on the
// host (localhost:8000); override with NEXT_PUBLIC_API_BASE if needed.
const BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export function getToken() {
  return typeof window !== "undefined" ? localStorage.getItem("ff_token") : null;
}
export function setToken(t) {
  localStorage.setItem("ff_token", t);
}
export function clearToken() {
  localStorage.removeItem("ff_token");
}

async function req(method, path, body, auth = true) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const t = getToken();
    if (t) headers["Authorization"] = `Bearer ${t}`;
  }
  const res = await fetch(BASE + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data?.error?.message || res.statusText);
  }
  return data;
}

export const api = {
  login: (username, password) => req("POST", "/auth/login", { username, password }, false),
  startSession: () => req("POST", "/sessions"),
  sendMessage: (sid, text) => req("POST", `/sessions/${sid}/messages`, { text }),
  getSession: (sid) => req("GET", `/sessions/${sid}`),
  buildProforma: (sid) => req("POST", `/sessions/${sid}/build-proforma`),
  getProforma: (id) => req("GET", `/proformas/${id}`),
  patchProforma: (id, edits) => req("PATCH", `/proformas/${id}`, edits),
  requestReport: (id) => req("POST", `/proformas/${id}/report`),
  getReport: (jid) => req("GET", `/reports/${jid}`),
};
