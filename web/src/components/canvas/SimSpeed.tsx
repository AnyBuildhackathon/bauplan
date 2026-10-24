// Playback speed for the trajectory replays (shared simClock), plus slow-motion at the event.
import { useState } from "react";
import { Segmented } from "../ui/primitives";
import { setAutoSlow, setSpeed, simClock } from "./simClock";

const SPEEDS = [
  { value: "0.25", label: "0.25×" },
  { value: "0.5", label: "0.5×" },
  { value: "1", label: "1×" },
];

export function SimSpeed() {
  const [speed, setLocal] = useState(String(simClock.speed));
  const [slow, setSlow] = useState(simClock.autoSlow);
  return (
    <div className="ml-auto mr-3 flex shrink-0 items-center gap-1.5">
      <Segmented
        size="sm"
        className="[&>button]:h-6 [&>button]:px-2 [&>button]:text-[12px]"
        options={SPEEDS}
        value={speed}
        onChange={(v) => {
          setLocal(v);
          setSpeed(Number(v));
        }}
      />
      <button
        type="button"
        onClick={() => {
          setSlow(!slow);
          setAutoSlow(!slow);
        }}
        aria-pressed={slow}
        title="Slow down to 0.25× around the gust or the push"
        className={`h-7 rounded-full px-3 text-[13px] font-semibold whitespace-nowrap ${slow ? "bg-ink text-white" : "bg-tile text-muted hover:text-ink-2"}`}
      >
        Slow-mo
      </button>
    </div>
  );
}
