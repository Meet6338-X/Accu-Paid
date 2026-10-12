const BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000';

async function req(path, { method = 'GET', body } = {}) {
  const res = await fetch(BASE + path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw { status: res.status, detail: data.detail || res.statusText };
  return data;
}

export const api = {
  root: () => req('/'),
  health: () => req('/health'),
  chat: (query) => req('/chat', { method: 'POST', body: { query } }),
  approve: (runId, verdict, reason, signature) =>
    req(`/approve/${runId}`, { method: 'POST', body: { verdict, reason, signature } }),
  run: (runId) => req(`/runs/${runId}`),
  audit: (runId, format = 'json') => req(`/runs/${runId}/audit${format === 'csv' ? '?format=csv' : ''}`),
  slip: (payload) => req('/ingest/slip', { method: 'POST', body: payload }),
  notice: (text) => req('/ingest/notice', { method: 'POST', body: { text } }),
};

export const API_BASE = BASE;
