// Thin Jamie meeting timeline in the top bar: kickoff, reviews, and the drone
// version each meeting produced, as name and version chip; dates sit in the tooltip.
// Clicking a meeting shows that version's numbers.
import { Fragment, useMemo } from "react";
import { History } from "lucide-react";
import { useSession } from "../../events/store";
import { useSource } from "../../events/source";
import type { MeetingEvent, VersionEvent } from "../../events/types";
import { meetingTitle } from "../../lib/derived";
import { useUi } from "../../lib/ui";

const STATUS_TEXT: Record<MeetingEvent["status"], string> = { done: "", live: "live now", next: "planned" };

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function shortDate(iso: string): string {
  const [, month, day] = iso.split("-");
  const m = Number(month);
  const d = Number(day);
  if (!m || !d) return "";
  return `${MONTHS[m - 1]} ${d}`;
}

function hoverText(m: MeetingEvent): string {
  const when = [shortDate(m.date), m.time].filter(Boolean).join(" ");
  return [m.title, when, STATUS_TEXT[m.status], m.tags.length ? `Tags: ${m.tags.join(", ")}` : ""].filter(Boolean).join(" · ");
}

function VersionBadge({ version, active }: { version: VersionEvent | undefined; active: boolean }) {
  if (!version) return null;
  const tone = version.sim === "fail" ? "bg-fail" : "bg-ok";
  return (
    <span className={`num flex h-5 min-w-7 items-center justify-center rounded-full px-1.5 text-[12px] font-semibold text-white ${tone} ${active ? "ring-2 ring-white/30" : ""}`}>
      v{version.n}
    </span>
  );
}

export function MeetingTimeline() {
  const allMeetings = useSession((s) => s.meetings);
  const versions = useSession((s) => s.versions);
  const hasRequirements = useSession((s) => s.requirements.length > 0);
  const log = useSession((s) => s.log);
  const selected = useUi((s) => s.selectedVersion);
  const selectVersion = useUi((s) => s.selectVersion);
  const setVersionsOpen = useUi((s) => s.setVersionsOpen);
  const fallbackTitle = useMemo(() => meetingTitle(log), [log]);
  const meetingWebhook = useSource((s) => s.meetingWebhook);
  const building = useSession((s) => Object.values(s.steps).some((step) => step.status === "running"));

  // Archive meetings feed warnings, they are not stations on the timeline.
  const meetings = allMeetings
    .filter((m) => m.kind !== "archive")
    .slice()
    .sort((a, b) => `${a.date}T${a.time}`.localeCompare(`${b.date}T${b.time}`));
  const shown: MeetingEvent[] = meetings.length
    ? meetings
    : [
        {
          type: "meeting",
          id: "kickoff",
          title: hasRequirements ? fallbackTitle : "Kickoff",
          kind: "kickoff",
          date: "",
          time: "",
          status: hasRequirements ? "done" : "next",
          version: versions[0]?.n ?? null,
          tags: [],
        },
      ];
  const newest = versions.at(-1)?.n ?? null;
  // The next review can be started and ended from here when Jamie's webhook is not wired.
  const nextReview = versions.length > 0 ? shown.find((m) => m.kind === "review" && m.status !== "done") : undefined;
  const current = selected ?? newest;

  return (
    <nav className="flex min-w-0 items-center overflow-hidden" data-target="timeline meetings" aria-label="Jamie meetings">
      <span className="mr-2.5 inline-flex shrink-0 items-center gap-1.5 text-[12px] font-semibold text-jamie">
        <span className="h-2 w-2 rounded-full bg-jamie" /> Jamie
      </span>
      {shown.map((m, i) => {
        const version = versions.find((v) => v.n === m.version) ?? versions.find((v) => v.meeting_id === m.id);
        const active = version !== undefined && version.n === current;
        const clickable = version !== undefined;
        return (
          <Fragment key={m.id}>
            {i > 0 && <span className={`h-px w-3 shrink-0 ${m.status === "next" ? "bg-track" : "bg-faint"}`} />}
            <button
              type="button"
              disabled={!clickable}
              data-target={`meeting:${m.id}`}
              onClick={() => version && selectVersion(version.n === newest ? null : version.n)}
              title={hoverText(m)}
              className={`flex h-8 max-w-[180px] items-center ${m.status === "next" ? "min-w-[60px] shrink" : "min-w-0 shrink-0"} gap-1.5 rounded-full pr-1.5 pl-2.5 transition ${
                active
                  ? "bg-ink text-white"
                  : m.status === "next"
                    ? "bg-transparent text-muted ring-1 ring-track ring-inset"
                    : "bg-tile text-ink hover:bg-track"
              } ${version ? "" : "pr-3"} disabled:cursor-default`}
            >
              {m.status === "live" ? (
                <span className="relative flex h-2.5 w-2.5 shrink-0">
                  <span className="absolute inset-0 animate-ping rounded-full bg-fail opacity-60" />
                  <span className="relative h-2.5 w-2.5 rounded-full bg-fail" />
                </span>
              ) : (
                <span className={`h-2 w-2 shrink-0 rounded-full ${m.status === "next" ? "ring-[1.5px] ring-faint ring-inset" : active ? "bg-white" : "bg-jamie"}`} />
              )}
              <span className="truncate text-[13px] font-semibold">{m.title}</span>
              <VersionBadge version={version} active={active} />
            </button>
            {nextReview?.id === m.id && !building && (
              <button
                type="button"
                data-target="meeting_end"
                data-control="run:review"
                onClick={() => void meetingWebhook(m.status === "live" ? "ended" : "started", m)}
                className={`ml-1.5 h-7 shrink-0 rounded-full px-3 text-[12px] font-bold transition ${
                  m.status === "live" ? "bg-fail text-white hover:brightness-110" : "bg-card text-ink-2 shadow-[var(--shadow-pill)] hover:bg-page-2"
                }`}
                title={m.status === "live" ? "End the meeting: AnyBuild rebuilds" : "Start the meeting"}
              >
                {m.status === "live" ? "End" : "Start"}
              </button>
            )}
          </Fragment>
        );
      })}
      {versions.length > 0 && (
        <button
          type="button"
          data-target="versions"
          data-control="panel:compare"
          onClick={() => setVersionsOpen(true)}
          className="ml-3 inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full bg-card px-3 text-[13px] font-bold text-ink-2 shadow-[var(--shadow-pill)] transition hover:bg-page-2"
          title="Version history"
        >
          <History className="h-4 w-4" /> History
        </button>
      )}
    </nav>
  );
}
