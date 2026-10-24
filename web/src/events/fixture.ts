// The demo replays a recorded backend run (agent/scripts/record_demo.py writes
// recording.json and copies its CAD parts and renders to public/demo/run/), so every
// number in ?demo is the backend's own. This file only adds the pacing.
import recording from "./recording.json";
import { parseEvent, type AgentEvent } from "./types";

export interface FixtureItem {
  /** Milliseconds to wait after the previous item, at 1x speed. */
  delay: number;
  event: AgentEvent;
  /** Named seek points the UI can jump to (for example "review"). */
  marker?: string;
}

const SLOW_TOOLS = new Set(["cad_frame", "blender_render", "simulate_drone"]);

/** How long the previous event stays on screen before this one arrives. */
function pause(ev: AgentEvent): number {
  switch (ev.type) {
    case "chat":
      return ev.role === "user" ? 900 : Math.min(4200, 900 + ev.text.length * 22);
    case "tool":
      if (ev.status === "running") return 250;
      return SLOW_TOOLS.has(ev.name) ? 1600 : ev.status === "connected" || ev.status === "offline" ? 0 : 700;
    case "step":
    case "meeting":
      return 150;
    case "mascot":
      return 300;
    case "requirement":
      return 350;
    case "metrics":
    case "bom":
    case "tasks":
      return 500;
    case "sim":
      return 1200;
    case "part":
      return ev.warnings.length ? 900 : 600;
    case "jamie":
      return 500;
    case "question":
      return ev.status === "answered" ? 4500 : 700;
    case "version":
      return 900;
    case "point":
      return 500;
    case "draw":
      return 450;
    default:
      return 300;
  }
}

function build(): FixtureItem[] {
  const events = (recording as unknown[]).map((raw) => parseEvent(JSON.stringify(raw))).filter((e): e is AgentEvent => e !== null);
  const start = events.findIndex((e) => e.type === "jamie" && e.action === "meeting_ended");
  let fails = 0;
  let versions = 0;
  return events.map((event, i) => {
    // Everything before the kickoff ends (tools, steps, the timeline) is the start screen.
    if (start < 0 || i < start) return { delay: 0, event };
    let marker: string | undefined;
    let delay = i === start ? 900 : pause(event);
    if (i === start) marker = "start";
    if (event.type === "sim" && event.result === "fail" && fails++ === 0) marker = "fail";
    if (event.type === "meeting" && event.status === "live") {
      marker = "review";
      delay = 3500;
    }
    if (event.type === "version" && ++versions === 2) marker = "v2";
    return { delay, event, marker };
  });
}

export const DEMO_FIXTURE: FixtureItem[] = build();
