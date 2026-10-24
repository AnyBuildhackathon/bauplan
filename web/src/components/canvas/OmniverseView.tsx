import { Cloud, Download, LoaderCircle, Play, Wind } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useSession } from "../../events/store";
import { useSource } from "../../events/source";
import { assetUrl } from "../../lib/api";
import { useShownBuild } from "../../lib/hooks";
import { usePartners } from "../../lib/partners";
import { TrendChart } from "../ui/TrendChart";

const METRICS: Record<string, [string, string]> = {
  hover_rmse_m: ["Hover error", "m"], max_tilt_deg: ["Peak tilt", "°"], max_drift_m: ["Lateral drift", "m"],
  min_altitude_m: ["Min. altitude", "m"], assembly_mass_g: ["Assembly mass", "g"],
  total_mass_g: ["Test mass incl. payload", "g"], peak_wind_m_s: ["Peak wind", "m/s"],
  payload_g: ["Added payload", "g"], first_failure_wind_m_s: ["Wind at first failure", "m/s"],
  final_reward: ["Final reward", ""], iterations: ["Iterations", ""], parallel_envs: ["Parallel environments", ""],
};

function conditions(params: Record<string, string | number>) {
  return Object.entries(params).map(([key, value]) => {
    if (key === "wind_m_s") return `${value} m/s wind`;
    if (key === "payload_g") return `${value} g payload`;
    if (key === "duration_s") return `${value} s`;
    if (key === "num_envs") return `${value} parallel environments`;
    if (key === "scenario" || key === "task") return String(value);
    return `${value} ${key.replaceAll("_", " ")}`;
  }).join(" · ");
}

export function OmniverseView() {
  // Without a GPU pod the backend answers with a recorded fixture; its synthetic values
  // are not shown, the tab says calmly that no GPU is connected instead.
  const latest = useSession((s) => s.omniverse);
  const connection = usePartners((s) => s.isaac);
  const product = useSession((s) => s.product);
  const cad = useSession((s) => s.cad);
  const supported = product === "drone" && !cad?.script_url;
  const offline = latest?.source === "recorded";
  const result = offline ? null : latest;
  const { metrics: shownMetrics, version: shownVersion } = useShownBuild();
  const sendPrompt = useSource((s) => s.sendPrompt);
  const [wind, setWind] = useState(6);
  const [payload, setPayload] = useState(10);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [videoError, setVideoError] = useState(false);
  const chart = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(400);
  useEffect(() => {
    if (!chart.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(100, entry.contentRect.width)));
    observer.observe(chart.current);
    return () => observer.disconnect();
  }, [result?.mode]);
  useEffect(() => setVideoError(false), [result?.video_url]);
  const busy = submitting || result?.status === "running";
  const video = assetUrl(result?.video_url);
  const curve = result?.curve ?? [];
  const values = curve.map((p) => p[1]);
  const lastRun = latest ?? connection.last_run;
  const canRun = supported && connection.state === "live" && !busy;

  async function run(text: string) {
    setError("");
    setSubmitting(true);
    try { await sendPrompt(text); }
    catch { setError("The request could not be sent. Try again."); }
    finally { setSubmitting(false); }
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div><p className="text-xs font-bold tracking-widest text-muted uppercase">NVIDIA Omniverse</p>
          <h2 className="mt-1 text-xl font-bold">Test the next possibility.</h2></div>
        <span className="rounded-full bg-tile px-3 py-1.5 text-xs font-semibold text-muted">
          {busy ? "GPU job running" : offline ? "GPU not connected" : result ? "GPU result" : "GPU experiments"}
        </span>
      </div>

      <div className="mb-4 rounded-2xl border border-line bg-white p-3 text-[13px]" data-target="isaac:connection" role="status">
        <p className={`font-semibold ${connection.state === "live" ? "text-ok-ink" : "text-muted"}`}>
          {connection.state === "live" ? "Connected" : connection.state === "mock" ? "Recorded demo" : "Offline"} · {connection.gpu ?? "No GPU detected"}
        </p>
        <p className="mt-1 break-all text-muted">Host: {connection.host ?? "Not configured"}</p>
        <p className="mt-1 text-muted">{connection.detail}</p>
        <p className="mt-1 text-muted">Last run: {lastRun ? `${lastRun.mode} · ${lastRun.status}${lastRun.stage ? ` · ${lastRun.stage}` : ""}` : "No job in this session"}</p>
        {!supported && <p className="mt-2 text-ink-2">Open the drone reference to run Isaac hover tests or reference policy training.</p>}
      </div>

      {shownMetrics && <p className="mb-3 text-xs font-semibold text-muted">
        Displayed assembly{shownVersion ? ` · v${shownVersion.n}` : " · current build"}: {shownMetrics.weight_g.toFixed(1)} g before added payload.
      </p>}

      <div className="mb-4 flex flex-wrap items-end gap-2 rounded-2xl border border-line bg-white p-3">
        <label className="min-w-0 flex-1 text-xs font-semibold text-muted">Wind (m/s)
          <input name="wind_m_s" aria-label="Wind in metres per second" type="number" min="0" max="20" step="0.5" value={wind}
            onChange={(e) => setWind(Number(e.target.value))} className="mt-1 block w-full rounded-lg bg-tile px-3 py-2 text-sm text-ink" /></label>
        <label className="min-w-0 flex-1 text-xs font-semibold text-muted">Payload (g)
          <input name="payload_g" aria-label="Payload in grams" type="number" min="0" max="500" value={payload}
            onChange={(e) => setPayload(Number(e.target.value))} className="mt-1 block w-full rounded-lg bg-tile px-3 py-2 text-sm text-ink" /></label>
        <button type="button" disabled={!canRun || wind < 0 || wind > 20 || payload < 0 || payload > 500}
          onClick={() => void run(`Test the product in Omniverse with ${wind} m/s wind gusts and a ${payload} g payload.`)}
          className="flex h-9 items-center gap-2 rounded-full bg-ink px-4 text-sm font-semibold text-white disabled:opacity-40">
          {busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Wind className="h-4 w-4" />}Run test</button>
      </div>
      <div className="mb-4 flex flex-wrap gap-2">
        <button type="button" disabled={!canRun} onClick={() => void run("Test hover stability in Omniverse.")}
          className="rounded-full bg-white px-3 py-2 text-xs font-semibold text-ink-2 disabled:opacity-40">Hover stability</button>
        <button type="button" disabled={!canRun} onClick={() => void run("Train the reference quadcopter in Isaac Lab.")}
          className="rounded-full bg-white px-3 py-2 text-xs font-semibold text-ink-2 disabled:opacity-40">Train reference policy</button>
      </div>
      {error && <p role="alert" className="mb-3 text-sm text-fail-ink">{error}</p>}
      {!result && (offline ? <div className="flex min-h-48 flex-1 flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-line p-6 text-center" role="status">
        <Cloud className="h-9 w-9 text-faint" /><h3 className="font-semibold">GPU not connected</h3>
        <p className="max-w-sm text-sm leading-relaxed text-muted">Omniverse tests run on a GPU pod. Once one is connected, the video and values of this test appear here. The MuJoCo checks in the Simulation tab work without it.</p>
      </div> : <div className="flex min-h-48 flex-1 flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-line p-6 text-center">
        <Cloud className="h-9 w-9 text-agent" /><h3 className="font-semibold">From CAD to a GPU experiment</h3>
        <p className="max-w-sm text-sm leading-relaxed text-muted">Ask Mechanic to test gusty wind, add a 10 g camera, or train a reference policy. A finished video and values appear here.</p>
      </div>)}
      {result && <>
        <div role="status" className="mb-3 rounded-2xl bg-white p-3 text-sm leading-relaxed text-ink-2">
          {result.detail}
          {result.mode === "train" && <p className="mt-1 text-xs">Isaac-Quadcopter-Direct-v0 · Stock Crazyflie reference, separate from the CAD product.</p>}
        </div>
        {busy && <ol aria-label="Experiment progress" className="mb-3 grid grid-cols-4 gap-1 text-center text-[11px] font-semibold">
          {(["export", "upload", "execute", "download"] as const).map((stage) => <li key={stage}
            className={`rounded-full py-1.5 capitalize ${result.stage === stage ? "bg-agent-soft text-agent-ink" : "bg-white text-muted"}`}>{stage}</li>)}
        </ol>}
        <p className="mb-2 text-xs leading-relaxed text-muted">Requested: {conditions(result.requested)}</p>
        {video && !videoError ? <video key={video} src={video} controls autoPlay muted playsInline loop onError={() => setVideoError(true)}
          aria-label="Completed Omniverse run"
          className="mb-3 aspect-video max-h-56 w-full shrink-0 rounded-2xl bg-ink object-contain" />
          : <div className="mb-3 flex min-h-32 items-center justify-center gap-2 rounded-2xl bg-tile p-4 text-sm text-muted">
            {busy ? <LoaderCircle className="h-5 w-5 animate-spin" /> : <Play className="h-5 w-5" />}
            {busy ? "The recording returns when the GPU run completes." : "Video unavailable. Values and JSON remain available."}</div>}
        <div className="mb-3 grid grid-cols-2 gap-2 xl:grid-cols-3">
          {Object.entries(result.metrics).map(([key, value]) => <div key={key} className="rounded-2xl bg-white px-4 py-3">
            <p className="text-xs text-muted">{METRICS[key]?.[0] ?? key.replaceAll("_", " ")}</p>
            <p className="mt-1 text-xl font-semibold tabular-nums">{Number(value.toFixed(key.endsWith("mass_g") ? 1 : 3))} <span className="text-sm text-muted">{METRICS[key]?.[1]}</span></p>
          </div>)}
        </div>
        {result.passed !== undefined && <p className={`mb-3 text-sm font-semibold ${result.passed ? "text-ok-ink" : "text-fail-ink"}`}>
          {result.passed ? "Hover criteria passed" : "Hover criteria failed"}</p>}
        {curve.length > 0 && <div ref={chart} className="mb-3 min-w-0 rounded-2xl bg-white p-3">
          <p className="mb-2 text-sm font-semibold">Learning curve</p>
          <div className="overflow-hidden"><TrendChart width={width} height={130} series={[{ points: curve, color: "#ff8a3d", area: true }]}
            xDomain={[0, Math.max(curve.at(-1)?.[0] ?? 1, 1)]} yDomain={[Math.min(0, ...values), Math.max(1, ...values)]}
            yTicks={[Math.min(0, ...values), Math.max(1, ...values)]} formatY={(v) => v.toFixed(1)} /></div>
          <p className="text-xs text-muted">Mean reward over training iterations</p>
        </div>}
        {result.json_url && <a href={assetUrl(result.json_url) ?? undefined} target="_blank" rel="noreferrer"
          className="flex items-center gap-2 text-xs font-semibold text-muted"><Download className="h-3.5 w-3.5" />Result JSON</a>}
      </>}
    </div>
  );
}
