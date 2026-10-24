// Canvas drawing of one gripper rollout frame, seen from the side: the palm on its
// lift, the two pads, the part between them, and the slip as a gap to where it should be.
import type { GripperSpec } from "../../sim/gripper";
import type { DrawStyle } from "./drawDrone";

/** Frames are [hand_rise, object_rise, pad_left_x, pad_right_x, object_x] per entry, metres. */
export function drawGripperFrame(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  frames: Float32Array,
  frameSize: number,
  index: number,
  style: DrawStyle,
  spec: GripperSpec | null,
) {
  ctx.clearRect(0, 0, w, h);
  const n = Math.floor(frames.length / Math.max(1, frameSize));
  if (n === 0) return;
  const k = Math.max(0, Math.min(n - 1, index)) * frameSize;
  const [handRise, objRise, padL, padR, objX] = [frames[k], frames[k + 1], frames[k + 2], frames[k + 3], frames[k + 4]];
  const halfW = Math.max(0.005, (spec?.width_mm ?? 66) / 2000);
  // About 0.3 m wide and 0.42 m tall fills the canvas, enough for the full lift; the floor sits near the bottom.
  const scale = Math.min(w / 0.3, h / 0.42);
  const ox = w / 2;
  const floor = h * 0.9;
  const X = (x: number) => ox + x * scale;
  const Z = (z: number) => floor - z * scale;

  ctx.strokeStyle = style.line;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, Z(0));
  ctx.lineTo(w, Z(0));
  ctx.stroke();

  // Where the part would be if it moved with the hand: a dashed outline.
  const objBottom = objRise;
  const handBottom = handRise;
  ctx.setLineDash([3, 4]);
  ctx.strokeStyle = style.faint;
  ctx.strokeRect(X(-halfW), Z(handBottom + 0.12), halfW * 2 * scale, 0.12 * scale);
  ctx.setLineDash([]);

  // The part.
  ctx.fillStyle = style.color;
  ctx.globalAlpha = 0.28;
  ctx.fillRect(X(objX - halfW), Z(objBottom + 0.12), halfW * 2 * scale, 0.12 * scale);
  ctx.globalAlpha = 1;
  ctx.strokeStyle = style.color;
  ctx.lineWidth = style.big ? 2.5 : 1.5;
  ctx.strokeRect(X(objX - halfW), Z(objBottom + 0.12), halfW * 2 * scale, 0.12 * scale);

  // Palm and the lift rod above it.
  const palmZ = 0.08 + handRise + 0.05;
  ctx.strokeStyle = style.ink;
  ctx.lineWidth = style.big ? 3 : 2;
  ctx.beginPath();
  ctx.moveTo(X(0), Z(palmZ));
  ctx.lineTo(X(0), 0);
  ctx.stroke();
  ctx.fillStyle = style.ink;
  const palmHalf = halfW + 0.03;
  ctx.fillRect(X(-palmHalf), Z(palmZ + 0.004), palmHalf * 2 * scale, Math.max(2, 0.008 * scale));

  // Fingers from the palm down to the pads.
  const padZ = 0.08 + handRise;
  for (const x of [padL, padR]) {
    ctx.beginPath();
    ctx.moveTo(X(x), Z(palmZ));
    ctx.lineTo(X(x), Z(padZ + 0.02));
    ctx.stroke();
    ctx.fillRect(X(x) - 0.003 * scale, Z(padZ + 0.02), 0.006 * scale, 0.04 * scale);
  }
}
