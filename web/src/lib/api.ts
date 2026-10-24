// Where the backend lives. The browser app talks to it through the Vite proxy
// (same origin); the desktop build sets VITE_API_BASE=http://localhost:8100, and the
// public web build the backend's public URL (Tailscale Funnel).
const BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/+$/, "");

// The session token from POST /api/access, when the backend asks for an access code.
// Sent as a bearer header; URLs the browser loads on its own (EventSource, images,
// models, videos) carry it as ?access_token=, since they cannot set headers.
const TOKEN_KEY = "anybuild.access";
let token: string | null = readToken();

function readToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function accessToken(): string | null {
  return token;
}

export function setAccessToken(next: string | null) {
  token = next;
  try {
    if (next) localStorage.setItem(TOKEN_KEY, next);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Private windows: the token then lives only in memory.
  }
}

function withToken(url: string): string {
  if (!token) return url;
  return `${url}${url.includes("?") ? "&" : "?"}access_token=${encodeURIComponent(token)}`;
}

export const apiUrl = (path: string) => `${BASE}${path}`;

/** apiUrl for URLs the browser loads itself (EventSource, download links), with the session token. */
export const apiStreamUrl = (path: string) => withToken(apiUrl(path));

/** Resolves a file URL from an event: backend paths (/files/, /api/) go to the backend. */
export function assetUrl(u: string | null | undefined): string | null {
  if (!u) return null;
  if (/^(https?:|data:|blob:)/.test(u)) return u;
  if (u.startsWith("/files/") || u.startsWith("/api/")) return withToken(`${BASE}${u}`);
  return u;
}

type Listener = { onLocked: () => void; onLimited: (message: string) => void };
let listener: Listener | null = null;

/** Who hears that the session ended (401) or a rate limit hit (429); the source store. */
export function onAccessEvents(next: Listener) {
  listener = next;
}

/** The backend's error text, for notices. */
export async function errorDetail(res: Response): Promise<string> {
  try {
    const body = await res.clone().json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Not JSON.
  }
  return `HTTP ${res.status}`;
}

/** fetch() against the backend, with the session token. A 401 locks the app, a 429 says why. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(apiUrl(path), { ...init, headers });
  // A wrong code (POST /api/access) is the access screen's own error, not a lost session.
  if (res.status === 401 && !(path === "/api/access" && init.method === "POST")) {
    setAccessToken(null);
    listener?.onLocked();
  } else if (res.status === 429) {
    listener?.onLimited(await errorDetail(res));
  }
  return res;
}
