// Bevel building blocks: big rounded cards, pill buttons and chips, segmented
// filters, metric rings and status dots.
import type { ReactNode } from "react";

export type Tone = "agent" | "ok" | "fail" | "neutral" | "muted";

export const TONE_FILL: Record<Tone, string> = {
  agent: "var(--color-agent)",
  ok: "var(--color-ok)",
  fail: "var(--color-fail)",
  neutral: "var(--color-ink)",
  muted: "var(--color-track)",
};
export const TONE_INK: Record<Tone, string> = {
  agent: "text-agent-ink",
  ok: "text-ok-ink",
  fail: "text-fail-ink",
  neutral: "text-ink",
  muted: "text-muted",
};
const TONE_CHIP: Record<Tone, string> = {
  agent: "bg-agent-soft text-agent-ink",
  ok: "bg-ok-soft text-ok-ink",
  fail: "bg-fail-soft text-fail-ink",
  neutral: "bg-ink text-white",
  muted: "bg-tile text-muted",
};

export function Card({
  children,
  className = "",
  as: As = "section",
  ...rest
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article";
} & React.HTMLAttributes<HTMLElement>) {
  return (
    <As className={`card ${className}`} {...rest}>
      {children}
    </As>
  );
}

export function CardTitle({
  icon,
  children,
  right,
  className = "",
}: {
  icon?: ReactNode;
  children: ReactNode;
  right?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      {icon && <span className="flex h-5 w-5 items-center justify-center text-muted">{icon}</span>}
      <h2 className="text-[17px] font-semibold tracking-[-0.01em] text-ink-2">{children}</h2>
      {right && <div className="ml-auto flex items-center gap-2">{right}</div>}
    </div>
  );
}

export function Chip({ tone = "muted", children, className = "" }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span
      className={`inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full px-3 text-[13px] font-semibold whitespace-nowrap ${TONE_CHIP[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

export function PillButton({
  children,
  onClick,
  variant = "secondary",
  size = "md",
  disabled,
  className = "",
  title,
  ...rest
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost" | "agent";
  size?: "sm" | "md" | "lg";
  disabled?: boolean;
  className?: string;
  title?: string;
} & Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onClick">) {
  const variants = {
    primary: "bg-ink text-white hover:bg-[#333] shadow-[var(--shadow-pill)]",
    agent: "bg-agent text-white hover:brightness-105 shadow-[0_8px_20px_-8px_rgb(255_138_61/0.7)]",
    secondary: "bg-card text-ink hover:bg-page-2 shadow-[var(--shadow-pill)]",
    ghost: "bg-tile text-ink-2 hover:bg-track",
  } as const;
  const sizes = { sm: "h-8 px-3.5 text-[13px]", md: "h-10 px-4.5 text-[15px]", lg: "h-12 px-6 text-[16px]" } as const;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex shrink-0 items-center justify-center gap-2 rounded-full font-semibold whitespace-nowrap transition disabled:cursor-not-allowed disabled:opacity-45 ${variants[variant]} ${sizes[size]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  size = "md",
  className = "",
}: {
  options: { value: T; label: ReactNode; target?: string; control?: string; badge?: ReactNode }[];
  value: T;
  onChange: (v: T) => void;
  size?: "sm" | "md";
  className?: string;
}) {
  const h = size === "sm" ? "h-8 text-[13px] px-3" : "h-9 text-[14px] px-4";
  return (
    <div className={`inline-flex items-center gap-0.5 rounded-full bg-tile p-1 ${className}`} role="tablist">
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="tab"
            aria-selected={active}
            data-target={o.target}
            data-control={o.control}
            onClick={() => onChange(o.value)}
            className={`relative inline-flex items-center gap-1.5 rounded-full font-semibold whitespace-nowrap transition ${h} ${
              active ? "bg-card text-ink shadow-[var(--shadow-pill)]" : "text-muted hover:text-ink-2"
            }`}
          >
            {o.label}
            {o.badge}
          </button>
        );
      })}
    </div>
  );
}

/** Bevel metric ring: a soft track, a colored arc, value in the middle. */
export function Ring({
  fraction,
  tone,
  size = 84,
  stroke = 9,
  children,
}: {
  fraction: number;
  tone: Tone;
  size?: number;
  stroke?: number;
  children?: ReactNode;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const f = Math.max(0, Math.min(1, fraction));
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-tile)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={TONE_FILL[tone]}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${c * f} ${c}`}
          style={{ transition: "stroke-dasharray 700ms cubic-bezier(.2,.8,.2,1), stroke 300ms" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">{children}</div>
    </div>
  );
}

export function StatusDot({ tone, pulse = false, hollow = false }: { tone: Tone; pulse?: boolean; hollow?: boolean }) {
  return (
    <span className="relative inline-flex h-2.5 w-2.5 shrink-0">
      {pulse && (
        <span className="absolute inset-0 animate-ping rounded-full opacity-50" style={{ background: TONE_FILL[tone] }} />
      )}
      <span
        className="relative inline-flex h-2.5 w-2.5 rounded-full"
        style={
          hollow
            ? { boxShadow: `inset 0 0 0 1.5px var(--color-faint)` }
            : { background: TONE_FILL[tone] }
        }
      />
    </span>
  );
}

/** Round check used for steps and requirements: done, failed, running, or open. */
export function CheckCircle({ state, size = 26 }: { state: "ok" | "fail" | "agent" | "open"; size?: number }) {
  if (state === "open") {
    return (
      <span
        className="inline-block shrink-0 rounded-full"
        style={{ width: size, height: size, boxShadow: "inset 0 0 0 2px var(--color-track)" }}
      />
    );
  }
  if (state === "agent") {
    return (
      <span className="relative inline-flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
        <span
          className="absolute inset-0 rounded-full border-[2.5px] border-agent/25 border-t-agent animate-spin-slow"
          aria-hidden
        />
        <span className="h-2 w-2 rounded-full bg-agent" />
      </span>
    );
  }
  const bg = state === "ok" ? "var(--color-ok)" : "var(--color-fail)";
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-full text-white"
      style={{ width: size, height: size, background: bg, boxShadow: `0 4px 10px -4px ${bg}` }}
    >
      {state === "ok" ? (
        <svg width={size * 0.5} height={size * 0.5} viewBox="0 0 12 12" fill="none">
          <path d="M2.5 6.3 5 8.6l4.5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : (
        <svg width={size * 0.42} height={size * 0.42} viewBox="0 0 10 10" fill="none">
          <path d="m2 2 6 6M8 2 2 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      )}
    </span>
  );
}
