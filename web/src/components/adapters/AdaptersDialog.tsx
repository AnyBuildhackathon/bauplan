// Check adapters, opened from Settings (or ?adapters): the engine behind each of AnyBuild's
// checks on this machine, in Mechanics, Electronics, Simulation and Manufacturing. Each row says
// whether the engine is installed, where and which version, what it does here or what happens
// without it, how to install it, and how it last ran. GET /api/adapters only reads files, so the
// dialog asks on every open; while a row is still checking (the Isaac SSH probe) it asks again.
// It renders into document.body, so no layout around the Settings button can clip or cover it.
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { create } from "zustand";
import { Check, X } from "lucide-react";
import { apiFetch } from "../../lib/api";
import { whenText } from "../../lib/history";
import { Chip } from "../ui/primitives";

export type AdapterDomain = "mechanics" | "electronics" | "simulation" | "manufacturing";

export interface Adapter {
  id: string;
  name: string;
  domain: AdapterDomain;
  /** The checks and outputs this engine gives, such as ERC and DRC. */
  provides: string[];
  /** Runs on another machine (the Isaac GPU host): available means reachable. */
  remote: boolean;
  /** null while a slow probe (the Isaac SSH check) still runs. */
  available: boolean | null;
  version: string | null;
  /** Where it was found, the home folder as ~. */
  path: string | null;
  detail: string;
  /** How to install it; commands are in backticks. */
  install_hint: string;
  /** The latest run on this machine; `at` in Unix seconds. */
  last: { at: number; pass: boolean; summary: string } | null;
}

const DOMAINS: { id: AdapterDomain; label: string }[] = [
  { id: "mechanics", label: "Mechanics" },
  { id: "electronics", label: "Electronics" },
  { id: "simulation", label: "Simulation" },
  { id: "manufacturing", label: "Manufacturing" },
];

export const useAdapters = create<{ open: boolean; setOpen: (open: boolean) => void }>((set) => ({
  open: new URLSearchParams(window.location.search).has("adapters"),
  setOpen: (open) => set({ open }),
}));

/** An install hint with its backticked commands as code a single click selects for copying. */
function Hint({ text }: { text: string }) {
  return (
    <p className="mt-2 text-[13px] leading-relaxed text-ink-2" data-hint>
      {text.split("`").map((part, i) =>
        i % 2 ? (
          <code key={i} className="box-decoration-clone rounded-md bg-card px-1.5 py-px font-label text-[12px] break-words text-ink ring-1 ring-line select-all">
            {part}
          </code>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </p>
  );
}

/** Installed or Missing for an engine on this machine, Connected or Offline for a remote host. */
function stateLabel(a: Pick<Adapter, "available" | "remote">): string {
  if (a.available === null) return "Checking";
  if (a.available) return a.remote ? "Connected" : "Installed";
  return a.remote ? "Offline" : "Missing";
}

function State({ adapter }: { adapter: Adapter }) {
  const label = stateLabel(adapter);
  if (adapter.available === null) return <Chip tone="agent">{label}</Chip>;
  if (!adapter.available) return <Chip>{label}</Chip>;
  return (
    <Chip tone="ok">
      <Check className="h-3.5 w-3.5" strokeWidth={3} />
      {label}
    </Chip>
  );
}

function Row({ adapter: a }: { adapter: Adapter }) {
  return (
    <li className="flex min-w-0 flex-col rounded-[18px] bg-page-2 px-4 py-3" data-adapter={a.id} data-available={String(a.available)}>
      <div className="flex items-center gap-3">
        <p className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2 text-[16px] leading-snug font-bold text-ink">
          {a.name}
          {a.version && <span className="num text-[13px] font-semibold text-muted">{a.version}</span>}
        </p>
        <State adapter={a} />
      </div>
      <p className="text-[13px] font-semibold text-muted">{a.provides.join(" · ")}</p>
      <p className="mt-1.5 text-[14px] leading-snug text-ink-2">{a.detail}</p>
      {a.path && (
        <p className="mt-1 truncate font-label text-[12px] text-faint" title={a.path}>
          {a.path}
        </p>
      )}
      {a.available === false && a.install_hint && <Hint text={a.install_hint} />}
      {a.last && (
        <p className="mt-2 flex items-start gap-1.5 border-t border-line pt-2 text-[13px] leading-snug text-ink-2">
          {a.last.pass ? (
            <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ok-ink" strokeWidth={3} />
          ) : (
            <X className="mt-0.5 h-3.5 w-3.5 shrink-0 text-fail-ink" strokeWidth={3} />
          )}
          <span className="min-w-0">
            <span className="num font-semibold text-muted">Last run {whenText(a.last.at)}</span> · {a.last.summary}
          </span>
        </p>
      )}
    </li>
  );
}

export function AdaptersDialog() {
  const open = useAdapters((s) => s.open);
  const setOpen = useAdapters((s) => s.setOpen);
  const [rows, setRows] = useState<Adapter[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", esc);
    let alive = true;
    let again: ReturnType<typeof setTimeout> | undefined;
    const load = async (tries: number) => {
      try {
        const res = await apiFetch("/api/adapters");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = (await res.json()) as Adapter[];
        if (!alive) return;
        setRows(body);
        setError(null);
        // The SSH probe answers within seconds, so a row still checking is asked about again.
        if (tries > 1 && body.some((a) => a.available === null)) again = setTimeout(() => void load(tries - 1), 2500);
      } catch {
        if (alive) setError("Check adapters need the live backend.");
      }
    };
    void load(4);
    return () => {
      alive = false;
      clearTimeout(again);
      window.removeEventListener("keydown", esc);
    };
  }, [open, setOpen]);

  if (!open) return null;
  const installed = rows?.filter((a) => a.available).length ?? 0;
  return createPortal(
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-[rgb(30_30_50/0.28)] p-4 backdrop-blur-[3px]" onMouseDown={() => setOpen(false)}>
      <div
        className="flex max-h-[min(900px,calc(100vh-32px))] w-[940px] max-w-full animate-rise flex-col overflow-hidden rounded-[32px] bg-card shadow-[var(--shadow-float)]"
        onMouseDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="adapters-title"
      >
        <div className="flex shrink-0 items-start gap-4 px-7 pt-6 pb-4">
          <div className="min-w-0">
            <h1 id="adapters-title" className="text-[30px] leading-none font-extrabold tracking-[-0.03em]">
              Check adapters
            </h1>
            <p className="mt-2 text-[15px] leading-snug font-semibold text-muted">
              The engine behind each check on this machine: what is installed, what is missing and how each last ran.
              {rows && (
                <>
                  {" "}
                  <span className="num whitespace-nowrap text-ink-2">
                    {installed} of {rows.length} available.
                  </span>
                </>
              )}
            </p>
          </div>
          <button type="button" onClick={() => setOpen(false)} className="ml-auto rounded-full p-2.5 text-muted hover:bg-tile hover:text-ink" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="scroll-soft min-h-0 flex-1 overflow-y-auto px-7 pb-7">
          {!rows && <p className="rounded-[20px] bg-page-2 px-4 py-6 text-center text-[15px] text-muted">{error ?? "Looking for the engines …"}</p>}
          {rows &&
            DOMAINS.map((domain) => {
              const group = rows.filter((a) => a.domain === domain.id);
              if (!group.length) return null;
              return (
                <section key={domain.id} className="mt-5 first:mt-0" aria-labelledby={`adapters-${domain.id}`}>
                  <h2 id={`adapters-${domain.id}`} className="eyebrow mb-2">
                    {domain.label}
                  </h2>
                  <ul className="grid gap-2 md:grid-cols-2">
                    {group.map((a) => (
                      <Row key={a.id} adapter={a} />
                    ))}
                  </ul>
                </section>
              );
            })}
        </div>
      </div>
    </div>,
    document.body,
  );
}
