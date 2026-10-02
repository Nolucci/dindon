// Everything the page asks of the application. The session is a cookie that the page cannot read.
export class AuthError extends Error {
  status = 401;
}

async function request(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options });
  if (response.status === 401) throw new AuthError('not authenticated');
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    // A refusal that the application wrote is a sentence; a form that was not filled in properly is a list of fields
    const error = new Error(typeof detail.detail === 'string' && detail.detail ? detail.detail : `Erreur ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

const query = (params) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') q.set(k, v);
  const s = q.toString();
  return s ? `?${s}` : '';
};

export const api = {
  session: () => request('/api/session'),
  login: (password) =>
    request('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }) }),
  logout: () => request('/api/logout', { method: 'POST' }),
  guilds: () => request('/api/guilds'),
  graph: (params) => request(`/api/graph${query(params)}`),
  people: (q, guild) => request(`/api/people${query({ q, guild })}`),
  person: (id, guild) => request(`/api/person/${id}${query({ guild })}`),
  status: () => request('/api/status'),
  importOptions: () => request('/api/import/options'),
  importStatus: () => request('/api/import'),
  importStart: (body) => request('/api/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  importCancel: () => request('/api/import/cancel', { method: 'POST' }),
};

// Live events. The browser reconnects by itself; `onState` says whether the line is open.
export function openEvents(onEvent, onState) {
  const source = new EventSource('/events');
  source.onopen = () => onState(true);
  source.onerror = () => onState(false);
  source.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data));
    } catch {
      /* an event that is not understood is ignored */
    }
  };
  return () => source.close();
}
