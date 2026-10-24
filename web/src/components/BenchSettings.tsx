// The bench's model settings: which Claude orchestrates, which runs the sub-agents, how hard
// each one thinks (effort), and whether the orchestrator delegates. GET/POST /api/settings.
import { useEffect, useRef, useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { apiUrl } from "../lib/api";

interface Settings {
  orchestrator_model: string;
  orchestrator_effort: string;
  subagent_model: string;
  subagent_effort: string;
  delegation: boolean;
  models: { id: string; label: string }[];
  efforts: string[];
}

function Select({ label, value, options, onChange }: { label: string; value: string; options: { value: string; label: string }[]; onChange: (v: string) => void }) {
  return (
    <label className="flex items-center justify-between gap-3 py-1 text-[14px] font-semibold text-ink-2">
      {label}
      <select
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
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    fetch(apiUrl("/api/settings"))
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((body: Settings) => setSettings(body))
      .catch(() => setError("Settings need the live backend."));
    const close = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", close);
    return () => window.removeEventListener("pointerdown", close);
  }, [open]);

  const change = async (patch: Partial<Settings>) => {
    setError(null);
    try {
      const res = await fetch(apiUrl("/api/settings"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setSettings((await res.json()) as Settings);
    } catch (err) {
      setError(`Not saved (${err instanceof Error ? err.message : "error"}).`);
    }
  };

  const models = settings?.models.map((m) => ({ value: m.id, label: m.label })) ?? [];
  const efforts = settings?.efforts.map((e) => ({ value: e, label: e })) ?? [];
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`flex h-10 w-10 items-center justify-center rounded-full transition ${open ? "bg-ink text-white" : "text-ink-2 hover:bg-card"}`}
        title="Models"
        aria-label="Model settings"
      >
        <SlidersHorizontal className="h-4.5 w-4.5" />
      </button>
      {open && (
        <div className="absolute top-12 right-0 z-[90] w-80 animate-rise rounded-[20px] bg-card p-4 shadow-[var(--shadow-float)]">
          {!settings ? (
            <p className="text-[14px] text-muted">{error ?? "Loading …"}</p>
          ) : (
            <>
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
                  className="h-5 w-5 cursor-pointer accent-[#0b9677]"
                />
              </label>
              <p className="mt-2 text-[12px] leading-snug text-faint">Applies to the next request. Each part's FreeCAD script is always written by a sub-agent.</p>
              {error && <p className="mt-1 text-[12px] font-semibold text-fail-ink">{error}</p>}
            </>
          )}
        </div>
      )}
    </div>
  );
}
