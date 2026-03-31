const BASE = '/api';

let sessionToken = localStorage.getItem('shams_session') || '';

export function setSession(token) {
  sessionToken = token;
  localStorage.setItem('shams_session', token);
}

export function clearSession() {
  sessionToken = '';
  localStorage.removeItem('shams_session');
}

export function getSession() {
  return sessionToken;
}

async function api(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${sessionToken}`,
      ...opts.headers,
    },
  });
  if (res.status === 401) {
    clearSession();
    window.location.href = '/login';
    return null;
  }
  return res.json();
}

export const get = (path) => api(path);
export const post = (path, data) => api(path, { method: 'POST', body: JSON.stringify(data) });
export const patch = (path, data) => api(path, { method: 'PATCH', body: JSON.stringify(data) });
export const del = (path) => api(path, { method: 'DELETE' });
