// Training: the pipeline from meeting to trained policy, and the Isaac Lab run on
// RunPod from `training` events (status, learning curve, video).
import { useEffect, useMemo, useRef, useState } from "react";
import { Cloud, Laptop } from "lucide-react";
import { STEP_IDS, type StepId } from "../events/types";
import { canonicalToolName, formatSteps, STEP_LABELS, useSession } from "../events/store";
import { useSource } from "../events/source";
import { fmtNum } from "../lib/format";
import { assetUrl } from "../lib/api";
import { SimScene } from "../components/canvas/Scenes";
import { RUN_COLOR } from "../components/canvas/SimView";
import { useSimClockDriver } from "../components/canvas/simClock";
import { MascotHead } from "../components/mascot/Mascot";
import { Card, CheckCircle, Chip, PillButton } from "../components/ui/primitives";
import { TrendChart } from "../components/ui/TrendChart";

const WHERE: Record<StepId, { tool: string; place: "cloud" | "local"; where: string }> = {
  meeting: { tool: "Jamie", place: "cloud", where: "Jamie MCP" },
  teile: { tool: "Claude", place: "cloud", where: "Anthropic" },
  cad: { tool: "CadQuery", place: "local", where: "Laptop" },
  render: { tool: "Blender", place: "local", where: "Laptop" },
  simulation: { tool: "MuJoCo", place: "local", where: "Laptop" },
  training: { tool: "Isaac Lab", place: "cloud", where: "RunPod GPU" },
  stueckliste: { tool: "Jamie", place: "cloud", where: "Jamie MCP" },
};

function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ w: 500, h: 260 });
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, size] as const;
}

function Pipeline() {
  const steps = useSession((s) => s.steps);
  return (
    <div className="grid grid-cols-7 gap-3">
      {STEP_IDS.map((id, i) => {
        const st = steps[id];
        const w = WHERE[id];
        const running = st.status === "running";
        return (
          <Card
            key={id}
            data-target={`pipeline:${id}`}
            className={`flex flex-col px-4 pt-3.5 pb-3 ${running ? "ring-2 ring-agent" : ""} ${st.status === "pending" ? "opacity-70" : ""}`}
          >
            <div className="flex items-center justify-between">
              <span className="num text-[13px] font-semibold text-faint">0{i + 1}</span>
              <CheckCircle state={{ pending: "open", running: "agent", done: "ok", failed: "fail" }[st.status] as "open"} size={22} />
            </div>
            <div className="mt-1.5 text-[17px] font-bold">{STEP_LABELS[id]}</div>
            <div className="truncate text-[13px] text-muted">{st.status === "pending" ? w.tool : st.label}</div>
            <div className="mt-3 flex items-center gap-1.5 text-[12px] font-bold tracking-[0.03em] text-muted uppercase">
              {w.place === "cloud" ? <Cloud className="h-3.5 w-3.5" /> : <Laptop className="h-3.5 w-3.5" />}
              {w.place === "cloud" ? "Cloud" : "Lokal"} · {w.where}
            </div>
          </Card>
        );
      })}
    </div>
  );
}

function PolicyVideo() {
  const training = useSession((s) => s.training);
  const runs = useSession((s) => s.runs);
  const lastPass = [...runs].reverse().find((r) => r.result === "pass");
  useSimClockDriver(lastPass?.trajectory.at(-1)?.[0] ?? 4);
  return (
    <Card className="relative flex min-h-0 flex-col overflow-hidden">
      <div className="flex items-center justify-between px-5 pt-4 pb-3">
        <h2 className="text-[17px] font-semibold text-ink-2">Video</h2>
        <span className="text-[13px] font-semibold text-muted">
          {training?.video_url ? "Aufnahme aus Isaac Sim" : lastPass ? `Policy-Replay · Lauf ${lastPass.run}` : "noch keins"}
        </span>
      </div>
      <div className="relative mx-3 mb-3 min-h-0 flex-1 overflow-hidden rounded-[22px] bg-[radial-gradient(110%_80%_at_50%_10%,#ffffff_0%,#f3f2f8_60%,#eae9f1_100%)]">
        {training?.video_url ? (
          <video key={training.video_url} src={assetUrl(training.video_url) ?? undefined} className="h-full w-full bg-[#0d0e12] object-contain" controls autoPlay muted loop playsInline />
        ) : lastPass ? (
          <SimScene run={lastPass} primary={false} color={RUN_COLOR.pass} />
        ) : (
          <div className="flex h-full items-center justify-center px-8 text-center text-[15px] text-muted">
            Das Video kommt von Isaac Sim auf RunPod, sobald die Policy gelernt ist.
          </div>
        )}
      </div>
    </Card>
  );
}

function LearningCurve() {
  const training = useSession((s) => s.training);
  const [ref, { w, h }] = useSize<HTMLDivElement>();
  const curve = training?.curve ?? [];
  const first = curve[0]?.[1];
  const last = curve.at(-1)?.[1];
  const maxStep = Math.max(100_000, curve.at(-1)?.[0] ?? 0);
  return (
    <Card className="flex min-h-0 flex-col px-5 pt-4 pb-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-[17px] font-semibold text-ink-2">Lernkurve</h2>
        <span className="text-[13px] font-semibold text-muted">Belohnung pro Episode</span>
      </div>
      <div className="mt-2 flex items-baseline gap-3">
        <span className="num text-[54px] leading-none font-extrabold tracking-[-0.03em]">{last !== undefined ? fmtNum(last, 1) : "–"}</span>
        {first !== undefined && last !== undefined && curve.length > 1 && (
          <span className="num text-[16px] font-bold text-ok-ink">
            {last - first >= 0 ? "+" : ""}
            {fmtNum(last - first, 1)} seit Start
          </span>
        )}
      </div>
      <div ref={ref} className="mt-4 min-h-0 flex-1">
        {curve.length > 1 ? (
          <TrendChart
            series={[{ points: curve, color: "#ff8a3d", area: true }]}
            width={w}
            height={Math.max(160, h)}
            xDomain={[0, maxStep]}
            yDomain={[-60, 160]}
            yTicks={[-50, 0, 50, 100, 150]}
            xTicks={[0, maxStep / 2, maxStep]}
            formatX={(v) => (v === 0 ? "0" : formatSteps(v))}
            formatY={(v) => fmtNum(v)}
          />
        ) : (
          <div className="flex h-full items-center justify-center rounded-[22px] bg-page-2 text-[15px] text-muted">
            Kurve erscheint, sobald Isaac Lab Schritte meldet.
          </div>
        )}
      </div>
    </Card>
  );
}

/** Task id and environment count as Isaac Lab reported them when the run started. */
function useIsaacRun() {
  const log = useSession((s) => s.log);
  return useMemo(() => {
    let task: string | null = null;
    let envs: string | null = null;
    for (const { ev } of log) {
      if (ev.type !== "tool" || canonicalToolName(ev.name) !== "Isaac Lab") continue;
      task = ev.detail.match(/Isaac-[\w-]+/)?.[0] ?? task;
      envs = ev.detail.match(/(\d[\d.]*)\s*(?:Umgebungen|envs|Drohnen)/i)?.[1] ?? envs;
    }
    return { task, envs };
  }, [log]);
}

function StatusCard() {
  const training = useSession((s) => s.training);
  const tools = useSession((s) => s.tools);
  const isaac = useIsaacRun();
  const mascot = useSession((s) => s.mascot);
  const mode = useSource((s) => s.mode);
  const sendPrompt = useSource((s) => s.sendPrompt);
  const status = training?.status ?? "offline";
  const title = { queued: "Wartet auf GPU", running: "Training läuft", done: "Training fertig", failed: "Abgebrochen", offline: "Noch nicht gestartet" }[status];
  const tone = status === "running" || status === "queued" ? "agent" : status === "done" ? "ok" : status === "failed" ? "fail" : "muted";
  const rows: [string, string][] = [
    ["Wo", `RunPod${tools.RunPod?.detail ? ` · ${tools.RunPod.detail.split("·")[0].trim()}` : ""}`],
    ["Simulator", tools["Isaac Sim"]?.detail || "Isaac Sim"],
    ["Aufgabe", isaac.task ?? "–"],
    ["Umgebungen", isaac.envs ? `${isaac.envs} parallel` : "–"],
    ["Schritte", training ? formatSteps(training.step) : "–"],
    ["Belohnung", training?.curve.length ? fmtNum(training.reward, 1) : "–"],
  ];
  return (
    <Card className="flex min-h-0 flex-col px-5 pt-4 pb-4">
      <div className="flex items-center gap-2">
        <h2 className="text-[17px] font-semibold text-ink-2">{title}</h2>
        <Chip tone={tone} className="ml-auto">
          {status === "running" ? "läuft" : status === "done" ? "fertig" : status === "queued" ? "Warteschlange" : status === "failed" ? "Fehler" : "aus"}
        </Chip>
      </div>
      <div className="relative mt-3 h-2.5 overflow-hidden rounded-full bg-tile">
        {/* The contract carries no step budget, so a running job shows an indeterminate bar. */}
        {status === "done" && <div className="h-full w-full rounded-full bg-ok" />}
        {(status === "running" || status === "queued") && (
          <div className={`absolute inset-y-0 w-2/5 rounded-full bg-agent ${status === "running" ? "animate-indeterminate" : "animate-pulse"}`} />
        )}
      </div>
      <dl className="mt-4 space-y-2.5">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-baseline justify-between gap-3">
            <dt className="text-[14px] text-muted">{k}</dt>
            <dd className="num truncate text-right text-[14px] font-semibold text-ink">{v}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-auto pt-4">
        {mascot.say && (
          <div className="mb-3 flex items-start gap-2.5 rounded-2xl bg-page-2 p-3">
            <MascotHead size={44} state={mascot.state} />
            <p className="text-[15px] leading-snug font-semibold text-ink-2">„{mascot.say}“</p>
          </div>
        )}
        <PillButton
          variant="secondary"
          className="w-full"
          disabled={status !== "running" || mode !== "live"}
          onClick={() => void sendPrompt("Stopp das Training.")}
          title={mode !== "live" ? "Nur im Live-Modus" : undefined}
        >
          Training stoppen
        </PillButton>
      </div>
    </Card>
  );
}

export function TrainingView() {
  return (
    <div className="flex h-full min-h-0 flex-col gap-4 px-5 pb-4">
      <div className="flex items-baseline gap-3 pt-1">
        <h1 className="text-[34px] leading-none font-extrabold tracking-[-0.03em]">Training</h1>
        <span className="text-[17px] text-muted">Isaac Lab auf RunPod · Isaac-Quadcopter-Direct-v0 mit unseren Massen und Schubwerten</span>
      </div>
      <Pipeline />
      <div className="grid min-h-0 flex-1 grid-cols-[1.25fr_1fr_340px] gap-4">
        <PolicyVideo />
        <LearningCurve />
        <StatusCard />
      </div>
    </div>
  );
}
