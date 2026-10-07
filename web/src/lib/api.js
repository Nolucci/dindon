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
  botInvite: () => request('/api/bot/invite'),
  system: () => request('/api/system'),
  automation: () => request('/api/automation'),
  automationSave: (body) => request('/api/automation', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  discordMap: () => request('/api/discord-map'),
  discordMapSave: (body) => request('/api/discord-map', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  automationRun: () => request('/api/automation/run', { method: 'POST' }),
  performance: () => request('/api/performance'),
  performanceSave: (body) => request('/api/performance', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  debates: () => request('/api/debates'),
  debate: (id) => request(`/api/debates/${id}`),
  privacy: () => request('/api/privacy'),
  privacyFind: (q) => request(`/api/privacy/find${query({ q })}`),
  privacyAct: (action, user_id, reason) =>
    request(`/api/privacy/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: String(user_id), reason: reason || '' }) }),
  digestUrl: (guild, format, part = 'all') => `/api/digest${query({ guild, format, part })}`,
  positions: (guild, filters = {}) => request(`/api/positions${query({ guild, ...filters })}`),
  positionsProposition: (id, guild) => request(`/api/positions/proposition/${id}${query({ guild })}`),
  positionsReview: (id, guild, rejected) =>
    request(`/api/positions/proposition/${id}${query({ guild })}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rejected }) }),
  coherence: (guild) => request(`/api/positions/coherence${query({ guild })}`),
  positionsLinks: (id, guild, links) =>
    request(`/api/positions/proposition/${id}/axes${query({ guild })}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ links }) }),
  positionsValidateLinks: (id, guild) => request(`/api/positions/proposition/${id}/axes/validate${query({ guild })}`, { method: 'POST' }),
  positionsOnlyValidated: (value, guild) =>
    request(`/api/positions/only-validated${query({ guild })}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value }) }),
  positionsPerson: (id, guild) => request(`/api/positions/person/${id}${query({ guild })}`),
  analysis: (guild) => request(`/api/analysis${query({ guild })}`),
  analysisWorkers: () => request('/api/performance/workers'),
  analysisWorkersSave: (urls) => request('/api/performance/workers', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ urls }) }),
  analysisStart: (body) => request('/api/analysis', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  analysisCancel: () => request('/api/analysis/cancel', { method: 'POST' }),
  topics: (guild, rejected) => request(`/api/topics${query({ guild, rejected: rejected ? 'true' : undefined })}`),
  topicsValidate: (guild, ids) => request('/api/topics/validate-batch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ guild, ids }) }),
  topicChange: (id, body) => request(`/api/topics/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  topicMerge: (id, into) => request(`/api/topics/${id}/merge`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ into }) }),
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

/** A function that runs a call to the application and, if it fails, tells what to do: `onAuthLost` when the session is gone, `onProblem(message)` otherwise. It returns what the call returns, or undefined. */
export function makeGuard(onAuthLost, onProblem) {
  return async (action) => {
    try {
      return await action();
    } catch (error) {
      if (error instanceof AuthError) onAuthLost();
      else onProblem(error.message);
      return undefined;
    }
  };
}
