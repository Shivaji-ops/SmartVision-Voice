// Thin wrapper around fetch. The token lives in localStorage so a refresh keeps you signed in.
const TOKEN_KEY = "sv_token";

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage can be blocked; the session then lasts until the tab closes */
  }
}

// Called when the server says the token is no longer good.
let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

// FastAPI sends errors as {detail: "text"} or, for validation, {detail: [{msg, loc}]}.
function messageFrom(body, status) {
  const detail = body && body.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0];
    const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : "";
    return field ? `${field}: ${first.msg}` : first.msg;
  }
  if (status >= 500) return "The server had a problem. Try again in a moment.";
  return "Something went wrong.";
}

async function request(method, path, body) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check that the backend is running.");
  }

  if (response.status === 204) return null;

  let data = null;
  try {
    data = await response.json();
  } catch {
    /* non-JSON error body */
  }

  if (!response.ok) {
    if (response.status === 401 && token) onUnauthorized();
    throw new ApiError(response.status, messageFrom(data, response.status));
  }
  return data;
}

// Fetches a sound with the sign-in header and returns a URL the browser can play.
export async function fetchAudio(method, path, body) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check that the backend is running.");
  }
  if (!response.ok) {
    let data = null;
    try {
      data = await response.json();
    } catch {
      /* non-JSON error body */
    }
    if (response.status === 401 && token) onUnauthorized();
    throw new ApiError(response.status, messageFrom(data, response.status));
  }
  return URL.createObjectURL(await response.blob());
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body) => request("POST", path, body ?? {}),
  patch: (path, body) => request("PATCH", path, body),
  del: (path) => request("DELETE", path),
};
