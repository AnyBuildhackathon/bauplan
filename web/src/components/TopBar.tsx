import { FastForward, Pause, Play, RotateCcw, SkipForward } from "lucide-react";
import { useSource } from "../events/source";
import { useUi } from "../lib/ui";
import { BenchSettings } from "./BenchSettings";
import { MeetingTimeline } from "./timeline/MeetingTimeline";
import { StatusDot } from "./ui/primitives";

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
  const backend = useSource((s) => s.backend);
  const { play, pause, restart, setSpeed, skipToEnd } = useSource.getState();
  const resetUi = useUi((s) => s.resetUi);
  const ended = demo.index >= demo.total;

  return (
    <div className="flex items-center gap-2">
      {mode === "demo" ? (
        <div className="flex items-center gap-1 rounded-full bg-tile p-1">
          <button
            type="button"
            onClick={demo.playing ? pause : play}
            className="flex h-8 items-center gap-1.5 rounded-full bg-ink pr-3 pl-2.5 text-[13px] font-semibold text-white"
            title={demo.playing ? "Pause" : "Play"}
          >
            {demo.playing ? <Pause className="h-3.5 w-3.5" fill="currentColor" /> : <Play className="h-3.5 w-3.5" fill="currentColor" />}
            {demo.playing ? "Pause" : ended ? "Replay" : demo.started ? "Resume" : "Play recording"}
          </button>
          <button
            type="button"
            onClick={() => setSpeed(demo.speed === 4 ? 1 : demo.speed * 2)}
            className="num flex h-8 min-w-11 items-center justify-center gap-1 rounded-full px-2 text-[13px] font-bold text-ink-2 hover:bg-track"
            title="Speed"
          >
            <FastForward className="h-3.5 w-3.5" /> {demo.speed}×
          </button>
          <button type="button" onClick={skipToEnd} className="flex h-8 w-8 items-center justify-center rounded-full text-ink-2 hover:bg-track" title="Jump to the end">
            <SkipForward className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => {
              resetUi();
              restart();
            }}
            className="flex h-8 w-8 items-center justify-center rounded-full text-ink-2 hover:bg-track"
            title="From the start"
          >
            <RotateCcw className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <span className={`flex items-center gap-2 text-[13px] font-semibold ${live !== "open" ? (live === "connecting" ? "text-agent-ink" : "text-fail-ink") : backend === "mock" ? "text-agent-ink" : "text-ok-ink"}`}>
          <StatusDot tone={live === "open" ? "ok" : live === "connecting" ? "agent" : "fail"} pulse={live === "connecting"} />
          {live === "open" ? (backend === "mock" ? "Mock run · no API key" : "Claude live") : live === "connecting" ? "connecting …" : "Backend offline"}
        </span>
      )}
    </div>
  );
}

/** The slim bar over the canvas: the Jamie meetings on the left, the run controls on the right. */
export function TopBar() {
  return (
    <header className="flex h-[60px] shrink-0 items-center gap-5 border-b border-line px-6">
      <div className="flex min-w-0 flex-1">
        <MeetingTimeline />
      </div>
      <SourceControls />
      <BenchSettings />
    </header>
  );
}
