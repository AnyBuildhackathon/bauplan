// Canvas drawing of one drone rollout frame: a fixed oblique camera, the target
// marker, a ground shadow, the recent trail, and the airframe tilted by its quaternion.
import { DRONE_TARGET } from "../../sim/drone";

export interface DrawStyle {
  color: string;
  ink: string;
  faint: string;
  line: string;
  /** Pixels per metre; derived from the canvas size when omitted. */
  scale?: number;
  big?: boolean;
}

function css(name: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

export function themeColors() {
  return {
    ok: css("--color-ok", "#2ed3ae"),
    fail: css("--color-fail", "#ff5a5f"),
    agent: css("--color-agent", "#ff8a3d"),
    ink: css("--color-ink", "#1f1f1f"),
    faint: css("--color-faint", "#a3a3aa"),
    line: css("--color-line", "#e8e7eb"),
  };
}

const COS = Math.cos(Math.PI / 6);
const SIN = Math.sin(Math.PI / 6);

/** Rotates a body-frame vector by the quaternion (w, x, y, z). */
function rotate(w: number, x: number, y: number, z: number, v: [number, number, number]): [number, number, number] {
  const [vx, vy, vz] = v;
  const tx = 2 * (y * vz - z * vy);
  const ty = 2 * (z * vx - x * vz);
  const tz = 2 * (x * vy - y * vx);
  return [vx + w * tx + (y * tz - z * ty), vy + w * ty + (z * tx - x * tz), vz + w * tz + (x * ty - y * tx)];
}

/**
 * Draws frame `index` of a rollout. Frames are [x, y, z, qw, qx, qy, qz] per entry.
 * `armM` is the arm length in metres, drawn exaggerated so the tilt reads at tile size.
 */
export function drawDroneFrame(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  frames: Float32Array,
  frameSize: number,
  index: number,
  style: DrawStyle,
  armM = 0.036,
) {
  ctx.clearRect(0, 0, w, h);
  const n = Math.floor(frames.length / Math.max(1, frameSize));
  if (n === 0) return;
  const i = Math.max(0, Math.min(n - 1, index));
  // About 1.6 m around the target fills the canvas; the ground sits below it.
  const scale = style.scale ?? Math.min(w / 1.7, h / 1.45);
  const ox = w / 2;
  const oy = h * 0.42 + DRONE_TARGET[2] * scale;
  const project = (x: number, y: number, z: number): [number, number] => [ox + (x - y) * COS * scale, oy - (z + (x + y) * SIN * 0.5) * scale];

  // Ground: a diamond under the target, plus a cross.
  ctx.lineWidth = 1;
  ctx.strokeStyle = style.line;
  ctx.beginPath();
  const g = 0.9;
  const corners: [number, number][] = [project(-g, -g, 0), project(g, -g, 0), project(g, g, 0), project(-g, g, 0)];
  corners.forEach(([px, py], k) => (k ? ctx.lineTo(px, py) : ctx.moveTo(px, py)));
  ctx.closePath();
  ctx.stroke();

  // Target: a ring at hover height, and its pole to the ground.
  const [tx, ty] = project(DRONE_TARGET[0], DRONE_TARGET[1], DRONE_TARGET[2]);
  const [gx, gy] = project(DRONE_TARGET[0], DRONE_TARGET[1], 0);
  ctx.setLineDash([3, 4]);
  ctx.strokeStyle = style.faint;
  ctx.beginPath();
  ctx.moveTo(gx, gy);
  ctx.lineTo(tx, ty);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.beginPath();
  ctx.ellipse(tx, ty, 0.12 * scale, 0.05 * scale, 0, 0, Math.PI * 2);
  ctx.stroke();

  const at = (k: number) => {
    const o = k * frameSize;
    return [frames[o], frames[o + 1], frames[o + 2], frames[o + 3], frames[o + 4], frames[o + 5], frames[o + 6]] as const;
  };
  const [x, y, z, qw, qx, qy, qz] = at(i);

  // Shadow on the ground.
  const [sx, sy] = project(x, y, 0);
  ctx.fillStyle = "rgba(0,0,0,0.10)";
  ctx.beginPath();
  ctx.ellipse(sx, sy, 0.14 * scale, 0.05 * scale, 0, 0, Math.PI * 2);
  ctx.fill();

  // Trail of the last second (20 frames).
  ctx.strokeStyle = style.color;
  ctx.globalAlpha = 0.45;
  ctx.lineWidth = style.big ? 2.5 : 1.5;
  ctx.beginPath();
  for (let k = Math.max(0, i - 20); k <= i; k++) {
    const [ax, ay, az] = at(k);
    const [px, py] = project(ax, ay, az);
    if (k === Math.max(0, i - 20)) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  }
  ctx.stroke();
  ctx.globalAlpha = 1;

  // Airframe: two arms in X and four rotor discs, exaggerated 4x.
  const arm = Math.max(0.12, armM * 4);
  const d = arm / Math.SQRT2;
  const motors: [number, number, number][] = [
    [d, d, 0],
    [d, -d, 0],
    [-d, d, 0],
    [-d, -d, 0],
  ];
  const pts = motors.map((m) => {
    const r = rotate(qw, qx, qy, qz, m);
    return project(x + r[0], y + r[1], z + r[2]);
  });
  const [cx, cy] = project(x, y, z);
  ctx.strokeStyle = style.ink;
  ctx.lineWidth = style.big ? 4 : 2.2;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(pts[0][0], pts[0][1]);
  ctx.lineTo(pts[3][0], pts[3][1]);
  ctx.moveTo(pts[1][0], pts[1][1]);
  ctx.lineTo(pts[2][0], pts[2][1]);
  ctx.stroke();
  const rotor = (style.big ? 0.07 : 0.06) * scale;
  ctx.fillStyle = style.color;
  ctx.globalAlpha = 0.35;
  for (const [px, py] of pts) {
    ctx.beginPath();
    ctx.ellipse(px, py, rotor, rotor * 0.45, 0, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  ctx.fillStyle = style.color;
  ctx.beginPath();
  ctx.arc(cx, cy, style.big ? 6 : 3.5, 0, Math.PI * 2);
  ctx.fill();
}
