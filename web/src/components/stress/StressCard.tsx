// Stress test result in the chat: the robustness score, one dot per randomized
// world, the worst world replayed, and Mechanic's sentence on the weak point.
import { useMemo } from "react";
import { ShieldCheck, Wind } from "lucide-react";
import { useSession, type Run } from "../../events/store";
import type { StressEvent, StressWorld } from "../../events/types";
import { MascotHead } from "../mascot/Mascot";
import { GripStage } from "../canvas/GripSimView";
import { SimScene } from "../canvas/Scenes";
import { useSimClockDriver, useSimTime } from "../canvas/simClock";
import { RUN_COLOR } from "../canvas/SimView";

const REASON: Record<string, string> = {
  crashed: "touched down",
  drifted: "blown off its spot",
  sagged: "could not hold height",
  slipped: "object slipped",
  dropped: "object dropped",
};

const POLICY: Record<StressEvent["policy"], string> = {
  trained: "trained gains",
  default: "default gains · not trained yet",
  design: "as designed",
};

const signed = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(0)} %`;

function describe(w: StressWorld, product: StressEvent["product"]): string {
  if (product === "gripper") {
    return `pads ${signed(w.friction_pct ?? 0)} · servo ${signed(w.motor_pct)} · payload ${signed(w.mass_pct)} · shake ${(w.shake_x ?? 1).toFixed(1)}× · jitter ${(w.noise_pct ?? 0).toFixed(0)} %`;
  }
  return `gust ${(w.gust_mps ?? 0).toFixed(1)} m/s · motors ${signed(w.motor_pct)} · mass ${signed(w.mass_pct)} · noise ${(w.noise_cm ?? 0).toFixed(1)} cm`;
}

function outcome(w: StressWorld, product: StressEvent["product"]): string {
  return product === "gripper" ? `slip ${(w.slip_mm ?? 0).toFixed(1)} mm` : `drift ${((w.drift_m ?? 0) * 100).toFixed(0)} cm`;
}

/** The 1-cosine gust the backend blew, as felt at time t. */
function gustAt(w: StressWorld, t: number): number {
  if (!w.gust_mps || !w.gust_len_s || w.gust_start_s === undefined) return 0;
  const k = (t - w.gust_start_s) / w.gust_len_s;
  return k <= 0 || k >= 1 ? 0 : (w.gust_mps * (1 - Math.cos(2 * Math.PI * k))) / 2;
}

const REPLAY_BG = "bg-[radial-gradient(110%_80%_at_50%_10%,#ffffff_0%,#f3f2f8_60%,#eae9f1_100%)]";

function DroneReplay({ run, world }: { run: Run; world: StressWorld }) {
  useSimClockDriver(run.trajectory.at(-1)?.[0] ?? 6);
  const { t } = useSimTime(15);
  const gust = gustAt(world, t);
  return (
    <div className={`relative h-[180px] overflow-hidden rounded-xl ${REPLAY_BG}`}>
      <SimScene run={run} primary={false} color={RUN_COLOR[run.result]} />
      <div className="num pointer-events-none absolute top-2 left-2 flex items-center gap-1.5 text-[12px] font-semibold">
        <span className="rounded-full bg-white/90 px-2 py-0.5 text-muted">t {t.toFixed(1)} s</span>
        {gust > 0.05 && (
          <span className="flex items-center gap-1 rounded-full bg-agent-soft px-2 py-0.5 text-agent-ink">
            <Wind className="h-3.5 w-3.5" /> gust {gust.toFixed(1)} m/s
          </span>
        )}
      </div>
    </div>
  );
}

function GripReplay({ run }: { run: Run }) {
  useSimClockDriver(run.trajectory.at(-1)?.[0] ?? 3.2);
  const { t } = useSimTime(30);
  return (
    <div className={`relative h-[260px] overflow-hidden rounded-xl ${REPLAY_BG}`}>
      <GripStage run={run} t={t} label="Worst" />
    </div>
  );
}

/** The latest finished drone stress run with default gains before `run`, for the before/after line. */
function useDefaultBefore(run: number): StressEvent | null {
  return useSession((s) => {
    let found: StressEvent | null = null;
    for (const [k, e] of Object.entries(s.stress)) {
      if (Number(k) < run && e.product !== "gripper" && e.policy === "default" && e.status === "done" && (!found || e.run > found.run)) found = e;
    }
    return found;
  });
}

export function StressCard({ run }: { run: number }) {
  const ev = useSession((s) => s.stress[run]);
  const before = useDefaultBefore(run);
  const latest = useSession((s) => Math.max(0, ...Object.keys(s.stress).map(Number)));
  const replay = useMemo<Run | null>(() => {
    if (!ev?.worst || ev.worst.trajectory.length < 2) return null;
    return {
      type: "sim",
      kind: ev.product === "gripper" ? "grip" : "hover",
      run: ev.worst.i,
      result: ev.worst.pass ? "pass" : "fail",
      summary: ev.explanation,
      trajectory: ev.worst.trajectory,
      hand: ev.worst.hand,
      object_width_mm: ev.object_width_mm,
      payload_g: ev.payload_g !== undefined ? ev.payload_g * (1 + ev.worst.mass_pct / 100) : undefined,
      force_n: ev.force_n !== undefined ? ev.force_n * (1 + ev.worst.motor_pct / 100) : undefined,
      slip_mm: ev.worst.slip_mm,
      seq: ev.seq,
      at: ev.at,
    };
  }, [ev]);
  if (!ev) return null;

  const product = ev.product ?? "drone";
  const done = ev.status === "done";
  const failed = ev.status === "failed";
  const lost = ev.done - ev.survived;
  const tone = failed ? "text-fail-ink" : !done ? "text-agent-ink" : lost === 0 ? "text-ok-ink" : ev.survived >= ev.total * 0.9 ? "text-ink" : "text-fail-ink";
  const byIndex = new Map(ev.worlds.map((w) => [w.i, w]));
  const worst = ev.worst;
  const verb = product === "gripper" ? "Running" : "Flying";
  const compare = done && ev.policy === "trained" && before ? before : null;
  const gain = compare ? ev.survived - compare.survived : 0;
  const gainLine = compare
    ? gain > 0
      ? ` Training won ${gain} more world${gain === 1 ? "" : "s"}: ${compare.survived}/${compare.total} with default gains, ${ev.survived}/${ev.total} trained.`
      : ` Default gains survived ${compare.survived}/${compare.total}, trained ${ev.survived}/${ev.total}.`
    : "";

  return (
    <div className="rounded-2xl bg-tile p-3" data-target="stress">
      <div className="flex items-center gap-2 text-[14px] font-bold text-ink-2">
        <ShieldCheck className="h-4.5 w-4.5 shrink-0" />
        Stress test · {ev.total} randomized worlds
        <span className="ml-auto shrink-0 rounded-full bg-white/80 px-2 py-0.5 text-[12px] font-semibold text-muted">{POLICY[ev.policy] ?? ev.policy}</span>
      </div>

      <div className={`num mt-1.5 text-[26px] leading-tight font-bold ${tone}`}>
        {done ? `Survived ${ev.survived}/${ev.total}` : failed ? `Stopped after ${ev.done}/${ev.total} worlds` : `${verb} world ${ev.done}/${ev.total}…`}
      </div>
      {!done && !failed && <div className="num text-[13px] text-muted">{ev.survived} survived so far</div>}
      {compare && (
        <div className="num text-[14px] font-semibold text-ink-2" data-target="stress:compare">
          default {compare.survived}/{compare.total} <span className="text-muted">→</span>{" "}
          <span className={gain > 0 ? "text-ok-ink" : "text-ink"}>trained {ev.survived}/{ev.total}</span>
        </div>
      )}
      {done && product === "gripper" && <div className="text-[12px] text-muted">The trained grasp has no stress gains: the gripper is tested as designed.</div>}
      {failed && <div className="text-[13px] text-fail-ink">{ev.explanation}</div>}

      <div className="mt-2 grid grid-cols-[repeat(25,minmax(0,1fr))] gap-[3px]" aria-label="One dot per world">
        {Array.from({ length: ev.total }, (_, k) => {
          const w = byIndex.get(k + 1);
          const isWorst = done && worst?.i === k + 1;
          return (
            <span
              key={k}
              title={w ? `World ${w.i}: ${w.pass ? "survived" : REASON[w.reason] ?? w.reason} · ${describe(w, product)}` : `World ${k + 1}`}
              className={`aspect-square rounded-full ${isWorst ? "ring-2 ring-ink ring-offset-1" : ""}`}
              style={{ background: w ? (w.pass ? RUN_COLOR.pass : RUN_COLOR.fail) : "var(--color-track)" }}
            />
          );
        })}
      </div>

      {done && worst && replay && (
        <div className="mt-2.5">
          <div className="mb-1 text-[13px] font-semibold">
            <span className={worst.pass ? "text-ok-ink" : "text-fail-ink"}>
              {worst.pass ? "Closest call" : "Worst failure"} · world {worst.i}
              {!worst.pass && ` · ${REASON[worst.reason] ?? worst.reason}`}
            </span>
          </div>
          {run !== latest ? (
            <div className="rounded-xl bg-white/70 px-3 py-2 text-[13px] text-muted">Replay shows on the latest stress test.</div>
          ) : product === "gripper" ? (
            <GripReplay run={replay} />
          ) : (
            <DroneReplay run={replay} world={worst} />
          )}
          <div className="num mt-1 text-[12px] text-muted">
            {describe(worst, product)} · {outcome(worst, product)}
          </div>
        </div>
      )}

      {done && ev.explanation && (
        <div className="mt-2.5 flex items-start gap-2 rounded-xl bg-white/80 px-2.5 py-2">
          <MascotHead size={24} state={lost === 0 ? "freut_sich" : "erklaert"} className="shrink-0" />
          <p className="text-[14px] leading-snug font-semibold text-ink">“{ev.explanation}{gainLine}”</p>
        </div>
      )}
    </div>
  );
}
