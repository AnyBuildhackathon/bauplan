import { useSource } from "../events/source";
import { BenchSettings } from "./BenchSettings";
import { MeetingTimeline } from "./timeline/MeetingTimeline";
import { StatusDot } from "./ui/primitives";

/** Where the bench gets its events: the live backend and whether Claude or the mock runs it.
 * The recorded run (?demo) shows nothing here; it plays on its own. */
function SourceStatus() {
  const mode = useSource((s) => s.mode);
  const live = useSource((s) => s.live);
  const backend = useSource((s) => s.backend);
  if (mode === "demo") return null;
  return (
    <span
      title={backend === "mock" ? "No Anthropic API key: the backend runs its scripted mock build" : undefined}
      className={`flex items-center gap-2 text-[12px] font-semibold ${live !== "open" ? (live === "connecting" ? "text-agent-ink" : "text-fail-ink") : backend === "mock" ? "text-agent-ink" : "text-ok-ink"}`}
    >
      <StatusDot tone={live === "open" ? "ok" : live === "connecting" ? "agent" : "fail"} pulse={live === "connecting"} />
      {live === "open" ? (backend === "mock" ? "Mock mode" : "Claude live") : live === "connecting" ? "connecting …" : "Backend offline"}
    </span>
  );
}

/** The slim bar over the canvas: the Jamie meetings on the left, the backend status and Settings on the right. */
export function TopBar() {
  return (
    <header className="flex h-[56px] shrink-0 items-center gap-4 border-b border-line px-5">
      <div className="flex min-w-0 flex-1">
        <MeetingTimeline />
      </div>
      <SourceStatus />
      <BenchSettings />
    </header>
  );
}
