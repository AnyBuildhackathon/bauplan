const de = (digits: number) =>
  new Intl.NumberFormat("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const fmtEur = (v: number) => `${de(2).format(v)} €`;
export const fmtGram = (v: number) => `${de(v < 10 && v % 1 !== 0 ? 1 : 0).format(v)} g`;
export const fmtRatio = (v: number) => de(2).format(v);
export const fmtMin = (v: number) => de(1).format(v);
export const fmtNum = (v: number, digits = 0) => de(digits).format(v);

export function fmtClock(ms: number): string {
  const d = new Date(ms);
  return d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

export function fmtDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${de(1).format(ms / 1000)} s`;
}

/** Tiny markdown-ish helper for chat: **bold** only, everything else stays plain text. */
export function boldSegments(text: string): { text: string; bold: boolean }[] {
  const parts: { text: string; bold: boolean }[] = [];
  const re = /\*\*(.+?)\*\*/g;
  let last = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) parts.push({ text: text.slice(last, m.index), bold: false });
    parts.push({ text: m[1], bold: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), bold: false });
  return parts;
}

export function stripMarkdown(text: string): string {
  return text.replace(/\*\*(.+?)\*\*/g, "$1").replace(/[_`]/g, "");
}
