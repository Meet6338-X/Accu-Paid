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
  csv: async ({ kind, mapping, file, idPrefix, idPad, monthDefault, validateOnly }) => {
    const fd = new FormData();
    fd.append('kind', kind);
    fd.append('mapping', mapping);
    fd.append('file', file);
    fd.append('id_prefix', idPrefix || '');
    fd.append('id_pad', String(idPad || 3));
    fd.append('month_default', monthDefault || '');
    fd.append('validate_only', validateOnly ? 'true' : 'false');
    const res = await fetch(BASE + '/ingest/csv', { method: 'POST', body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw { status: res.status, detail: data.detail || res.statusText };
    return data;
  },
};

export const API_BASE = BASE;
