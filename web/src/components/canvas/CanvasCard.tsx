// The big canvas in the middle: Modell (live 3D or the Blender render), CAD and
// Simulation, with Bolzen's spoken line at the bottom.
import { useEffect, useState } from "react";
import { Box, Camera, Cloud, DraftingCompass, Rocket } from "lucide-react";
import { useSession } from "../../events/store";
import { useUi, type CanvasTab, type ModelLook } from "../../lib/ui";
import { MascotHead } from "../mascot/Mascot";
import { Segmented } from "../ui/primitives";
import { assetUrl } from "../../lib/api";
import { CadScene, CadView } from "./CadView";
import { CompareView } from "./CompareView";
import { RenderGallery } from "./RenderGallery";
import { ModelScene } from "./Scenes";
import { SimView } from "./SimView";
import { OmniverseView } from "./OmniverseView";
import { BrowserTraining } from "../training/BrowserTraining";
import { useBrowserTrainingEvent, useSimPane } from "../training/useBrowserTraining";

const TABS: { value: CanvasTab; label: string; icon: typeof Box }[] = [
  { value: "modell", label: "Model", icon: Box },
  { value: "cad", label: "CAD", icon: DraftingCompass },
  { value: "simulation", label: "Simulation", icon: Rocket },
  { value: "omniverse", label: "Omniverse", icon: Cloud },
];

/** Bolzen's current line, as a caption at the bottom of the canvas. */
function SpokenLine({ lifted }: { lifted: boolean }) {
  const mascot = useSession((s) => s.mascot);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!mascot.say) return setVisible(false);
    const age = Date.now() - mascot.at;
    if (age > 12000) return setVisible(false);
    setVisible(true);
    const id = setTimeout(() => setVisible(false), 12000 - age);
    return () => clearTimeout(id);
  }, [mascot]);
  if (!visible) return null;
  return (
    <div
      key={mascot.at}
      className={`pointer-events-none absolute left-1/2 z-10 ${lifted ? "bottom-[112px]" : "bottom-5"} flex w-max max-w-[86%] -translate-x-1/2 animate-rise items-center gap-3 rounded-[24px] bg-white/95 py-2.5 pr-6 pl-2.5 shadow-[var(--shadow-float)] backdrop-blur`}
    >
      <MascotHead size={44} state={mascot.state} />
      <span className="line-clamp-2 text-[19px] leading-snug font-semibold text-ink">„{mascot.say}“</span>
    </div>
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
        <Box className="h-8 w-8 text-faint" />
        <p className="text-[18px] font-semibold text-ink-2">{running ? "FreeCAD is building the part …" : "No model yet"}</p>
        <p className="max-w-sm text-[15px] text-muted">The assembly shows up here once FreeCAD has built it.</p>
      </div>
    );
  }
  return <CadScene url={url} zUp />;
}

export function CanvasCard() {
  const tab = useUi((s) => s.tab);
  const setTab = useUi((s) => s.setTab);
  const look = useUi((s) => s.look);
  const setLook = useUi((s) => s.setLook);
  const compare = useUi((s) => s.compare);
  const runs = useSession((s) => s.runs.length);
  const cad = useSession((s) => s.cad);
  const renders = useSession((s) => s.renders.length);
  const product = useSession((s) => s.product);
  const omniverse = useSession((s) => s.omniverse);
  const supportsOmniverse = product === "drone" && !cad?.script_url;
  useEffect(() => {
    if (supportsOmniverse && omniverse) setTab("omniverse");
  }, [omniverse, supportsOmniverse, setTab]);
  useEffect(() => {
    if (!supportsOmniverse && tab === "omniverse") setTab("simulation");
  }, [supportsOmniverse, tab, setTab]);
  const tabs = TABS.filter((t) => t.value !== "omniverse" || supportsOmniverse);
  const badges: Partial<Record<CanvasTab, boolean>> = { cad: !!cad, simulation: runs > 0, omniverse: !!omniverse };
  const showRender = tab === "modell" && look === "render";
  const pane = useSimPane((s) => s.pane);
  const setPane = useSimPane((s) => s.setPane);
  const trained = useBrowserTrainingEvent() !== null;
  const showTraining = tab === "simulation" && pane === "training";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-end gap-6 border-b border-line" role="tablist">
        {tabs.map((t) => {
          const active = t.value === tab;
          return (
            <button
              key={t.value}
              type="button"
              role="tab"
              aria-selected={active}
              data-target={`tab:${t.value}`}
              onClick={() => setTab(t.value)}
              className={`-mb-px flex items-center gap-2 border-b-2 px-0.5 pb-3 text-[16px] transition ${
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

      <div
        className={`relative mt-5 min-h-0 flex-1 overflow-hidden rounded-[20px] ${
          showRender
            ? "bg-[radial-gradient(120%_90%_at_50%_15%,#f4f4f2_0%,#e2e2df_60%,#d6d6d2_100%)]"
            : "bg-[radial-gradient(110%_80%_at_50%_10%,#ffffff_0%,#f3f3f0_60%,#e9e9e5_100%)]"
        }`}
        data-target="canvas viewport"
      >
        {tab === "simulation" && (
          <Segmented<"hover" | "training">
            size="sm"
            className="absolute top-3 right-3 z-10 bg-white/90 shadow-[var(--shadow-pill)] backdrop-blur"
            value={pane}
            onChange={setPane}
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
            onChange={setLook}
            options={[
              { value: "3d", label: "3D", target: "look:3d" },
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
        {tab === "cad" && <CadView />}
        {tab === "simulation" && (showTraining ? <BrowserTraining /> : <SimView />)}
        {tab === "omniverse" && supportsOmniverse && <OmniverseView />}
        {tab !== "cad" && tab !== "omniverse" && !(tab === "modell" && compare) && <SpokenLine lifted={(tab === "simulation" && (runs > 0 || showTraining)) || (showRender && renders > 1)} />}
      </div>
    </div>
  );
}
