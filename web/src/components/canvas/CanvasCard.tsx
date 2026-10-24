// The big canvas in the middle: Modell (live 3D or the Blender render), CAD and
// Simulation, with Bolzen's spoken line at the bottom.
import { useEffect, useState } from "react";
import { Box, Camera, DraftingCompass, Rocket } from "lucide-react";
import { useSession } from "../../events/store";
import { useUi, type CanvasTab, type ModelLook } from "../../lib/ui";
import { MascotHead } from "../mascot/Mascot";
import { Segmented } from "../ui/primitives";
import { CadView } from "./CadView";
import { RenderGallery } from "./RenderGallery";
import { ModelScene } from "./Scenes";
import { SimView } from "./SimView";

const TABS: { value: CanvasTab; label: string; icon: typeof Box }[] = [
  { value: "modell", label: "Modell", icon: Box },
  { value: "cad", label: "CAD", icon: DraftingCompass },
  { value: "simulation", label: "Simulation", icon: Rocket },
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

export function CanvasCard() {
  const tab = useUi((s) => s.tab);
  const setTab = useUi((s) => s.setTab);
  const look = useUi((s) => s.look);
  const setLook = useUi((s) => s.setLook);
  const runs = useSession((s) => s.runs.length);
  const cad = useSession((s) => s.cad);
  const renders = useSession((s) => s.renders.length);
  const badges: Partial<Record<CanvasTab, boolean>> = { cad: !!cad, simulation: runs > 0 };
  const showRender = tab === "modell" && look === "render";

  return (
    <div className="card flex h-full min-h-0 flex-col overflow-hidden">
      <div className="flex shrink-0 items-center gap-3 px-4 pt-3.5 pb-3">
        <Segmented
          value={tab}
          onChange={setTab}
          options={TABS.map((t) => ({
            value: t.value,
            target: `tab:${t.value}`,
            label: (
              <>
                <t.icon className="h-4.5 w-4.5" />
                {t.label}
              </>
            ),
            badge: badges[t.value] ? <span className="h-1.5 w-1.5 rounded-full bg-agent" /> : undefined,
          }))}
        />
        {tab === "modell" && (
          <Segmented<ModelLook>
            size="sm"
            className="ml-auto"
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
      </div>

      <div
        className={`relative mx-3 mb-3 min-h-0 flex-1 overflow-hidden rounded-[22px] ${
          showRender
            ? "bg-[radial-gradient(120%_90%_at_50%_15%,#f4f3f8_0%,#dcdbe5_55%,#c9c7d4_100%)]"
            : "bg-[radial-gradient(110%_80%_at_50%_10%,#ffffff_0%,#f3f2f8_60%,#eae9f1_100%)]"
        }`}
        data-target="canvas viewport"
      >
        {tab === "modell" && (showRender ? <RenderGallery /> : <ModelScene look="modell" />)}
        {tab === "cad" && <CadView />}
        {tab === "simulation" && <SimView />}
        {tab !== "cad" && <SpokenLine lifted={(tab === "simulation" && runs > 0) || (showRender && renders > 1)} />}
      </div>
    </div>
  );
}
