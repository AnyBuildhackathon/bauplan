// The panel right of the studio and its tab bar on the far right: Mechanic's chat, the
// versions, the assembly tree, the joints and the checks. The chat stays mounted behind the
// other tabs, so a half-typed message and the scroll position survive a look at the versions.
// Pressing the open tab again closes the panel and gives the studio the room; on a narrow
// screen the bar runs along the bottom, also holds the studio, and the open panel takes the
// studio's place.
import { useState, type ReactNode } from "react";
import { Box, GitCommitVertical, ListChecks, ListTree, Rotate3d, type LucideIcon } from "lucide-react";
import { useSession } from "../../events/store";
import { useUi, type RightTab } from "../../lib/ui";
import SidebarChat from "../chat/SidebarChat";
import { MascotHead } from "../mascot/Mascot";
import { AssemblyTree } from "./AssemblyTree";
import { ChecksTab } from "./ChecksTab";
import { JointsTab } from "./JointsTab";
import { VersionsTab } from "./VersionsTab";

/** The header row every tab but the chat starts with, as tall as the chat's own. */
export function PanelHeader({ title, detail, children }: { title: string; detail?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mx-5 flex h-[56px] shrink-0 items-center gap-3 border-b border-line">
      <div className="min-w-0 flex-1 leading-tight">
        <h2 className="truncate text-[15px] font-semibold text-ink">{title}</h2>
        {detail && <div className="truncate font-label text-[11px] text-muted">{detail}</div>}
      </div>
      {children}
    </div>
  );
}

/** What a tab shows before there is anything to list. */
export function PanelEmpty({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-4 py-10 text-center">
      <span className="mb-3 flex h-14 w-14 items-center justify-center rounded-[18px] bg-tile text-faint">
        <Icon className="h-6 w-6" strokeWidth={1.7} />
      </span>
      <p className="text-[16px] font-semibold text-ink-2">{title}</p>
      <p className="mt-1 max-w-[300px] text-[14px] leading-snug text-muted">{children}</p>
    </div>
  );
}

export function RightPanel() {
  const tab = useUi((s) => s.rightTab);
  const chat = tab === "mechanic";
  return (
    <div className="relative h-full min-h-0 overflow-hidden bg-page" data-target="panel">
      <div className={`absolute inset-0 ${chat ? "" : "invisible"}`} inert={!chat}>
        <SidebarChat />
      </div>
      {!chat && (
        <div className="absolute inset-0 flex min-h-0 flex-col" role="tabpanel" aria-label={TABS.find((t) => t.value === tab)?.label}>
          {tab === "versions" && <VersionsTab />}
          {tab === "assembly" && <AssemblyTree />}
          {tab === "joints" && <JointsTab />}
          {tab === "checks" && <ChecksTab />}
        </div>
      )}
    </div>
  );
}

const TABS: { value: RightTab; label: string; icon: LucideIcon | null; hint: string }[] = [
  { value: "mechanic", label: "Mechanic", icon: null, hint: "Chat with Mechanic" },
  { value: "versions", label: "Versions", icon: GitCommitVertical, hint: "Every build, to compare or restore" },
  { value: "assembly", label: "Assembly", icon: ListTree, hint: "The parts of the model" },
  { value: "joints", label: "Joints", icon: Rotate3d, hint: "The moving parts and their limits" },
  { value: "checks", label: "Checks", icon: ListChecks, hint: "Requirements and tests" },
];

function RailTab({
  label,
  hint,
  active,
  dot,
  onClick,
  target,
  bottom,
  children,
}: {
  label: string;
  hint: string;
  active: boolean;
  dot?: "agent" | "fail" | null;
  onClick: () => void;
  target: string;
  /** In the bottom bar of a narrow screen the tabs share its width. */
  bottom: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      aria-label={label}
      onClick={onClick}
      title={hint}
      data-target={target}
      data-control={target}
      className={`relative flex flex-col items-center justify-center gap-1 rounded-[12px] font-semibold transition ${bottom ? "h-full min-w-0 flex-1 text-[11px]" : "h-[58px] w-[62px] text-[12px]"} ${
        active ? "bg-track text-ink" : "text-ink-2 hover:bg-tile hover:text-ink"
      }`}
    >
      <span className="relative flex h-6 w-6 items-center justify-center">
        {children}
        {dot && <span className={`absolute -top-0.5 -right-1 h-2 w-2 rounded-full ring-2 ring-page-2 ${dot === "fail" ? "bg-fail" : "bg-agent"}`} />}
      </span>
      {label}
    </button>
  );
}

/** True when something arrived after its tab was last open. `at` is when the newest one was applied;
 * a replayed backlog is stamped in the past, so a reload starts with nothing unseen. */
function useUnseen(at: number, open: boolean): boolean {
  const [seen, setSeen] = useState(() => Date.now());
  if (open && at > seen) setSeen(at);
  return !open && at > seen;
}

/** The panel's tabs: a rail on the far right, or on a narrow screen a bar along the bottom that also holds the studio. */
export function RightRail({ narrow = false }: { narrow?: boolean }) {
  const tab = useUi((s) => s.rightTab);
  const open = useUi((s) => s.panelOpen);
  const setRightTab = useUi((s) => s.setRightTab);
  const setPanelOpen = useUi((s) => s.setPanelOpen);
  const mascot = useSession((s) => s.mascot.state);
  const said = useSession((s) => s.chat.findLast((c) => c.kind === "msg" && c.role === "agent")?.at ?? 0);
  const built = useSession((s) => s.chat.findLast((c) => c.kind === "version")?.at ?? 0);
  const failed = useSession((s) => s.requirements.some((r) => r.met === false));
  const unseenChat = useUnseen(said, open && tab === "mechanic");
  const unseenVersions = useUnseen(built, open && tab === "versions");
  const dots: Partial<Record<RightTab, "agent" | "fail" | null>> = {
    mechanic: unseenChat ? "agent" : null,
    versions: unseenVersions ? "agent" : null,
    checks: failed ? "fail" : null,
  };

  return (
    <nav
      className={narrow ? "flex h-16 w-full shrink-0 items-stretch gap-0.5 border-t border-line bg-page-2 px-1.5 py-1.5" : "flex h-full w-[72px] shrink-0 flex-col items-center gap-1 bg-page-2 py-3"}
      aria-label="Panels"
      role="tablist"
      aria-orientation={narrow ? "horizontal" : "vertical"}
    >
      {narrow && (
        <RailTab label="Studio" hint="The model, CAD and tests" active={!open} onClick={() => setPanelOpen(false)} target="rail:studio" bottom>
          <Box className="h-5 w-5" strokeWidth={1.8} />
        </RailTab>
      )}
      {TABS.map((t) => {
        const active = open && tab === t.value;
        return (
          <RailTab
            key={t.value}
            label={t.label}
            hint={active && !narrow ? "Close the panel" : t.hint}
            active={active}
            dot={dots[t.value]}
            target={`rail:${t.value}`}
            bottom={narrow}
            // The open tab closes the panel again, so the studio gets the whole width.
            onClick={() => (active && !narrow ? setPanelOpen(false) : setRightTab(t.value))}
          >
            {t.icon ? <t.icon className="h-5 w-5" strokeWidth={1.8} /> : <MascotHead state={mascot} size={24} className="ring-1 ring-line" />}
          </RailTab>
        );
      })}
    </nav>
  );
}
