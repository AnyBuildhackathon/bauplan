// Stress test result in the chat: the robustness score, one dot per randomized
// world, the worst world replayed in 3D, and Bolzen's sentence on the weak point.
import { useMemo } from "react";
import { ShieldCheck } from "lucide-react";
import { useSession, type Run } from "../../events/store";
import type { StressWorld } from "../../events/types";
import { MascotHead } from "../mascot/Mascot";
import { SimScene } from "../canvas/Scenes";
import { useSimClockDriver } from "../canvas/simClock";
import { RUN_COLOR } from "../canvas/SimView";

const REASON: Record<string, string> = {
  crashed: "touched down",
  drifted: "blown off its spot",
  sagged: "could not hold height",
};

const signed = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(0)} %`;

function describe(w: StressWorld): string {
  return `gust ${w.gust_mps.toFixed(1)} m/s · motors ${signed(w.motor_pct)} · mass ${signed(w.mass_pct)} · noise ${w.noise_cm.toFixed(1)} cm`;
}

function WorstReplay({ run, seq }: { run: Run; seq: number }) {
  useSimClockDriver(run.trajectory.at(-1)?.[0] ?? 5);
  return (
    <div className="relative h-[180px] overflow-hidden rounded-xl bg-[radial-gradient(110%_80%_at_50%_10%,#ffffff_0%,#f3f2f8_60%,#eae9f1_100%)]" key={seq}>
      <SimScene run={run} primary={false} color={RUN_COLOR[run.result]} />
    </div>
  );
}

export function StressCard({ run }: { run: number }) {
  const ev = useSession((s) => s.stress[run]);
  const latest = useSession((s) => Math.max(0, ...Object.keys(s.stress).map(Number)));
  const replay = useMemo<Run | null>(() => {
    if (!ev?.worst) return null;
    return {
      type: "sim",
      run: ev.worst.i,
      result: ev.worst.pass ? "pass" : "fail",
      summary: ev.explanation,
      trajectory: ev.worst.trajectory,
      seq: ev.seq,
      at: ev.at,
    };
  }, [ev]);
  if (!ev) return null;

  const done = ev.status === "done";
  const lost = ev.done - ev.survived;
  const tone = !done ? "text-agent-ink" : lost === 0 ? "text-ok-ink" : ev.survived >= ev.total * 0.9 ? "text-ink" : "text-fail-ink";
  const byIndex = new Map(ev.worlds.map((w) => [w.i, w]));
  const worst = ev.worst;

  return (
    <div className="rounded-2xl bg-tile p-3" data-target="stress">
      <div className="flex items-center gap-2 text-[14px] font-bold text-ink-2">
        <ShieldCheck className="h-4.5 w-4.5 shrink-0" />
        Stress test · {ev.total} randomized worlds
        <span className="ml-auto rounded-full bg-white/80 px-2 py-0.5 text-[12px] font-semibold text-muted">
          {ev.policy === "trained" ? "trained gains" : "default gains"}
        </span>
      </div>

      <div className={`num mt-1.5 text-[26px] leading-tight font-bold ${tone}`}>
        {done ? `Survived ${ev.survived}/${ev.total}` : `Flying world ${ev.done}/${ev.total}…`}
      </div>
      {!done && <div className="num text-[13px] text-muted">{ev.survived} survived so far</div>}

      <div className="mt-2 grid grid-cols-[repeat(25,minmax(0,1fr))] gap-[3px]" aria-label="One dot per world">
        {Array.from({ length: ev.total }, (_, k) => {
          const w = byIndex.get(k + 1);
          const isWorst = done && worst?.i === k + 1;
          return (
            <span
              key={k}
              title={w ? `World ${w.i}: ${w.pass ? "survived" : REASON[w.reason] ?? w.reason} · ${describe(w)}` : `World ${k + 1}`}
              className={`aspect-square rounded-full ${isWorst ? "ring-2 ring-ink ring-offset-1" : ""}`}
              style={{ background: w ? (w.pass ? RUN_COLOR.pass : RUN_COLOR.fail) : "var(--color-track)" }}
            />
          );
        })}
      </div>

      {done && worst && replay && (
        <div className="mt-2.5">
          <div className="mb-1 flex items-baseline gap-2 text-[13px] font-semibold">
            <span className={worst.pass ? "text-ok-ink" : "text-fail-ink"}>
              {worst.pass ? "Closest call" : "Worst failure"} · world {worst.i}
              {!worst.pass && ` · ${REASON[worst.reason] ?? worst.reason}`}
            </span>
          </div>
          {run === latest ? (
            <WorstReplay run={replay} seq={ev.seq} />
          ) : (
            <div className="rounded-xl bg-white/70 px-3 py-2 text-[13px] text-muted">Replay shows on the latest stress test.</div>
          )}
          <div className="num mt-1 text-[12px] text-muted">
            {describe(worst)} · drift {(worst.drift_m * 100).toFixed(0)} cm
          </div>
        </div>
      )}

      {done && ev.explanation && (
        <div className="mt-2.5 flex items-start gap-2 rounded-xl bg-white/80 px-2.5 py-2">
          <MascotHead size={24} state={lost === 0 ? "freut_sich" : "erklaert"} className="shrink-0" />
          <p className="text-[14px] leading-snug font-semibold text-ink">“{ev.explanation}”</p>
        </div>
      )}
    </div>
  );
}
