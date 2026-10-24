// Saved chats for the logbook. A session is archived when it is reset, so the
// Logbuch can show earlier runs next to the current one. Browser storage only.
import type { ChatItem } from "../events/store";
import { stripMarkdown } from "./format";

export interface SavedChat {
  at: number;
  title: string;
  messages: { role: "user" | "agent"; text: string }[];
  result: string;
}

const KEY = "bauplan.saved-chats";
const MAX = 6;

export function loadSavedChats(): SavedChat[] {
  try {
    const raw = localStorage.getItem(KEY);
    const list = raw ? (JSON.parse(raw) as SavedChat[]) : [];
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

export function archiveChat(chat: ChatItem[], result: string) {
  const messages = chat.flatMap((c) => (c.kind === "msg" ? [{ role: c.role, text: stripMarkdown(c.text) }] : []));
  if (messages.length < 2) return;
  const first = messages.find((m) => m.role === "user")?.text ?? "Chat";
  const entry: SavedChat = { at: chat[0]?.at ?? Date.now(), title: first.slice(0, 60), messages, result };
  const saved = loadSavedChats();
  // Replaying the same recording twice should not fill the archive with copies.
  const rest = saved.filter((c) => !(c.title === entry.title && c.messages.length === entry.messages.length && c.result === entry.result));
  try {
    localStorage.setItem(KEY, JSON.stringify([entry, ...rest].slice(0, MAX)));
  } catch {
    // Storage full or blocked: the archive is a convenience, losing it is fine.
  }
}
