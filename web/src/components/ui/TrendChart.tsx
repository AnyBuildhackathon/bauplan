// Bevel trend chart: hairline grid with values on the right, a smooth line and a
// glowing dot at its end.
import { useId, type ReactNode } from "react";

export interface Series {
  points: [number, number][];
  color: string;
  dashed?: boolean;
  area?: boolean;
  glow?: boolean;
  label?: string;
}

function smoothPath(pts: [number, number][]): string {
  if (pts.length < 2) return pts.length ? `M${pts[0][0]},${pts[0][1]}` : "";
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1];
    const [x1, y1] = pts[i];
    const mx = (x0 + x1) / 2;
    d += ` C${mx},${y0} ${mx},${y1} ${x1},${y1}`;
  }
  return d;
}

export function TrendChart({
  series,
  width,
  height,
  xDomain,
  yDomain,
  yTicks,
  xTicks,
  formatY = (v) => String(v),
  formatX = (v) => String(v),
  marker,
  className = "",
}: {
  series: Series[];
  width: number;
  height: number;
  xDomain: [number, number];
  yDomain: [number, number];
  yTicks: number[];
  xTicks?: number[];
  formatY?: (v: number) => string;
  formatX?: (v: number) => string;
  /** Optional horizontal target line, e.g. the 1 m hover height. */
  marker?: { y: number; label: ReactNode };
  className?: string;
}) {
  const uid = useId().replace(/:/g, "");
  const padR = 54;
  const padB = xTicks ? 26 : 8;
  const padT = 10;
  const w = width - padR;
  const h = height - padB - padT;
  const sx = (x: number) => ((x - xDomain[0]) / (xDomain[1] - xDomain[0] || 1)) * w;
  const sy = (y: number) => padT + h - ((y - yDomain[0]) / (yDomain[1] - yDomain[0] || 1)) * h;

  // Thin the samples so long curves stay light; the shape is what matters here.
  const project = (pts: [number, number][]) => {
    const step = Math.max(1, Math.floor(pts.length / 160));
    const out: [number, number][] = [];
    for (let i = 0; i < pts.length; i += step) out.push([sx(pts[i][0]), sy(pts[i][1])]);
    if (pts.length && (pts.length - 1) % step !== 0) {
      const last = pts[pts.length - 1];
      out.push([sx(last[0]), sy(last[1])]);
    }
    return out;
  };

  return (
    <svg width={width} height={height} className={`block overflow-visible ${className}`} role="img">
      <defs>
        {series.map((s, i) => (
          <linearGradient key={i} id={`${uid}-a${i}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={s.color} stopOpacity="0.22" />
            <stop offset="1" stopColor={s.color} stopOpacity="0" />
          </linearGradient>
        ))}
      </defs>
      {yTicks.map((t) => (
        <g key={t}>
          <line x1={0} x2={w} y1={sy(t)} y2={sy(t)} stroke="var(--color-line)" strokeWidth={1} />
          <text x={w + 18} y={sy(t) + 4.5} fontSize={13} fill="var(--color-faint)" className="num">
            {formatY(t)}
          </text>
        </g>
      ))}
      {xTicks?.map((t) => (
        <text key={t} x={sx(t)} y={height - 6} fontSize={13} fill="var(--color-muted)" textAnchor="middle" className="num">
          {formatX(t)}
        </text>
      ))}
      {marker && (
        <g>
          <line
            x1={0}
            x2={w}
            y1={sy(marker.y)}
            y2={sy(marker.y)}
            stroke="var(--color-ink)"
            strokeOpacity={0.35}
            strokeWidth={1.5}
            strokeDasharray="4 5"
          />
        </g>
      )}
      {series.map((s, i) => {
        const pts = project(s.points);
        if (!pts.length) return null;
        const d = smoothPath(pts);
        const last = pts[pts.length - 1];
        return (
          <g key={i}>
            {s.area && (
              <path d={`${d} L${last[0]},${padT + h} L${pts[0][0]},${padT + h} Z`} fill={`url(#${uid}-a${i})`} stroke="none" />
            )}
            <path
              d={d}
              fill="none"
              stroke={s.color}
              strokeWidth={3}
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeDasharray={s.dashed ? "2 6" : undefined}
            />
            {s.glow !== false && (
              <g style={{ color: s.color }}>
                <circle cx={last[0]} cy={last[1]} r={13} fill={s.color} opacity={0.18} />
                <circle cx={last[0]} cy={last[1]} r={7} fill={s.color} stroke="white" strokeWidth={2.5} />
              </g>
            )}
          </g>
        );
      })}
    </svg>
  );
}
