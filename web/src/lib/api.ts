// Where the backend lives. The browser app talks to it through the Vite proxy
// (same origin); the desktop build sets VITE_API_BASE=http://localhost:8100.
const BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/+$/, "");

export const apiUrl = (path: string) => `${BASE}${path}`;

/** Resolves a file URL from an event: backend paths (/files/, /api/) go to the backend. */
export function assetUrl(u: string | null | undefined): string | null {
  if (!u) return null;
  if (/^(https?:|data:|blob:)/.test(u)) return u;
  if (u.startsWith("/files/") || u.startsWith("/api/")) return `${BASE}${u}`;
  return u;
}
