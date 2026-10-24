// The big canvas in the middle: Modell (live 3D or the Blender render), CAD,
// Simulation and the agent team, with Bolzen's spoken line at the bottom.
import { useEffect, useState } from "react";
import { Box, Boxes, Camera, Cloud, DraftingCompass, Network, Play, Rocket } from "lucide-react";
import { useSource } from "../../events/source";
import { useSession } from "../../events/store";
import { useUi, type CanvasTab, type ModelLook } from "../../lib/ui";
import { MascotFull } from "../mascot/Mascot";
import { useSpeech } from "../../lib/speech";
import { Segmented } from "../ui/primitives";
import { assetUrl } from "../../lib/api";
import { fmtEur } from "../../lib/format";
import { CadScene, CadView } from "./CadView";
import { CompareView } from "./CompareView";
import { ExplodeSlider, PartCard } from "./ExplodeControls";
import { RenderGallery } from "./RenderGallery";
import { ModelScene } from "./Scenes";
import { SimView } from "./SimView";
import { SketchInset } from "./SketchInset";
import { OmniverseView } from "./OmniverseView";
import { AgentsView } from "../agents/AgentsView";
import { BrowserTraining } from "../training/BrowserTraining";
import { useBrowserTrainingEvent, useSimPane } from "../training/useBrowserTraining";

const TABS: { value: CanvasTab; label: string; icon: typeof Box }[] = [
  { value: "modell", label: "Model", icon: Box },
  { value: "cad", label: "CAD", icon: DraftingCompass },
  { value: "simulation", label: "Simulation", icon: Rocket },
  { value: "omniverse", label: "Omniverse", icon: Cloud },
  { value: "agents", label: "Agents", icon: Network },
];

/** Bolzen's current line, as a caption at the bottom of the canvas, with his full figure in the corner while he talks. */
function SpokenLine({ lifted, overSlider }: { lifted: boolean; overSlider: boolean }) {
  const mascot = useSession((s) => s.mascot);
  const speaking = useSpeech((s) => s.speaking);
  const figureOn = useUi((s) => s.display.mascot);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!mascot.say) return setVisible(false);
    const age = Date.now() - mascot.at;
    if (age > 12000) return setVisible(false);
    setVisible(true);
    const id = setTimeout(() => setVisible(false), 12000 - age);
    return () => clearTimeout(id);
  }, [mascot]);
  const figure = figureOn && (visible || speaking || mascot.state === "erklaert");
  return (
    <>
      {figure && (
        <div className={`pointer-events-none absolute right-4 z-10 animate-rise ${lifted ? "bottom-[150px]" : "bottom-2"}`}>
          <MascotFull state={mascot.state} height={150} />
        </div>
      )}
      {visible && (
        <div
          key={mascot.at}
          className={`pointer-events-none absolute left-1/2 z-10 ${lifted ? "bottom-[112px]" : overSlider ? "bottom-[68px]" : "bottom-5"} flex w-max ${figure ? "max-w-[calc(100%-280px)]" : "max-w-[86%]"} -translate-x-1/2 animate-rise items-center rounded-[24px] bg-white/95 px-6 py-3 shadow-[var(--shadow-float)] backdrop-blur`}
        >
          <span className="line-clamp-2 text-[19px] leading-snug font-semibold text-ink">“{mascot.say}”</span>
        </div>
      )}
    </>
  );
}

/** Any product other than the drone: its generated CAD assembly is the model. */
function PartModel() {
  const cad = useSession((s) => s.cad);
  const running = useSession((s) => s.steps.cad.status === "running");
  const url = assetUrl(cad?.glb_url ?? null);
  if (!url) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-8 text-center">
        {/* Mechanic already stands in the chat; the empty canvas shows only what will appear here. */}
        <span className="mb-2 flex h-20 w-20 items-center justify-center rounded-[24px] bg-tile text-faint">
          <Box className="h-9 w-9" strokeWidth={1.6} />
        </span>
        <p className="text-[18px] font-semibold text-ink-2">{running ? "FreeCAD is building the part …" : "No model yet"}</p>
        <p className="max-w-sm text-[15px] text-muted">The assembly shows up here once FreeCAD has built it.</p>
      </div>
    );
  }
  return <CadScene url={url} zUp stage explodable />;
}

export function CanvasCard() {
  const tab = useUi((s) => s.tab);
  const selectTab = useUi((s) => s.selectTab);
  const look = useUi((s) => s.look);
  const setLook = useUi((s) => s.setLook);
  const compare = useUi((s) => s.compare);
  const runs = useSession((s) => s.runs.length);
  const cad = useSession((s) => s.cad);
  const renders = useSession((s) => s.renders.length);
  const product = useSession((s) => s.product);
  const omniverse = useSession((s) => s.omniverse);
  const supportsOmniverse = product === "drone" && !cad?.script_url;
  const tabs = TABS.filter((t) => t.value !== "omniverse" || supportsOmniverse || tab === "omniverse");
  const agentsWorking = useSession((s) => Object.values(s.agents).some((a) => a.status === "running" || a.status === "queued"));
  const badges: Partial<Record<CanvasTab, boolean>> = { cad: !!cad, simulation: runs > 0, omniverse: !!omniverse, agents: agentsWorking };
  const showRender = tab === "modell" && look === "render";
  const pane = useSimPane((s) => s.pane);
  const setPane = useSimPane((s) => s.setPane);
  const trained = useBrowserTrainingEvent() !== null;
  const showTraining = tab === "simulation" && pane === "training";
  const building = useSession((s) => Object.values(s.steps).some((step) => step.status === "running"));
  const bom = useSession((s) => s.bom);
  const setBomOpen = useUi((s) => s.setBomOpen);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-end gap-4 border-b border-line">
        <div className="flex min-w-0 flex-1 items-end gap-5 overflow-x-auto [scrollbar-width:none]" role="tablist">
          {tabs.map((t) => {
            const active = t.value === tab;
            return (
              <button
                key={t.value}
                type="button"
                role="tab"
                aria-selected={active}
                data-target={`tab:${t.value}`}
                data-control={`tab:${t.value === "modell" ? "model" : t.value}`}
                onClick={() => selectTab(t.value)}
                className={`-mb-px flex shrink-0 items-center gap-2 border-b-2 px-0.5 pb-3 text-[15px] whitespace-nowrap transition ${
                  active ? "border-ink font-semibold text-ink" : "border-transparent font-medium text-muted hover:text-ink"
                }`}
              >
                <t.icon className="h-4.5 w-4.5" strokeWidth={1.8} />
                {t.label}
                {badges[t.value] && !active && <span className="h-1.5 w-1.5 rounded-full bg-agent" />}
              </button>
            );
          })}
        </div>
        {tab === "simulation" && !showTraining && runs > 0 && (
          <button
            type="button"
            onClick={() => void useSource.getState().pressControl("run:test")}
            disabled={building}
            data-control="run:test"
            className="mb-1.5 inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full bg-tile px-3 text-[12px] font-semibold text-ink hover:bg-track disabled:text-faint"
          >
            <Play className="h-3.5 w-3.5" fill="currentColor" /> Run test
          </button>
        )}
        {bom && (
          <button
            type="button"
            onClick={() => setBomOpen(true)}
            data-target="bom stueckliste nav:stueckliste"
            data-control="panel:bom"
            title="Open the bill of materials"
            className="mb-1.5 flex h-7 shrink-0 items-center gap-1.5 rounded-full bg-tile px-3 text-[12px] font-semibold text-ink-2 transition hover:bg-track"
          >
            <Boxes className="h-4 w-4" />
            Bill of materials
            <span className="font-label text-[11px] text-muted">{fmtEur(bom.total_eur)}</span>
          </button>
        )}
      </div>

      <div
        className={`relative mt-5 min-h-0 flex-1 overflow-hidden rounded-[20px] ${
          showRender
            ? "bg-[radial-gradient(120%_90%_at_50%_15%,#f4f4f2_0%,#e2e2df_60%,#d6d6d2_100%)]"
            : "bg-[radial-gradient(110%_80%_at_50%_10%,#ffffff_0%,#f3f3f0_60%,#e9e9e5_100%)]"
        }`}
        data-target="canvas viewport"
      >
        <div key={tab} className="h-full min-h-0 motion-safe:animate-[canvas-enter_200ms_ease-out_both]">
        {tab === "simulation" && (
          <Segmented<"hover" | "training">
            size="sm"
            className="absolute top-3 right-3 z-10 bg-white/90 shadow-[var(--shadow-pill)] backdrop-blur"
            value={pane}
            onChange={(pane) => { selectTab("simulation"); setPane(pane); }}
            options={[
              { value: "hover", label: "Hover test", target: "sim:hover" },
              {
                value: "training",
                label: "Training",
                target: "sim:training training",
                badge: trained ? <span className="h-1.5 w-1.5 rounded-full bg-agent" /> : undefined,
              },
            ]}
          />
        )}
        {tab === "modell" && !compare && (
          <Segmented<ModelLook>
            size="sm"
            className="absolute top-3 right-3 z-10 bg-white/90 shadow-[var(--shadow-pill)] backdrop-blur"
            value={look}
            onChange={(look) => { selectTab("modell"); setLook(look); }}
            options={[
              { value: "3d", label: "3D", target: "look:3d", control: "look:3d" },
              {
                value: "render",
                target: "look:render render",
                label: (
                  <>
                    <Camera className="h-4 w-4" /> Render
                  </>
                ),
                badge: renders > 0 ? <span className="h-1.5 w-1.5 rounded-full bg-agent" /> : undefined,
              },
            ]}
          />
        )}
        {tab === "modell" && compare && <CompareView pair={compare} />}
        {tab === "modell" && !compare && (showRender ? <RenderGallery /> : product === "drone" ? <ModelScene look="modell" /> : <PartModel />)}
        {tab === "modell" && !compare && <SketchInset />}
        {tab === "modell" && !compare && !showRender && (product === "drone" || !!cad?.glb_url) && <ExplodeSlider />}
        <PartCard />
        {tab === "cad" && <CadView />}
        {tab === "simulation" && (showTraining ? <BrowserTraining /> : <SimView />)}
        {tab === "omniverse" && <OmniverseView />}
        {tab === "agents" && <AgentsView />}
        {tab !== "cad" && tab !== "omniverse" && tab !== "agents" && !(tab === "modell" && compare) && <SpokenLine lifted={(tab === "simulation" && (runs > 0 || showTraining)) || (showRender && renders > 1)} overSlider={tab === "modell" && !showRender} />}
        </div>
      </div>
    </div>
  );
}
