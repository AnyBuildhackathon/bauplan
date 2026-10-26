// The Assembly tab of the right panel: the CAD tree of the latest build. Clicking a row selects
// its part in the studio (it glows and its card opens), the crosshair turns the camera to it and
// the eye hides or shows it. A part hovered or clicked on the model marks its row here.
import { useState } from "react";
import { Box, ChevronRight, Crosshair, Eye, EyeOff, ListTree } from "lucide-react";
import { useSession } from "../../events/store";
import type { CadNode } from "../../events/types";
import { normaliseName, resolveTarget } from "../../lib/targets";
import { useUi } from "../../lib/ui";
import { useExplodeHover } from "../canvas/explode";
import { rowNodes } from "./assembly";
import { PanelEmpty, PanelHeader } from "./RightRail";
import { useStudio } from "./studio";

/** Calls back with the part's spot once the studio shows it, for up to a second (a tab may still be loading). */
function onScreen(target: string, then: (x: number, y: number) => void, tries = 30) {
  const spot = resolveTarget(target);
  if (spot?.kind === "part") return then(spot.x, spot.y);
  if (tries > 0) requestAnimationFrame(() => onScreen(target, then, tries - 1));
}

function Row({ node, depth }: { node: CadNode; depth: number }) {
  const cad = useSession((s) => s.cad);
  const nodes = useStudio((s) => s.nodes);
  const hiddenNames = useStudio((s) => s.hidden);
  const setHidden = useStudio((s) => s.setHidden);
  const hovered = useExplodeHover((s) => s.key);
  const [open, setOpen] = useState(depth < 2);
  // Only the nodes the scene really has: a tree row can name a part the model draws as part of another.
  const names = rowNodes(node, cad).filter((n) => n in nodes);
  const kids = node.children.length > 0;
  const hidden = names.length > 0 && names.every((n) => hiddenNames.includes(n));
  // The deepest row with the hovered part is marked: a part, not the group around it (a part with screws is both).
  const spot = hovered ? normaliseName(hovered) : null;
  const selected = !!spot && names.includes(spot) && !node.children.some((c) => rowNodes(c, cad).includes(spot));
  const [name, ...rest] = node.label.split(" · ");
  const raw = names.length ? nodes[names[0]] : null;

  const select = () => {
    if (!raw) return;
    const ui = useUi.getState();
    if (ui.view !== "werkbank") ui.setView("werkbank");
    if (ui.tab !== "modell" && ui.tab !== "cad") ui.selectTab("modell");
    onScreen(raw, (x, y) => useExplodeHover.getState().pin(raw, name, x, y));
  };
  const focus = () => {
    if (!raw) return;
    const ui = useUi.getState();
    if (ui.tab !== "modell" && ui.tab !== "cad") ui.selectTab("modell");
    ui.setFocus(raw);
  };

  return (
    <li role="treeitem" aria-expanded={kids ? open : undefined} aria-selected={selected}>
      <div
        className={`group flex h-9 items-center gap-1 rounded-[10px] pr-1 transition-colors ${selected ? "bg-accent-soft" : "hover:bg-tile"}`}
        style={{ paddingLeft: 2 + depth * 16 }}
        data-target={raw ? `assembly:${normaliseName(raw)}` : undefined}
      >
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-label={open ? `Collapse ${name}` : `Expand ${name}`}
          tabIndex={kids ? 0 : -1}
          className={`flex h-7 w-5 shrink-0 items-center justify-center rounded-md text-faint hover:text-ink-2 ${kids ? "" : "invisible"}`}
        >
          <ChevronRight className={`h-3.5 w-3.5 transition ${open ? "rotate-90" : ""}`} />
        </button>
        <button
          type="button"
          onClick={select}
          disabled={!raw}
          title={raw ? `Select ${name}` : undefined}
          className="flex h-full min-w-0 flex-1 items-center gap-2 text-left disabled:cursor-default"
        >
          <Box className={`h-4 w-4 shrink-0 ${hidden ? "text-faint" : depth === 0 ? "text-ink" : "text-muted"}`} strokeWidth={1.8} />
          <span className={`min-w-0 shrink truncate text-[14px] ${hidden ? "text-faint" : depth === 0 ? "font-bold text-ink" : "font-medium text-ink-2"}`}>{name}</span>
          {rest.length > 0 && <span className="min-w-0 flex-1 truncate font-label text-[11px] text-muted">{rest.join(" · ")}</span>}
        </button>
        {raw && (
          <>
            <button
              type="button"
              onClick={focus}
              title="Turn the camera to it"
              aria-label={`Turn the camera to ${name}`}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-muted opacity-0 transition group-hover:opacity-100 hover:bg-card hover:text-ink focus-visible:opacity-100"
            >
              <Crosshair className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setHidden(names, !hidden)}
              title={hidden ? "Show" : "Hide"}
              aria-label={hidden ? `Show ${name}` : `Hide ${name}`}
              aria-pressed={hidden}
              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full transition hover:bg-card hover:text-ink focus-visible:opacity-100 ${
                hidden ? "text-faint" : "text-muted opacity-0 group-hover:opacity-100"
              }`}
            >
              {hidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </>
        )}
      </div>
      {kids && open && (
        <ul role="group">
          {node.children.map((c) => (
            <Row key={c.id} node={c} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

/** The parts, counted for the header: rows without children, and a part's standard parts (rows that list their `nodes`) next to it. */
const leaves = (nodes: CadNode[]): number =>
  nodes.reduce((n, c) => {
    const inner = c.children.filter((k) => !k.nodes);
    return n + (inner.length ? leaves(inner) : 1) + c.children.length - inner.length;
  }, 0);

export function AssemblyTree() {
  const cad = useSession((s) => s.cad);
  const running = useSession((s) => s.steps.cad.status === "running");
  const hidden = useStudio((s) => s.hidden);
  const showAll = useStudio((s) => s.showAll);
  const count = cad ? leaves(cad.tree) : 0;
  return (
    <>
      <PanelHeader title="Assembly" detail={cad ? `${count} ${count === 1 ? "part" : "parts"}${hidden.length ? ` · ${hidden.length} hidden` : ""}` : undefined}>
        {hidden.length > 0 && (
          <button type="button" onClick={showAll} className="inline-flex h-8 items-center gap-1.5 rounded-full bg-card px-3 text-[13px] font-bold text-ink-2 shadow-[var(--shadow-pill)] hover:bg-page-2">
            <Eye className="h-4 w-4" /> Show all
          </button>
        )}
      </PanelHeader>
      <div className="scroll-soft min-h-0 flex-1 overflow-y-auto px-4 py-3" data-target="assembly">
        {!cad ? (
          <PanelEmpty icon={ListTree} title={running ? "FreeCAD is building …" : "No assembly yet"}>
            The parts of the model show up here once FreeCAD has built it: select one, turn the camera to it or hide it.
          </PanelEmpty>
        ) : (
          <ul role="tree" aria-label="Assembly">
            {cad.tree.map((n) => (
              <Row key={n.id} node={n} depth={0} />
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
