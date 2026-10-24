import { FastForward, Pause, Play, RotateCcw, SkipForward } from "lucide-react";
import { useSource } from "../events/source";
import { useUi } from "../lib/ui";
import { BenchSettings } from "./BenchSettings";
import { MeetingTimeline } from "./timeline/MeetingTimeline";
import { StatusDot } from "./ui/primitives";

/** The app logo: Mechanic leaning on the workbench cube, cropped to his head and the cube corner so it reads at small sizes. */
export function Logo({ size = 40 }: { size?: number }) {
  return (
    <img
      src={`${import.meta.env.BASE_URL}logo-mark.webp`}
      width={size}
      height={size}
      alt=""
      draggable={false}
      className="shrink-0 rounded-[12px] shadow-[0_0_0_1px_rgb(26_26_24_/_0.06)] select-none"
    />
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
        <div className="flex items-center gap-1 rounded-full bg-tile p-1" title="Playback of the recorded drone run; it only appears without a live backend">
          <button
            type="button"
            onClick={demo.playing ? pause : play}
            className="flex h-7 items-center gap-1.5 rounded-full bg-ink pr-3 pl-2.5 text-[12px] font-semibold text-white"
            title={demo.playing ? "Pause" : "Play"}
          >
            {demo.playing ? <Pause className="h-3.5 w-3.5" fill="currentColor" /> : <Play className="h-3.5 w-3.5" fill="currentColor" />}
            {demo.playing ? "Pause" : ended ? "Replay recording" : demo.started ? "Resume" : "Play recording"}
          </button>
          <button
            type="button"
            onClick={() => setSpeed(demo.speed === 4 ? 1 : demo.speed * 2)}
            className="num flex h-7 min-w-10 items-center justify-center gap-1 rounded-full px-2 text-[12px] font-semibold text-ink-2 hover:bg-track"
            title="Playback speed"
          >
            <FastForward className="h-3.5 w-3.5" /> {demo.speed}×
          </button>
          <button type="button" onClick={skipToEnd} className="flex h-7 w-7 items-center justify-center rounded-full text-ink-2 hover:bg-track" title="Jump to the end">
            <SkipForward className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => {
              resetUi();
              restart();
            }}
            className="flex h-7 w-7 items-center justify-center rounded-full text-ink-2 hover:bg-track"
            title="Restart the recording"
          >
            <RotateCcw className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <span
          title={backend === "mock" ? "No Anthropic API key: the backend runs its scripted mock build" : undefined}
          className={`flex items-center gap-2 text-[12px] font-semibold ${live !== "open" ? (live === "connecting" ? "text-agent-ink" : "text-fail-ink") : backend === "mock" ? "text-agent-ink" : "text-ok-ink"}`}>
          <StatusDot tone={live === "open" ? "ok" : live === "connecting" ? "agent" : "fail"} pulse={live === "connecting"} />
          {live === "open" ? (backend === "mock" ? "Mock mode" : "Claude live") : live === "connecting" ? "connecting …" : "Backend offline"}
        </span>
      )}
    </div>
  );
}

/** The slim bar over the canvas: the Jamie meetings on the left, the run controls on the right. */
export function TopBar() {
  return (
    <header className="flex h-[56px] shrink-0 items-center gap-4 border-b border-line px-5">
      <div className="flex min-w-0 flex-1">
        <MeetingTimeline />
      </div>
      <SourceControls />
      <BenchSettings />
    </header>
  );
}
