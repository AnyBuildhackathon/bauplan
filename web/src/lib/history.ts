// Saved chats (GET /api/history): the backend keeps every conversation with its build,
// so the history menu and the Logbook can list and reopen them.
import { apiFetch } from "./api";

export interface SavedChat {
  id: string;
  title: string;
  /** The product label, empty before a product was picked. */
  product: string;
  /** Unix seconds. */
  created_at: number;
  updated_at: number;
  messages: number;
  versions: number;
}

export interface Transcript extends SavedChat {
  chat: { role: "user" | "agent"; text: string }[];
}

/** Saved chats newest first, and the id of the chat open on the bench. */
export async function loadHistory(): Promise<{ current: string; items: SavedChat[] }> {
  try {
    const res = await apiFetch("/api/history");
    if (!res.ok) return { current: "", items: [] };
    const body = (await res.json()) as { current?: string; items?: SavedChat[] };
    return { current: body.current ?? "", items: body.items ?? [] };
  } catch {
    return { current: "", items: [] };
  }
}

export async function loadTranscript(id: string): Promise<Transcript | null> {
  try {
    const res = await apiFetch(`/api/history/${encodeURIComponent(id)}`);
    if (!res.ok) return null;
    return ((await res.json()) as { item: Transcript }).item;
  } catch {
    return null;
  }
}

/** "14:05" today, "Yesterday 14:05", else "23 Oct 14:05". */
export function whenText(unixSeconds: number, now = new Date()): string {
  const d = new Date(unixSeconds * 1000);
  const clock = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((day(now) - day(d)) / 86_400_000);
  if (days === 0) return clock;
  if (days === 1) return `Yesterday ${clock}`;
  return `${d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })} ${clock}`;
}
