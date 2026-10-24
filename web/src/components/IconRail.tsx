// The slim icon rail on the far left: the logo (which starts a new chat), the chat history, and the views. The
// stage flow lives on the Workbench; Library, Community, Training and Logbook stay one click away.
import { BookOpen, Box, Dumbbell, LayoutGrid, Users } from "lucide-react";
import { useSource } from "../events/source";
import { useUi, type View } from "../lib/ui";
import { HistoryMenu } from "./HistoryMenu";
import { Logo } from "./TopBar";

const VIEWS: { value: View; label: string; icon: typeof Box; control: string }[] = [
  { value: "werkbank", label: "Workbench", icon: Box, control: "view:workbench" },
  { value: "library", label: "Library", icon: LayoutGrid, control: "view:library" },
  { value: "community", label: "Community", icon: Users, control: "view:community" },
  { value: "training", label: "Training", icon: Dumbbell, control: "view:training" },
  { value: "logbuch", label: "Logbook", icon: BookOpen, control: "view:logbook" },
];

function RailButton({
  label,
  active = false,
  onClick,
  target,
  control,
  children,
}: {
  label: string;
  active?: boolean;
  onClick: () => void;
  target?: string;
  control?: string;
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
      data-control={control}
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
  const resetSession = useSource((s) => s.resetSession);
  return (
    <nav className="flex h-full w-16 shrink-0 flex-col items-center justify-between bg-page-2 py-4" aria-label="AnyBuild">
      <div className="flex flex-col items-center gap-1.5">
        {/* The logo starts a new chat: a fresh session on the start screen. */}
        <button
          type="button"
          onClick={() => {
            resetUi();
            setView("werkbank");
            void resetSession();
          }}
          title="New chat"
          aria-label="AnyBuild: new chat"
          data-target="logo nav:new"
          className="mb-4"
        >
          <Logo size={52} />
        </button>
        <HistoryMenu />
        {VIEWS.map((v) => (
          <RailButton key={v.value} label={v.label} active={view === v.value} onClick={() => setView(v.value)} target={`nav:${v.value}`} control={v.control}>
            <v.icon className="h-5 w-5" strokeWidth={1.8} />
          </RailButton>
        ))}
      </div>
    </nav>
  );
}
