import { useEffect, useRef, useState } from "react";
import { BookOpen, Dumbbell, Ellipsis, FastForward, LayoutDashboard, Pause, Play, RotateCcw, SkipForward } from "lucide-react";
import { useSource } from "../events/source";
import { useUi, type View } from "../lib/ui";
import { MeetingTimeline } from "./timeline/MeetingTimeline";
import { Segmented, StatusDot } from "./ui/primitives";

export function Logo({ size = 40 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden className="shrink-0">
      <rect width="40" height="40" rx="12" fill="#1F1F1F" />
      <path d="M13 13 27 27M27 13 13 27" stroke="#FF8A3D" strokeWidth="3" strokeLinecap="round" />
      {[
        [12, 12],
        [28, 12],
        [12, 28],
        [28, 28],
      ].map(([x, y]) => (
        <circle key={`${x}${y}`} cx={x} cy={y} r="4.6" fill="#1F1F1F" stroke="#FF8A3D" strokeWidth="2.4" />
      ))}
      <rect x="16.5" y="16.5" width="7" height="7" rx="2" fill="#FF8A3D" />
    </svg>
  );
}

function SourceControls() {
  const mode = useSource((s) => s.mode);
  const live = useSource((s) => s.live);
  const demo = useSource((s) => s.demo);
  const { setMode, play, pause, restart, setSpeed, skipToEnd } = useSource.getState();
  const resetUi = useUi((s) => s.resetUi);
  const ended = demo.index >= demo.total;

  return (
    <div className="flex items-center gap-2">
      <Segmented
        size="sm"
        value={mode}
        onChange={(m) => {
          resetUi();
          setMode(m);
        }}
        options={[
          {
            value: "live",
            label: (
              <>
                <StatusDot tone={live === "open" ? "ok" : live === "connecting" ? "agent" : "fail"} pulse={live === "connecting" && mode === "live"} hollow={mode !== "live"} />
                Live
              </>
            ),
          },
          { value: "demo", label: "Demo" },
        ]}
      />
      {mode === "demo" ? (
        <div className="flex items-center gap-1 rounded-full bg-card p-1 shadow-[var(--shadow-pill)]">
          <button
            type="button"
            onClick={demo.playing ? pause : play}
            className="flex h-8 items-center gap-1.5 rounded-full bg-ink pr-3 pl-2.5 text-[13px] font-semibold text-white"
            title={demo.playing ? "Pause" : "Abspielen"}
          >
            {demo.playing ? <Pause className="h-3.5 w-3.5" fill="currentColor" /> : <Play className="h-3.5 w-3.5" fill="currentColor" />}
            {demo.playing ? "Pause" : ended ? "Nochmal" : demo.started ? "Weiter" : "Demo starten"}
          </button>
          <button
            type="button"
            onClick={() => setSpeed(demo.speed === 4 ? 1 : demo.speed * 2)}
            className="num flex h-8 min-w-11 items-center justify-center gap-1 rounded-full px-2 text-[13px] font-bold text-ink-2 hover:bg-tile"
            title="Tempo"
          >
            <FastForward className="h-3.5 w-3.5" /> {demo.speed}×
          </button>
          <button type="button" onClick={skipToEnd} className="flex h-8 w-8 items-center justify-center rounded-full text-ink-2 hover:bg-tile" title="Zum Ende springen">
            <SkipForward className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => {
              resetUi();
              restart();
            }}
            className="flex h-8 w-8 items-center justify-center rounded-full text-ink-2 hover:bg-tile"
            title="Von vorn"
          >
            <RotateCcw className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <span className={`text-[13px] font-semibold ${live === "open" ? "text-ok-ink" : live === "connecting" ? "text-agent-ink" : "text-fail-ink"}`}>
          {live === "open" ? "Backend verbunden" : live === "connecting" ? "verbinde …" : "Backend offline"}
        </span>
      )}
    </div>
  );
}

const MENU: { value: View; label: string; icon: typeof Dumbbell }[] = [
  { value: "werkbank", label: "Werkbank", icon: LayoutDashboard },
  { value: "training", label: "Training", icon: Dumbbell },
  { value: "logbuch", label: "Logbuch", icon: BookOpen },
];

/** Training and Logbuch are not part of the stage flow, so they sit behind a small menu. */
function MoreMenu() {
  const view = useUi((s) => s.view);
  const setView = useUi((s) => s.setView);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", close);
    return () => window.removeEventListener("pointerdown", close);
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`flex h-10 w-10 items-center justify-center rounded-full transition ${open || view !== "werkbank" ? "bg-ink text-white" : "text-ink-2 hover:bg-card"}`}
        title="Mehr"
        aria-label="Mehr Ansichten"
      >
        <Ellipsis className="h-5 w-5" />
      </button>
      {open && (
        <div className="absolute top-12 right-0 z-[90] w-52 animate-rise rounded-[20px] bg-card p-1.5 shadow-[var(--shadow-float)]">
          {MENU.map((m) => (
            <button
              key={m.value}
              type="button"
              onClick={() => {
                setView(m.value);
                setOpen(false);
              }}
              className={`flex h-11 w-full items-center gap-3 rounded-2xl px-3.5 text-[15px] font-semibold ${view === m.value ? "bg-tile text-ink" : "text-ink-2 hover:bg-page-2"}`}
            >
              <m.icon className="h-4.5 w-4.5 text-muted" /> {m.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function TopBar() {
  const setView = useUi((s) => s.setView);
  return (
    <header className="flex h-[72px] shrink-0 items-center gap-5 px-5">
      <button type="button" onClick={() => setView("werkbank")} className="flex shrink-0 items-center gap-3 text-left">
        <Logo />
        <div className="leading-tight">
          <div className="text-[19px] font-bold tracking-[-0.01em]">Bauplan</div>
          <div className="text-[13px] font-medium text-muted">Drohne</div>
        </div>
      </button>
      <div className="flex min-w-0 flex-1 justify-center">
        <MeetingTimeline />
      </div>
      <SourceControls />
      <MoreMenu />
    </header>
  );
}
