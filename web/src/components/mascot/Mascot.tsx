// Mechanic, exported as SVG from the Paper file (artboards 0A, 0B, 0C). The mascot
// keeps its own colors; at head size only the antenna tip changes with the state.
import type { MascotState } from "../../events/types";
import hero from "../../assets/mascot/hero.svg";
import ruhig from "../../assets/mascot/ruhig.svg";
import denkt from "../../assets/mascot/denkt.svg";
import erklaert from "../../assets/mascot/erklaert.svg";
import freutSich from "../../assets/mascot/freut_sich.svg";
import besorgt from "../../assets/mascot/besorgt.svg";
import head96 from "../../assets/mascot/head-96.svg?raw";
import head44 from "../../assets/mascot/head-44.svg?raw";
import head24 from "../../assets/mascot/head-24.svg?raw";

const BUSTS: Record<MascotState, string> = {
  ruhig,
  denkt,
  erklaert,
  freut_sich: freutSich,
  besorgt,
};

export const MASCOT_LABEL: Record<MascotState, string> = {
  ruhig: "calm",
  denkt: "thinking",
  erklaert: "explaining",
  freut_sich: "pleased",
  besorgt: "worried",
};

/** Antenna tip colors from the Paper spec (0C): orange, green when happy, red when worried. */
export const TIP_COLOR: Record<MascotState, string> = {
  ruhig: "#FF6B1A",
  denkt: "#FF6B1A",
  erklaert: "#FF6B1A",
  freut_sich: "#3DD68C",
  besorgt: "#FF4D6A",
};

const HEADS = { 96: head96, 44: head44, 24: head24 } as const;
const headCache = new Map<string, string>();

function headUrl(size: 96 | 44 | 24, state: MascotState): string {
  const key = `${size}-${state}`;
  let url = headCache.get(key);
  if (!url) {
    // The antenna tip is the only circle filled with the base orange; recolor just that one.
    const svg = HEADS[size].replace(/(<circle[^>]*fill=")#FF6B1A("[^>]*\/>)/, `$1${TIP_COLOR[state]}$2`);
    url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
    headCache.set(key, url);
  }
  return url;
}

export function MascotHead({
  state = "ruhig",
  size = 44,
  className = "",
}: {
  state?: MascotState;
  size?: 96 | 44 | 24;
  className?: string;
}) {
  return (
    <img
      src={headUrl(size, state)}
      width={size}
      height={size}
      alt={`Mechanic ${MASCOT_LABEL[state]}`}
      className={`shrink-0 select-none ${className}`}
      draggable={false}
    />
  );
}

export function MascotBust({ state, size, className = "" }: { state: MascotState; size: number; className?: string }) {
  return (
    <img
      src={BUSTS[state]}
      width={size}
      height={size}
      alt={`Mechanic ${MASCOT_LABEL[state]}`}
      className={`shrink-0 select-none ${className}`}
      draggable={false}
    />
  );
}

export function MascotHero({ height, className = "" }: { height: number; className?: string }) {
  return (
    <img
      src={hero}
      height={height}
      width={Math.round((height * 483) / 980)}
      alt="Mechanic"
      className={`shrink-0 select-none ${className}`}
      draggable={false}
    />
  );
}
