// Lernmoment: "Erklär mir das" for the current step, with the live numbers of
// this build and a one-question check.
import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { STEP_IDS } from "../events/types";
import { STEP_LABELS, useSession } from "../events/store";
import { LESSONS, type Diagram } from "../lib/lessons";
import { fmtEur, fmtNum, fmtRatio } from "../lib/format";
import { useTargets } from "../lib/hooks";
import { useUi } from "../lib/ui";
import { MascotBust, MascotHead } from "../components/mascot/Mascot";
import { TrendChart } from "../components/ui/TrendChart";

const HAND = { fontFamily: "var(--font-hand)", fontWeight: 700 } as const;

function ThrustDiagram() {
  const m = useSession((s) => s.metrics);
  const targets = useTargets();
  const tw = m?.thrust_to_weight ?? 2.16;
  const weightN = (m?.weight_g ?? 194) * 0.00981;
  const thrustN = tw * weightN;
  const max = Math.max(thrustN, weightN * 2.2);
  const bar = (v: number) => (v / max) * 300;
  const ok = tw >= targets.thrust_to_weight.value;
  return (
    <svg viewBox="0 0 560 150" className="h-full w-full">
      {/* side view drone */}
      <g transform="translate(92 86)">
        <rect x="-46" y="-6" width="92" height="10" rx="5" fill="#2b2d33" />
        <rect x="-24" y="-22" width="48" height="16" rx="4" fill={m && m.weight_g > 250 ? "#e2b93b" : "#5b8fe6"} />
        {[-40, 40].map((x) => (
          <g key={x}>
            <rect x={x - 5} y="-14" width="10" height="9" rx="2" fill="#b9bec6" />
            <rect x={x - 22} y="-17" width="44" height="3" rx="1.5" fill="#c9ced6" />
            <path d={`M${x} -24 V-58 M${x - 7} -48 L${x} -58 L${x + 7} -48`} stroke="#2ed3ae" strokeWidth="3" fill="none" strokeLinecap="round" />
          </g>
        ))}
        <path d="M0 8 V44 M-7 34 L0 44 L7 34" stroke="#ff5a5f" strokeWidth="3" fill="none" strokeLinecap="round" />
        <text x="16" y="44" fontSize="20" fill="#dc3439" style={HAND}>
          G
        </text>
        <text x="48" y="-50" fontSize="20" fill="#0b9677" style={HAND}>
          T
        </text>
      </g>
      {/* bars */}
      <g transform="translate(210 40)">
        <text x="0" y="-8" fontSize="14" fontWeight="600" fill="#6f6f76">
          Schub
        </text>
        <rect x="0" y="0" width={bar(thrustN)} height="20" rx="10" fill="#2ed3ae" />
        <text x={bar(thrustN) + 10} y="15" fontSize="15" fontWeight="700" fill="#1f1f1f" className="num">
          {fmtRatio(thrustN)} N
        </text>
        <text x="0" y="50" fontSize="14" fontWeight="600" fill="#6f6f76">
          Gewicht
        </text>
        <rect x="0" y="58" width={bar(weightN)} height="20" rx="10" fill="#ff5a5f" />
        <text x={bar(weightN) + 10} y="73" fontSize="15" fontWeight="700" fill="#1f1f1f" className="num">
          {fmtRatio(weightN)} N
        </text>
        <text x="0" y="104" fontSize="24" fill={ok ? "#0b9677" : "#d9620f"} style={HAND}>
          {ok ? `${fmtRatio(tw)} : 1, genug Reserve` : `nur ${fmtRatio(tw)} : 1`}
        </text>
      </g>
    </svg>
  );
}

function RequirementsDiagram() {
  return (
    <svg viewBox="0 0 560 150" className="h-full w-full">
      <g transform="translate(20 34)">
        <rect width="190" height="62" rx="18" fill="#e8e2ff" />
        <text x="16" y="27" fontSize="15" fontWeight="600" fill="#1f1f1f">
          „Bleib unter 250
        </text>
        <text x="16" y="47" fontSize="15" fontWeight="600" fill="#1f1f1f">
          Gramm …“
        </text>
      </g>
      <path d="M222 65 H272 M262 57 L272 65 L262 73" stroke="#ff8a3d" strokeWidth="3" fill="none" strokeLinecap="round" />
      <g transform="translate(284 42)">
        <rect width="108" height="46" rx="23" fill="#fff" stroke="#e8e7eb" strokeWidth="2" />
        <text x="54" y="30" textAnchor="middle" fontSize="19" fontWeight="800" fill="#1f1f1f" className="num">
          ≤ 250 g
        </text>
      </g>
      <path d="M404 65 H448 M438 57 L448 65 L438 73" stroke="#ff8a3d" strokeWidth="3" fill="none" strokeLinecap="round" />
      <g transform="translate(482 65)">
        <circle r="24" fill="#2ed3ae" />
        <path d="M-10 1 l7 7 l13 -15" stroke="white" strokeWidth="4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </g>
      <text x="300" y="128" textAnchor="middle" fontSize="22" fill="#d9620f" style={HAND}>
        Satz → Zahl → Test
      </text>
    </svg>
  );
}

function FrameDiagram() {
  return (
    <svg viewBox="0 0 560 150" className="h-full w-full">
      <g transform="translate(150 75)">
        {[
          [-1, -1],
          [1, -1],
          [-1, 1],
          [1, 1],
        ].map(([x, y]) => (
          <g key={`${x}${y}`}>
            <path d={`M0 0 L${x * 50} ${y * 50}`} stroke="#2b2d33" strokeWidth="8" strokeLinecap="round" />
            <circle cx={x * 50} cy={y * 50} r="10" fill="#b9bec6" />
          </g>
        ))}
        <rect x="-16" y="-14" width="32" height="28" rx="6" fill="#2b2d33" />
      </g>
      <path d="M220 32 L210 22 M220 32 L196 40" stroke="#ff8a3d" strokeWidth="2.5" fill="none" strokeLinecap="round" />
      <text x="232" y="38" fontSize="22" fill="#d9620f" style={HAND}>
        Armlänge = 90 mm
      </text>
      <text x="232" y="80" fontSize="22" fill="#d9620f" style={HAND}>
        Stärke = 4 mm
      </text>
      <text x="232" y="122" fontSize="22" fill="#d9620f" style={HAND}>
        Abstand = 127 mm
      </text>
      <text x="420" y="80" fontSize="15" fontWeight="600" fill="#6f6f76">
        → frame.py → STL
      </text>
    </svg>
  );
}

function RenderDiagram() {
  const box = (x: number, label: string, fill: string) => (
    <g transform={`translate(${x} 45)`}>
      <rect width="110" height="56" rx="18" fill={fill} />
      <text x="55" y="34" textAnchor="middle" fontSize="16" fontWeight="700" fill="#1f1f1f">
        {label}
      </text>
    </g>
  );
  return (
    <svg viewBox="0 0 560 150" className="h-full w-full">
      {box(10, "Modell", "#f2f2f5")}
      <text x="132" y="80" fontSize="22" fill="#6f6f76" fontWeight="700">
        +
      </text>
      {box(150, "Licht", "#fff1e6")}
      <text x="272" y="80" fontSize="22" fill="#6f6f76" fontWeight="700">
        +
      </text>
      {box(290, "Material", "#e8e2ff")}
      <path d="M410 73 H440 M432 65 L440 73 L432 81" stroke="#ff8a3d" strokeWidth="3" fill="none" strokeLinecap="round" />
      {box(448, "Bild", "#e2f8f1")}
    </svg>
  );
}

function RewardDiagram() {
  const training = useSession((s) => s.training);
  const curve = training?.curve.length
    ? training.curve
    : Array.from({ length: 30 }, (_, i) => [i * 40000, -40 + 180 / (1 + Math.exp(-(i * 40000 - 430000) / 115000))] as [number, number]);
  const max = curve.at(-1)![0] || 1;
  return (
    <div className="flex h-full items-center px-4">
      <TrendChart
        series={[{ points: curve, color: "#ff8a3d", area: true }]}
        width={500}
        height={140}
        xDomain={[0, max]}
        yDomain={[-60, 160]}
        yTicks={[0, 100]}
        formatY={(v) => fmtNum(v)}
      />
    </div>
  );
}

function BudgetDiagram() {
  const bom = useSession((s) => s.bom);
  const targets = useTargets();
  const budget = targets.price_eur.value;
  const items = bom?.items ?? [];
  const total = items.reduce((s, i) => s + i.qty * i.unit_price_eur, 0) || 1;
  const scale = 500 / Math.max(budget, total);
  const colors = ["#2b2d33", "#6fa8ff", "#c8b8f8", "#ff8a3d", "#5b8fe6", "#2ed3ae", "#a3a3aa"];
  let x = 0;
  return (
    <svg viewBox="0 0 560 150" className="h-full w-full">
      <g transform="translate(20 50)">
        {items.length === 0 && <rect width="500" height="30" rx="15" fill="#f2f2f5" />}
        {items.map((it, i) => {
          const w = it.qty * it.unit_price_eur * scale;
          const el = <rect key={it.name} x={x} y="0" width={Math.max(2, w - 2)} height="30" rx="6" fill={colors[i % colors.length]} />;
          x += w;
          return el;
        })}
        <path d={`M${budget * scale} -12 V44`} stroke="#1f1f1f" strokeWidth="2" strokeDasharray="4 4" />
        <text x={budget * scale} y="-18" textAnchor="end" fontSize="14" fontWeight="700" fill="#1f1f1f">
          Budget {fmtEur(budget)}
        </text>
        <text x="0" y="74" fontSize="22" fill="#d9620f" style={HAND}>
          Akku = größter Hebel bei Preis und Gewicht
        </text>
      </g>
    </svg>
  );
}

const DIAGRAMS: Record<Diagram, () => React.JSX.Element> = {
  thrust: ThrustDiagram,
  requirements: RequirementsDiagram,
  frame: FrameDiagram,
  render: RenderDiagram,
  reward: RewardDiagram,
  budget: BudgetDiagram,
};

export function LessonModal() {
  const step = useUi((s) => s.lessonStep);
  const close = useUi((s) => s.closeLesson);
  const markConcept = useUi((s) => s.markConcept);
  const metrics = useSession((s) => s.metrics);
  const [answer, setAnswer] = useState<number | null>(null);

  useEffect(() => setAnswer(null), [step]);
  useEffect(() => {
    if (!step) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [step, close]);

  if (!step) return null;
  const lesson = LESSONS[step];
  const Fig = DIAGRAMS[lesson.diagram];
  const formula = lesson.formula(metrics);
  const n = STEP_IDS.indexOf(step) + 1;
  const correct = answer === lesson.correct;

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-[rgb(30_30_50/0.28)] backdrop-blur-[3px]" onMouseDown={close}>
      <div
        className="relative w-[680px] max-w-[94vw] animate-rise overflow-hidden rounded-[32px] bg-card shadow-[var(--shadow-float)]"
        onMouseDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={`Erklär mir das: ${lesson.concept}`}
      >
        <div className="px-8 pt-7">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-extrabold tracking-[0.08em] text-agent-ink">ERKLÄR MIR DAS</span>
            <span className="rounded-full bg-tile px-2.5 py-0.5 text-[13px] font-semibold text-ink-2">
              Schritt {n} · {STEP_LABELS[step]}
            </span>
            <button onClick={close} className="ml-auto rounded-full p-2 text-muted hover:bg-tile hover:text-ink" aria-label="Schließen">
              <X className="h-5 w-5" />
            </button>
          </div>
          <div className="flex gap-4">
            <div className="min-w-0 flex-1">
              <h2 className="mt-2 text-[38px] leading-[1.05] font-extrabold tracking-[-0.03em]">{lesson.concept}</h2>
              <p className="mt-3 text-[17px] leading-[1.5] text-ink-2">{lesson.body}</p>
            </div>
            <MascotBust state="erklaert" size={132} className="-mr-3 self-end" />
          </div>
        </div>

        <div className="mx-8 mt-3 h-[150px] rounded-[22px] bg-page-2">
          <Fig />
        </div>
        <div className="mx-8 mt-3 flex items-baseline justify-between gap-4">
          <span className="num text-[19px] font-bold text-ink">{formula.left}</span>
          <span className="text-[14px] font-semibold text-muted">{formula.right}</span>
        </div>

        <div className="mt-5 border-t border-line px-8 pt-5 pb-7">
          <div className="eyebrow">Kurzer Check</div>
          <p className="mt-1 text-[19px] leading-snug font-bold">{lesson.question}</p>
          <div className="mt-3 grid grid-cols-3 gap-2.5">
            {lesson.options.map((o, i) => {
              const chosen = answer === i;
              const reveal = answer !== null && i === lesson.correct;
              return (
                <button
                  key={o}
                  type="button"
                  disabled={answer !== null && correct}
                  onClick={() => {
                    setAnswer(i);
                    if (i === lesson.correct) markConcept(step, "verstanden");
                  }}
                  className={`min-h-12 rounded-2xl px-3 py-2.5 text-[15px] font-semibold transition ${
                    reveal && correct
                      ? "bg-ok text-white shadow-[0_8px_18px_-8px_var(--color-ok)]"
                      : chosen
                        ? "bg-fail-soft text-fail-ink ring-2 ring-fail/50"
                        : "bg-tile text-ink-2 hover:bg-track"
                  }`}
                >
                  {reveal && correct ? "✓ " : ""}
                  {o}
                </button>
              );
            })}
          </div>
          {answer !== null && (
            <div className={`mt-3 flex animate-rise items-start gap-2.5 rounded-2xl px-3.5 py-3 ${correct ? "bg-ok-soft" : "bg-fail-soft"}`}>
              <MascotHead size={24} state={correct ? "freut_sich" : "besorgt"} />
              <p className="text-[15px] leading-snug text-ink">{correct ? lesson.right : lesson.wrong}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
