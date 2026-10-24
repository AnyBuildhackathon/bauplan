// Logbuch: one column with a timeline of the versions. Each entry says what triggered
// it (a Jamie meeting or a chat request), the three key numbers and what changed in one
// line; it opens to the full difference and the note written back to Jamie. Saved
// chats fold away below, the learned concepts show only in learning mode, and Export
// downloads the whole logbook as Markdown.
import { useMemo, useState } from "react";
import { ChevronDown, Download, MessageSquareText, NotebookPen } from "lucide-react";
import { MascotHead } from "../components/mascot/Mascot";
import { Chip, PillButton } from "../components/ui/primitives";
import { MeetingTimeline } from "../components/timeline/MeetingTimeline";
import { STEP_IDS, type MeetingEvent, type VersionDiff, type VersionEvent } from "../events/types";
import { useSession } from "../events/store";
import { loadSavedChats } from "../lib/archive";
import { fmtClock, fmtEur, fmtGram, fmtNum, stripMarkdown } from "../lib/format";
import { enLabel, enText } from "../lib/copy";
import { LESSONS } from "../lib/lessons";
import { apiFetch } from "../lib/api";
import { useSource } from "../events/source";
import { useUi } from "../lib/ui";

type Session = ReturnType<typeof useSession.getState>;

const fmtValue = (value: number | string, unit: string) => (typeof value === "number" ? `${fmtNum(value, unit === "€" ? 2 : 1)} ${unit}` : enText(value));

function diffText(d: VersionDiff): string {
  return `${enLabel(d.label)} ${fmtValue(d.before, d.unit)} → ${fmtValue(d.after, d.unit)}`;
}

/** What changed against the version before, in one line. */
function changeLine(v: VersionEvent): string {
  if (v.n === 1) return "First build";
  if (!v.diff.length) return "No change";
  const parts = v.diff.filter((d) => !d.unit);
  const numbers = v.diff.filter((d) => d.unit);
  return [...parts, ...numbers].map(diffText).join(" · ");
}

/** The three key numbers a version carries; products that do not fly leave out flight time. */
function keyNumbers(v: VersionEvent): { label: string; value: string }[] {
  return [
    { label: "Weight", value: v.weight_g > 0 ? `${fmtNum(v.weight_g, v.weight_g < 100 ? 1 : 0)} g` : "" },
    { label: "Flight time", value: v.flight_time_min > 0 ? `${fmtNum(v.flight_time_min, 1)} min` : "" },
    { label: "Price", value: v.price_eur > 0 ? fmtEur(v.price_eur) : "" },
  ].filter((n) => n.value);
}

function useTrigger(v: VersionEvent): { meeting: MeetingEvent | undefined; label: string } {
  const meeting = useSession((s) => s.meetings.find((m) => m.id === v.meeting_id && m.kind !== "archive"));
  return { meeting, label: meeting?.title ?? (v.meeting_title && v.meeting_title !== "Meeting" ? v.meeting_title : "Chat request") };
}

function VersionEntry({ v, last }: { v: VersionEvent; last: boolean }) {
  const [open, setOpen] = useState(false);
  const selectVersion = useUi((s) => s.selectVersion);
  const setView = useUi((s) => s.setView);
  const { meeting, label } = useTrigger(v);
  const tested = v.sim !== null;
  const pass = v.sim !== "fail";
  return (
    <li className="flex gap-4" data-target={`logbook:v${v.n}`}>
      <div className="flex flex-col items-center">
        <span className={`num flex h-7 min-w-9 items-center justify-center rounded-full px-2 text-[13px] font-semibold text-white ${pass ? "bg-ok" : "bg-fail"}`}>
          v{v.n}
        </span>
        {!last && <span className="mt-1.5 w-px flex-1 bg-track" />}
      </div>
      <div className={`min-w-0 flex-1 ${last ? "" : "pb-6"}`}>
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="group block w-full text-left">
          <div className="flex items-center gap-2 text-[13px] font-medium text-muted">
            {meeting ? <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-jamie" /> : <MessageSquareText className="h-3.5 w-3.5 shrink-0" />}
            <span className="truncate">
              {meeting && "Jamie meeting · "}
              <span className="text-ink-2">{label}</span>
              {tested && <span className={pass ? "text-ok-ink" : "text-fail-ink"}> · {pass ? "test passed" : "test failed"}</span>}
            </span>
            <ChevronDown className={`ml-auto h-4 w-4 shrink-0 text-faint transition group-hover:text-ink-2 ${open ? "rotate-180" : ""}`} />
          </div>
          <div className="num mt-1 flex flex-wrap gap-x-5 gap-y-0.5 text-[17px] font-semibold tracking-[-0.01em] text-ink">
            {keyNumbers(v).map((n) => (
              <span key={n.label} title={n.label}>
                {n.value}
              </span>
            ))}
          </div>
          {!(open && v.diff.length) && <p className="num mt-0.5 truncate font-read text-[14px] text-ink-2">{changeLine(v)}</p>}
        </button>
        {open && (
          <div className="mt-3 animate-rise space-y-3">
            {v.diff.length > 0 && (
              <ul className="num space-y-0.5 text-[13px]">
                {v.diff.map((d) => (
                  <li key={d.key} className="flex gap-3">
                    <span className="w-28 shrink-0 text-muted">{enLabel(d.label)}</span>
                    <span className="min-w-0 text-ink-2">
                      {fmtValue(d.before, d.unit)} → <b className="font-semibold text-ink">{fmtValue(d.after, d.unit)}</b>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {v.note && (
              <div className="flex gap-2.5 rounded-[14px] bg-lavender/50 px-3.5 py-3">
                <NotebookPen className="mt-0.5 h-4 w-4 shrink-0 text-jamie" />
                <div className="min-w-0">
                  <p className="text-[12px] font-semibold text-jamie">Note in Jamie{meeting ? ` · ${meeting.title}` : ""}</p>
                  <p className="font-read text-[13px] leading-normal whitespace-pre-line text-ink-2">{enText(v.note)}</p>
                </div>
              </div>
            )}
            <button
              type="button"
              onClick={() => {
                selectVersion(v.n);
                setView("werkbank");
              }}
              className="text-[13px] font-semibold text-accent hover:underline"
            >
              Show v{v.n} on the workbench
            </button>
          </div>
        )}
      </div>
    </li>
  );
}

function Section({ title, meta, children }: { title: string; meta?: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="border-t border-line">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="group flex w-full items-center gap-2 py-3.5 text-left">
        <span className="text-[14px] font-semibold text-ink-2">{title}</span>
        {meta && <span className="num text-[13px] text-muted">{meta}</span>}
        <ChevronDown className={`ml-auto h-4 w-4 text-faint transition group-hover:text-ink-2 ${open ? "rotate-180" : ""}`} />
      </button>
      {open && <div className="animate-rise pb-5">{children}</div>}
    </section>
  );
}

function Chats() {
  const chat = useSession((s) => s.chat);
  const saved = useMemo(() => loadSavedChats(), []);
  const current = chat.flatMap((c) => (c.kind === "msg" ? [{ role: c.role, text: stripMarkdown(c.text) }] : []));
  const [open, setOpen] = useState<"current" | number>("current");
  const shown = open === "current" ? current : (saved[open]?.messages ?? []);
  const meetings = useSession((s) => s.meetings);
  const live = useSource((s) => s.mode) === "live";
  const [meetingId, setMeetingId] = useState("");
  const [noteStatus, setNoteStatus] = useState("");
  const [sending, setSending] = useState(false);
  const targetMeeting = meetingId || meetings.find((m) => m.status === "live")?.id
    || [...meetings].reverse().find((m) => m.status === "done")?.id
    || meetings.find((m) => m.kind !== "archive")?.id || "";
  const sendToJamie = async () => {
    setSending(true);
    setNoteStatus("");
    try {
      const response = await apiFetch("/api/voice/note", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ meeting_id: targetMeeting, text: shown.map((m) => `${m.role === "user" ? "You" : "Mechanic"}: ${m.text}`).join("\n\n").slice(0, 24000) }),
      });
      const result = await response.json();
      if (!response.ok || result.ok === false) throw new Error("Could not send the note.");
      setNoteStatus(result.live ? "Sent to Jamie." : "Saved to the Jamie outbox.");
    } catch { setNoteStatus("Could not send the note. Try again."); }
    finally { setSending(false); }
  };
  return (
    <Section title="Chats" meta={`${current.length} messages${saved.length ? ` · ${saved.length} earlier` : ""}`}>
      <div className="flex flex-wrap gap-1.5">
        <button
          type="button"
          onClick={() => setOpen("current")}
          className={`h-7 rounded-full px-3 text-[12px] font-semibold ${open === "current" ? "bg-ink text-white" : "bg-tile text-ink-2 hover:bg-track"}`}
        >
          Now · {current.length} messages
        </button>
        {saved.map((s, i) => (
          <button
            key={s.at + i}
            type="button"
            onClick={() => setOpen(i)}
            className={`h-7 rounded-full px-3 text-[12px] font-semibold ${open === i ? "bg-ink text-white" : "bg-tile text-ink-2 hover:bg-track"}`}
          >
            {fmtClock(s.at)} · {s.result}
          </button>
        ))}
      </div>
      {live && shown.length > 0 && meetings.length > 0 && <div className="mt-3 flex flex-wrap items-center gap-2">
        <select name="conversation-meeting" aria-label="Jamie meeting for conversation note" value={targetMeeting} onChange={(e) => setMeetingId(e.target.value)} className="min-w-0 max-w-full rounded-full bg-tile px-3 py-1 text-[12px] text-ink">
          {meetings.map((m) => <option key={m.id} value={m.id}>{m.title}</option>)}
        </select>
        <PillButton variant="secondary" size="sm" disabled={sending || !targetMeeting} onClick={() => void sendToJamie()}>{sending ? "Sending…" : "Send to Jamie"}</PillButton>
        {noteStatus && <p role="status" className="w-full text-[12px] text-muted">{noteStatus}</p>}
      </div>}
      <div className="scroll-soft mt-3 max-h-[420px] space-y-2 overflow-y-auto pr-1">
        {shown.length === 0 && <p className="text-[14px] text-muted">No chat yet. Start on the workbench.</p>}
        {shown.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="flex justify-end pl-10">
              <p className="rounded-[16px] rounded-br-md bg-tile px-3 py-1.5 font-read text-[13px] leading-normal text-ink">{m.text}</p>
            </div>
          ) : (
            <div key={i} className="flex gap-2">
              <MascotHead size={24} />
              <p className="font-read text-[13px] leading-normal text-ink-2">{m.text}</p>
            </div>
          ),
        )}
      </div>
    </Section>
  );
}

function Learned() {
  const concepts = useUi((s) => s.concepts);
  const steps = useSession((s) => s.steps);
  const openLesson = useUi((s) => s.openLesson);
  const understood = STEP_IDS.filter((id) => concepts[id] === "verstanden").length;
  return (
    <Section title="Learned" meta={`${understood} of ${STEP_IDS.length}`}>
      <div className="flex flex-wrap gap-1.5">
        {STEP_IDS.map((id) => {
          const st = concepts[id];
          const reached = steps[id].status !== "pending";
          return (
            <button
              key={id}
              type="button"
              onClick={() => openLesson(id)}
              className={`flex h-8 items-center gap-2 rounded-full bg-tile pr-1.5 pl-3 text-[13px] font-semibold text-ink-2 transition hover:bg-track ${!reached && !st ? "opacity-60" : ""}`}
            >
              {LESSONS[id].concept}
              <Chip tone={st === "verstanden" ? "ok" : st === "gesehen" ? "agent" : "muted"} className="h-5! px-2! text-[11px]!">
                {st === "verstanden" ? "learned" : st === "gesehen" ? "seen" : "open"}
              </Chip>
            </button>
          );
        })}
      </div>
    </Section>
  );
}

function logbookMarkdown(s: Pick<Session, "meetings" | "versions" | "requirements" | "bom" | "productLabel">, concepts: Record<string, string>): string {
  const lines: string[] = [];
  lines.push(`# ${s.productLabel || "Build"} · Logbook`, "");
  const stations = s.meetings.filter((m) => m.kind !== "archive" && m.status === "done").map((m) => m.title);
  lines.push(`${stations.join(" → ") || "No meeting yet"} · as of ${fmtClock(Date.now())}`, "");
  if (s.versions.length) {
    lines.push("## Versions", "");
    for (const v of [...s.versions].reverse()) {
      const meeting = s.meetings.find((m) => m.id === v.meeting_id && m.kind !== "archive");
      lines.push(`### v${v.n} · ${meeting ? `Jamie meeting ${meeting.title}` : v.meeting_title || "Chat request"}`, "");
      lines.push(`${keyNumbers(v).map((n) => `${n.label} ${n.value}`).join(" · ")}${v.sim ? ` · test ${v.sim === "pass" ? "passed" : "failed"}` : ""}`, "");
      for (const d of v.diff) lines.push(`- ${diffText(d)}`);
      if (v.diff.length) lines.push("");
      if (v.note) lines.push(...enText(v.note).split("\n").map((l) => `> ${l}`), "");
    }
  }
  if (s.requirements.length) {
    lines.push("## Requirements", "");
    for (const r of s.requirements) {
      const mark = r.met === true ? "✓" : r.met === false ? "✕" : "○";
      const who = [r.speaker, r.time, r.meeting_title].filter(Boolean).join(", ");
      lines.push(`- ${mark} **${r.text}**: "${r.source_quote}"${who ? ` (${who})` : ""}`);
    }
    lines.push("");
  }
  if (s.bom) {
    lines.push(`## Bill of materials · ${fmtEur(s.bom.total_eur)}`, "");
    for (const it of s.bom.items) lines.push(`- ${it.qty}× ${it.name}, ${fmtEur(it.unit_price_eur)}, ${fmtGram(it.weight_g)}`);
    lines.push("");
  }
  const learned = STEP_IDS.filter((id) => concepts[id]);
  if (learned.length) {
    lines.push("## Learned", "");
    for (const id of learned) lines.push(`- **${LESSONS[id].concept}**: ${concepts[id] === "verstanden" ? "learned" : "seen"}`);
    lines.push("");
  }
  return lines.join("\n");
}

export function LogbookView() {
  const versions = useSession((s) => s.versions);
  const learning = useUi((s) => s.display.learning);

  const exportMd = () => {
    const md = logbookMarkdown(useSession.getState(), useUi.getState().concepts);
    const url = URL.createObjectURL(new Blob([md], { type: "text/markdown;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `logbook-${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <div className="scroll-soft h-full overflow-y-auto">
      <div className="mx-auto max-w-[720px] px-6 pt-8 pb-12">
        <div className="mb-7 flex items-end gap-4">
          <div className="min-w-0 flex-1">
            <h1 className="text-[26px] leading-tight font-semibold tracking-[-0.02em] text-ink">Logbook</h1>
            <p className="text-[14px] text-muted">Every version, what triggered it and what changed.</p>
          </div>
          <PillButton variant="secondary" size="sm" onClick={exportMd} title="Download the logbook as Markdown" data-target="logbook_export">
            <Download className="h-4 w-4" /> Export
          </PillButton>
        </div>
        <div className="mb-5"><MeetingTimeline /></div>
        {versions.length === 0 ? (
          <p className="pb-6 text-[14px] text-muted">No version yet. v1 comes out of the kickoff or your first request.</p>
        ) : (
          <ol className="pb-6">
            {[...versions].reverse().map((v, i) => (
              <VersionEntry key={v.n} v={v} last={i === versions.length - 1} />
            ))}
          </ol>
        )}
        <Chats />
        {learning && <Learned />}
      </div>
    </div>
  );
}
