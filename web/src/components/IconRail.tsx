// The slim icon rail on the far left: the logo, a new project, and the views. The
// stage flow lives on the Workbench; Training and Logbook stay one click away.
import { BookOpen, Box, Dumbbell, Plus } from "lucide-react";
import { useSession } from "../events/store";
import { useSource } from "../events/source";
import { useUi, type View } from "../lib/ui";
import { MascotHead } from "./mascot/Mascot";
import { Logo } from "./TopBar";

const VIEWS: { value: View; label: string; icon: typeof Box }[] = [
  { value: "werkbank", label: "Workbench", icon: Box },
  { value: "training", label: "Training", icon: Dumbbell },
  { value: "logbuch", label: "Logbook", icon: BookOpen },
];

function RailButton({
  label,
  active = false,
  onClick,
  target,
  children,
}: {
  label: string;
  active?: boolean;
  onClick: () => void;
  target?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-current={active ? "page" : undefined}
      data-target={target}
      className={`flex h-11 w-11 items-center justify-center rounded-[12px] transition ${
        active ? "bg-track text-ink" : "text-ink-2 hover:bg-tile hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}

export function IconRail() {
  const view = useUi((s) => s.view);
  const setView = useUi((s) => s.setView);
  const resetUi = useUi((s) => s.resetUi);
  const mascot = useSession((s) => s.mascot);
  const resetSession = useSource((s) => s.resetSession);
  return (
    <nav className="flex h-full w-16 shrink-0 flex-col items-center justify-between bg-page-2 py-4" aria-label="AnyBuild">
      <div className="flex flex-col items-center gap-1.5">
        <button type="button" onClick={() => setView("werkbank")} title="AnyBuild" aria-label="AnyBuild" className="mb-4">
          <Logo size={38} />
        </button>
        <RailButton
          label="New project"
          target="nav:new"
          onClick={() => {
            resetUi();
            setView("werkbank");
            void resetSession();
          }}
        >
          <Plus className="h-5 w-5" strokeWidth={1.8} />
        </RailButton>
        {VIEWS.map((v) => (
          <RailButton key={v.value} label={v.label} active={view === v.value} onClick={() => setView(v.value)} target={`nav:${v.value}`}>
            <v.icon className="h-5 w-5" strokeWidth={1.8} />
          </RailButton>
        ))}
      </div>
      <MascotHead size={44} state={mascot.state} className="h-10 w-10 rounded-full bg-track" />
    </nav>
  );
}
