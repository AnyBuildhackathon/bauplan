// The model stands still at its three-quarter angle. After a new version is built it makes one
// short turn around itself, then stops where it started; a drag or a focused part ends it early.
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import { useSession } from "../../events/store";
import { useUi } from "../../lib/ui";

/** Seconds for the one revolution. */
const TURN_S = 8;

type Controls = {
  autoRotate: boolean;
  autoRotateSpeed: number;
  getAzimuthalAngle: () => number;
  addEventListener: (type: "start", fn: () => void) => void;
  removeEventListener: (type: "start", fn: () => void) => void;
};

export function IntroTurn({ disabled = false }: { disabled?: boolean }) {
  const controls = useThree((s) => s.controls) as unknown as Controls | null;
  const latest = useSession((s) => s.versions.at(-1)?.n ?? 0);
  const focus = useUi((s) => s.focus);
  const seen = useRef(latest);
  // Radians still to turn, and the azimuth of the last frame to measure the turn by.
  const left = useRef(0);
  const last = useRef<number | null>(null);

  useEffect(() => {
    if (latest > seen.current && !disabled) {
      left.current = Math.PI * 2;
      last.current = null;
    }
    seen.current = latest;
  }, [latest, disabled]);

  useEffect(() => {
    left.current = 0;
  }, [focus]);

  useEffect(() => {
    if (!controls) return;
    const stop = () => {
      left.current = 0;
    };
    controls.addEventListener("start", stop);
    return () => controls.removeEventListener("start", stop);
  }, [controls]);

  useFrame(() => {
    if (!controls) return;
    if (left.current <= 0) {
      if (controls.autoRotate) controls.autoRotate = false;
      last.current = null;
      return;
    }
    const azimuth = controls.getAzimuthalAngle();
    if (last.current !== null) {
      let step = Math.abs(azimuth - last.current);
      if (step > Math.PI) step = Math.PI * 2 - step;
      left.current -= step;
    }
    last.current = azimuth;
    controls.autoRotateSpeed = 60 / TURN_S;
    controls.autoRotate = left.current > 0;
  });
  return null;
}
