// The Settings panel behind the sliders icon. The dashboard shows only the essentials;
// these toggles add the rest (agent steps, tool cards, all metrics,
// learning mode), show which speech recognition listens, switch the mic from
// hands-free to push-to-talk. In live mode it also holds the bench's model settings:
// where Claude runs (the API key or the local Claude Code subscription), which Claude
// orchestrates, which runs the sub-agents, how hard each one thinks (effort), and
// whether the orchestrator delegates. GET/POST /api/settings.
import { useEffect, useRef, useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { useSource } from "../events/source";
import { apiFetch } from "../lib/api";
import { usePartners } from "../lib/partners";
import { useUi, type Display } from "../lib/ui";
import { useBenchResults } from "../views/BenchResults";

const DISPLAY: { key: keyof Display; label: string; hint: string; control?: string }[] = [
  { key: "agents", label: "Show agent steps and costs", hint: "Orchestrator and sub-agents in the chat", control: "setting:agents" },
  { key: "tools", label: "Show tool details", hint: "FreeCAD, Blender, MuJoCo cards", control: "setting:tools" },
  { key: "allMetrics", label: "Show all metrics", hint: "Thrust to weight and the rest", control: "setting:all_metrics" },
  { key: "mascot", label: "Show Mechanic on the canvas", hint: "His full figure in the corner while he speaks or explains" },
  { key: "learning", label: "Learning mode", hint: "Mechanic explains each decision with the physics; the logbook shows what you learned" },
];

const SPEECH: Record<"reson8" | "browser" | "none", string> = {
  reson8: "Speech recognition: Reson8 · English",
  browser: "Speech recognition: browser · English",
  none: "No speech recognition in this browser. Type instead.",
};

function Toggle({ label, hint, on, onChange, control }: { label: string; hint?: string; on: boolean; onChange: (on: boolean) => void; control?: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} onClick={() => onChange(!on)} data-control={control} className="flex w-full items-center gap-3 py-1.5 text-left">
      <span className="min-w-0 flex-1">
        <span className="block text-[14px] font-semibold text-ink">{label}</span>
        {hint && <span className="block text-[12px] text-muted">{hint}</span>}
      </span>
      <span className={`relative h-6 w-10 shrink-0 rounded-full transition ${on ? "bg-accent" : "bg-track"}`}>
        <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-[left] ${on ? "left-[18px]" : "left-0.5"}`} />
      </span>
    </button>
  );
}

interface Settings {
  orchestrator_model: string;
  orchestrator_effort: string;
  subagent_model: string;
  subagent_effort: string;
  delegation: boolean;
  models: { id: string; label: string }[];
  efforts: string[];
  /** Where Claude runs as asked: auto, api or subscription; `provider` says what runs and why. */
  llm_provider: string;
  provider: { requested: string; active: "api" | "subscription" | "mock"; detail: string };
  providers: { id: string; label: string }[];
}

function Select({ label, value, options, onChange }: { label: string; value: string; options: { value: string; label: string }[]; onChange: (v: string) => void }) {
  return (
    <label className="flex items-center justify-between gap-3 py-1 text-[14px] font-semibold text-ink-2">
      {label}
      <select
        name={label.toLowerCase().replace(/\s+/g, "-")}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-8 rounded-full bg-tile px-3 text-[13px] font-semibold text-ink outline-none hover:bg-track"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function BenchSettings() {
  // Global, so Mechanic can open the panel too (lib/pilot.ts).
  const open = useUi((s) => s.settingsOpen);
  const setOpen = useUi((s) => s.setSettingsOpen);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  const display = useUi((s) => s.display);
  const director = useUi((s) => s.director);
  const setDirector = useUi((s) => s.setDirector);
  const setDisplay = useUi((s) => s.setDisplay);
  const micMode = useUi((s) => s.micMode);
  const setMicMode = useUi((s) => s.setMicMode);
  const stt = useUi((s) => s.stt);
  const mode = useSource((s) => s.mode);
  const live = mode === "live";

  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => {
      // A synthetic press from the pointer is no outside click.
      if (e.isTrusted && !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", close);
    return () => window.removeEventListener("pointerdown", close);
  }, [open, setOpen]);
  useEffect(() => {
    if (!open || !live) return;
    apiFetch("/api/settings")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((body: Settings) => setSettings(body))
      .catch(() => setError("Settings need the live backend."));
  }, [open, live]);

  const change = async (patch: Partial<Settings>) => {
    setError(null);
    try {
      const res = await apiFetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!res.ok) {
        // A refused choice says why, e.g. the subscription on a public server.
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(body?.detail ?? `HTTP ${res.status}`);
      }
      const next = (await res.json()) as Settings;
      setSettings(next);
      // The top bar names the provider at once, not at the next status poll.
      usePartners.setState((s) => ({
        partners: s.partners.map((p) => (p.id === "claude" ? { ...p, provider: next.provider.active, detail: next.provider.detail } : p)),
      }));
    } catch (err) {
      setError(`Not saved (${err instanceof Error ? err.message : "error"}).`);
    }
  };

  const models = settings?.models.map((m) => ({ value: m.id, label: m.label })) ?? [];
  const providers = settings?.providers?.map((p) => ({ value: p.id, label: p.label })) ?? [];
  const efforts = settings?.efforts.map((e) => ({ value: e, label: e })) ?? [];
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`flex h-10 w-10 items-center justify-center rounded-full transition ${open ? "bg-ink text-white" : "text-ink-2 hover:bg-tile"}`}
        title="Settings"
        aria-label="Settings"
        data-target="settings"
        data-control="panel:settings panel:settings:close"
      >
        <SlidersHorizontal className="h-4.5 w-4.5" />
      </button>
      {open && (
        <div className="scroll-soft absolute top-12 right-0 z-[90] max-h-[calc(100vh-90px)] w-[340px] animate-rise overflow-y-auto rounded-[20px] bg-card p-4 shadow-[var(--shadow-float)]">
          <h3 className="eyebrow mb-1">Show</h3>
          <Toggle label="Director mode" hint="Follow CAD, tests and version changes. A tab click pauses for 30 seconds." on={director} onChange={setDirector} />
          {DISPLAY.map((d) => (
            <Toggle key={d.key} control={d.control} label={d.label} hint={d.hint} on={display[d.key]} onChange={(on) => setDisplay({ [d.key]: on })} />
          ))}
          <h3 className="eyebrow mt-3 mb-1 border-t border-line pt-3">Voice</h3>
          <Toggle
            control="setting:push_to_talk"
            label="Push-to-talk"
            hint={micMode === "ptt" ? "Hold the mic or space while you speak" : "Off: click the mic once and just talk"}
            on={micMode === "ptt"}
            onChange={(on) => setMicMode(on ? "ptt" : "handsfree")}
          />
          <p className="pt-1 text-[12px] text-muted">{SPEECH[stt]}</p>
          <h3 className="eyebrow mt-3 mb-1 border-t border-line pt-3">Evaluation</h3>
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              useBenchResults.getState().setOpen(true);
            }}
            className="flex w-full items-center gap-3 py-1.5 text-left"
          >
            <span className="min-w-0 flex-1">
              <span className="block text-[14px] font-semibold text-ink">AnyBuild Bench results</span>
              <span className="block text-[12px] text-muted">Pass rate and cost over 20 product prompts</span>
            </span>
            <span className="text-[13px] font-bold text-link">Open</span>
          </button>
          {live && (
            <div className="mt-3 border-t border-line pt-3">
              {!settings ? (
                <p className="text-[14px] text-muted">{error ?? "Loading models …"}</p>
              ) : (
                <>
                  {settings.provider && (
                    <>
                      <h3 className="eyebrow mb-1">Claude</h3>
                      <Select label="Runs on" value={settings.llm_provider} options={providers} onChange={(v) => void change({ llm_provider: v })} />
                      <p className="mb-3 text-[12px] leading-snug text-muted">{settings.provider.detail}</p>
                    </>
                  )}
                  <h3 className="eyebrow mb-1">Orchestrator</h3>
                  <Select label="Model" value={settings.orchestrator_model} options={models} onChange={(v) => void change({ orchestrator_model: v })} />
                  <Select label="Effort" value={settings.orchestrator_effort} options={efforts} onChange={(v) => void change({ orchestrator_effort: v })} />
                  <h3 className="eyebrow mt-3 mb-1">Sub-agents</h3>
                  <Select label="Model" value={settings.subagent_model} options={models} onChange={(v) => void change({ subagent_model: v })} />
                  <Select label="Effort" value={settings.subagent_effort} options={efforts} onChange={(v) => void change({ subagent_effort: v })} />
                  <label className="mt-3 flex cursor-pointer items-center justify-between gap-3 text-[14px] font-semibold text-ink-2">
                    Delegate parts, checks and pricing
                    <input
                      type="checkbox"
                      checked={settings.delegation}
                      onChange={(e) => void change({ delegation: e.target.checked })}
                      className="h-5 w-5 cursor-pointer accent-[#1f6f78]"
                    />
                  </label>
                  <p className="mt-2 text-[12px] leading-snug text-faint">Applies to the next request. Each part's FreeCAD script is always written by a sub-agent.</p>
                  {error && <p className="mt-1 text-[12px] font-semibold text-fail-ink">{error}</p>}
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
