// One shared playhead for trajectory replays, so before/after views stay in sync.
import { useEffect, useState } from "react";
import type { TrajectorySample } from "../../events/types";

type Listener = () => void;

export const simClock = {
  t: 0,
  duration: 4,
  playing: true,
  /** Pause at the end before looping, in seconds. */
  hold: 1.2,
  listeners: new Set<Listener>(),
};

let raf = 0;
let last = 0;
let users = 0;
let holdLeft = 0;

function tick(now: number) {
  const dt = last ? Math.min(0.1, (now - last) / 1000) : 0;
  last = now;
  if (simClock.playing) {
    if (simClock.t >= simClock.duration) {
      holdLeft -= dt;
      if (holdLeft <= 0) simClock.t = 0;
    } else {
      simClock.t = Math.min(simClock.duration, simClock.t + dt);
      if (simClock.t >= simClock.duration) holdLeft = simClock.hold;
    }
  }
  simClock.listeners.forEach((l) => l());
  raf = requestAnimationFrame(tick);
}

/** Keeps the clock running while at least one replay view is mounted. */
export function useSimClockDriver(duration: number) {
  useEffect(() => {
    simClock.duration = Math.max(0.5, duration);
    if (simClock.t > simClock.duration) simClock.t = 0;
  }, [duration]);
  useEffect(() => {
    users++;
    if (users === 1) {
      last = 0;
      raf = requestAnimationFrame(tick);
    }
    return () => {
      users--;
      if (users === 0) cancelAnimationFrame(raf);
    };
  }, []);
}

/** React state view of the playhead, throttled to keep re-renders cheap. */
export function useSimTime(hz = 15): { t: number; playing: boolean } {
  const [state, setState] = useState({ t: simClock.t, playing: simClock.playing });
  useEffect(() => {
    let lastEmit = 0;
    const l = () => {
      const now = performance.now();
      if (now - lastEmit < 1000 / hz) return;
      lastEmit = now;
      setState({ t: simClock.t, playing: simClock.playing });
    };
    simClock.listeners.add(l);
    return () => {
      simClock.listeners.delete(l);
    };
  }, [hz]);
  return state;
}

export function setPlaying(playing: boolean) {
  simClock.playing = playing;
  if (playing && simClock.t >= simClock.duration) simClock.t = 0;
}
export function seek(t: number) {
  simClock.t = Math.max(0, Math.min(simClock.duration, t));
}

/** Interpolated [x, y, z] at time t, plus velocity, from a trajectory. */
export function sampleAt(traj: TrajectorySample[], t: number): { p: [number, number, number]; v: [number, number, number] } {
  if (!traj.length) return { p: [0, 0, 0], v: [0, 0, 0] };
  if (t <= traj[0][0]) return { p: [traj[0][1], traj[0][2], traj[0][3]], v: [0, 0, 0] };
  for (let i = 1; i < traj.length; i++) {
    const a = traj[i - 1];
    const b = traj[i];
    if (t <= b[0]) {
      const span = b[0] - a[0] || 1;
      const k = (t - a[0]) / span;
      return {
        p: [a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k, a[3] + (b[3] - a[3]) * k],
        v: [(b[1] - a[1]) / span, (b[2] - a[2]) / span, (b[3] - a[3]) / span],
      };
    }
  }
  const z = traj[traj.length - 1];
  return { p: [z[1], z[2], z[3]], v: [0, 0, 0] };
}
