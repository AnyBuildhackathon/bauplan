// Thin Jamie meeting timeline in the top bar: kickoff, reviews, and the drone
// version each meeting produced. Clicking a meeting shows that version's numbers.
import { Fragment, useMemo } from "react";
import { useSession } from "../../events/store";
import { useSource } from "../../events/source";
import type { MeetingEvent, VersionEvent } from "../../events/types";
import { meetingTitle } from "../../lib/derived";
import { useUi } from "../../lib/ui";

const STATUS_TEXT: Record<MeetingEvent["status"], string> = { done: "", live: "live", next: "planned" };

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function shortDate(iso: string): string {
  const [, month, day] = iso.split("-");
  const m = Number(month);
  const d = Number(day);
  if (!m || !d) return "";
  return `${MONTHS[m - 1]} ${d}`;
}

function VersionBadge({ version, active }: { version: VersionEvent | undefined; active: boolean }) {
  if (!version) return null;
  const tone = version.sim === "fail" ? "bg-fail" : "bg-ok";
  return (
    <span className={`num flex h-7 min-w-9 items-center justify-center rounded-full px-2 text-[14px] font-bold text-white ${tone} ${active ? "ring-2 ring-white/30" : ""}`}>
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
  // The demo recording holds one review, so there the button only exists before it.
  const mode = useSource((s) => s.mode);
  const nextReview =
    versions.length > 0 && (mode === "live" || versions.length === 1)
      ? shown.find((m) => m.kind === "review" && m.status !== "done")
      : undefined;
  const current = selected ?? newest;
  const showDate = new Set(shown.map((m) => m.date).filter(Boolean)).size > 1;

  return (
    <nav className="flex min-w-0 items-center" data-target="timeline meetings" aria-label="Jamie meetings">
      <span className="mr-3 inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full bg-lavender px-3 text-[13px] font-bold text-jamie">
        <span className="h-2 w-2 rounded-full bg-jamie" /> Jamie
      </span>
      {shown.map((m, i) => {
        const version = versions.find((v) => v.n === m.version) ?? versions.find((v) => v.meeting_id === m.id);
        const active = version !== undefined && version.n === current;
        const clickable = version !== undefined;
        return (
          <Fragment key={m.id}>
            {i > 0 && <span className={`h-[2px] w-6 shrink-0 rounded-full ${m.status === "next" ? "bg-track" : "bg-jamie/40"}`} />}
            <button
              type="button"
              disabled={!clickable}
              data-target={`meeting:${m.id}`}
              onClick={() => version && selectVersion(version.n === newest ? null : version.n)}
              title={m.tags.length ? `Tags: ${m.tags.join(", ")}` : m.title}
              className={`flex h-10 min-w-0 shrink items-center gap-2 rounded-full pr-1.5 pl-3.5 transition ${
                active
                  ? "bg-ink text-white shadow-[var(--shadow-pill)]"
                  : m.status === "next"
                    ? "bg-transparent text-faint ring-1 ring-line ring-dashed"
                    : "bg-card text-ink shadow-[var(--shadow-pill)] hover:bg-page-2"
              } ${version ? "" : "pr-3.5"} disabled:cursor-default`}
            >
              {m.status === "live" ? (
                <span className="relative flex h-2.5 w-2.5 shrink-0">
                  <span className="absolute inset-0 animate-ping rounded-full bg-fail opacity-60" />
                  <span className="relative h-2.5 w-2.5 rounded-full bg-fail" />
                </span>
              ) : (
                <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${m.status === "next" ? "ring-[1.5px] ring-faint ring-inset" : active ? "bg-white" : "bg-jamie"}`} />
              )}
              <span className="truncate text-[15px] font-semibold">{m.title}</span>
              {(m.time || m.date || STATUS_TEXT[m.status]) && (
                <span className={`num shrink-0 text-[13px] font-semibold ${active ? "text-white/65" : m.status === "live" ? "text-fail-ink" : "text-muted"}`}>
                  {m.status === "live" ? "live" : [showDate ? shortDate(m.date) : "", m.time].filter(Boolean).join(" ") || STATUS_TEXT[m.status]}
                </span>
              )}
              <VersionBadge version={version} active={active} />
            </button>
            {nextReview?.id === m.id && !building && (
              <button
                type="button"
                data-target="meeting_end"
                onClick={() => void meetingWebhook(m.status === "live" ? "ended" : "started", m)}
                className={`ml-1.5 h-8 shrink-0 rounded-full px-3 text-[13px] font-bold transition ${
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
    </nav>
  );
}
