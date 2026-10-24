// Logbuch: the versions per Jamie meeting with their difference and the note written
// back to Jamie, saved chats, learned concepts, and the editable logbook (core-oss
// BlockEditor) with the Jamie summary of the session and Markdown export.
import { useEffect, useMemo, useRef, useState } from "react";
import { Download, MessageSquareText, NotebookPen, RefreshCw } from "lucide-react";
import BlockEditor from "../components/BlockEditor/BlockEditor";
import { blocksToMarkdown, createBlock, parseBlocksFromContent, serializeBlocks, type Block } from "../components/BlockEditor/types";
import { MascotHead } from "../components/mascot/Mascot";
import { JamieMark } from "../components/panels/Panels";
import { Card, Chip, PillButton } from "../components/ui/primitives";
import { STEP_IDS, type MeetingEvent, type VersionEvent } from "../events/types";
import { useSession } from "../events/store";
import { loadSavedChats } from "../lib/archive";
import { fmtClock, fmtEur, fmtGram, fmtNum, stripMarkdown } from "../lib/format";
import { enLabel, enText } from "../lib/copy";
import { LESSONS } from "../lib/lessons";
import { useUi } from "../lib/ui";

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function VersionCard({ v }: { v: VersionEvent }) {
  const pass = v.sim !== "fail";
  const selectVersion = useUi((s) => s.selectVersion);
  const setView = useUi((s) => s.setView);
  const fmt = (value: number | string, unit: string) => (typeof value === "number" ? `${fmtNum(value, unit === "€" ? 2 : 1)} ${unit}` : value);
  return (
    <div className="flex gap-3">
      <div className="flex flex-col items-center">
        <span className={`flex h-9 min-w-11 items-center justify-center rounded-full px-2 text-[15px] font-extrabold text-white ${pass ? "bg-ok" : "bg-fail"}`}>
          v{v.n}
        </span>
        <span className="mt-1 w-[2px] flex-1 rounded-full bg-track" />
      </div>
      <button
        type="button"
        onClick={() => {
          selectVersion(v.n);
          setView("werkbank");
        }}
        className="mb-3 min-w-0 flex-1 rounded-[22px] bg-page-2 p-4 text-left transition hover:bg-tile"
      >
        <div className="flex items-baseline gap-2">
          <span className="text-[17px] font-bold">from {v.meeting_title}</span>
          <span className={`text-[15px] font-bold ${pass ? "text-ok-ink" : "text-fail-ink"}`}>{pass ? "✓ hovers" : "✕ drops"}</span>
        </div>
        <p className="num mt-1 text-[15px] font-semibold text-ink-2">{v.summary}</p>
        {v.diff.length > 0 && (
          <ul className="num mt-2 space-y-0.5 text-[14px]">
            {v.diff.map((d) => (
              <li key={d.key} className="flex gap-2">
                <span className="w-28 shrink-0 font-semibold text-muted">{enLabel(d.label)}</span>
                <span className="min-w-0 truncate text-ink-2">
                  {fmt(d.before, d.unit)} → <b className="text-ink">{fmt(d.after, d.unit)}</b>
                </span>
              </li>
            ))}
          </ul>
        )}
        {v.note && (
          <div className="mt-3 flex gap-2 rounded-2xl bg-lavender/55 px-3 py-2.5">
            <NotebookPen className="mt-0.5 h-4 w-4 shrink-0 text-jamie" />
            <div className="min-w-0">
              <p className="text-[12px] font-bold text-jamie">Note on {v.meeting_title}</p>
              <p className="text-[14px] leading-snug whitespace-pre-line text-ink">{enText(v.note)}</p>
            </div>
          </div>
        )}
      </button>
    </div>
  );
}

function SavedChats() {
  const chat = useSession((s) => s.chat);
  const saved = useMemo(() => loadSavedChats(), []);
  const current = chat.filter((c) => c.kind === "msg");
  const [open, setOpen] = useState<"current" | number>("current");
  const shown =
    open === "current"
      ? current.map((c) => (c.kind === "msg" ? { role: c.role, text: stripMarkdown(c.text) } : null)).filter(Boolean)
      : saved[open]?.messages ?? [];
  return (
    <Card className="flex min-h-0 flex-col px-5 pt-4 pb-4">
      <div className="flex items-center gap-2">
        <MessageSquareText className="h-5 w-5 text-muted" />
        <h2 className="text-[17px] font-semibold text-ink-2">Gespeicherte Chats</h2>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setOpen("current")}
          className={`h-8 rounded-full px-3 text-[13px] font-semibold ${open === "current" ? "bg-ink text-white" : "bg-tile text-ink-2"}`}
        >
          Now · {current.length} messages
        </button>
        {saved.map((s, i) => (
          <button
            key={s.at + i}
            type="button"
            onClick={() => setOpen(i)}
            className={`h-8 rounded-full px-3 text-[13px] font-semibold ${open === i ? "bg-ink text-white" : "bg-tile text-ink-2"}`}
          >
            {fmtClock(s.at)} · {s.result}
          </button>
        ))}
      </div>
      <div className="scroll-soft mt-3 min-h-0 flex-1 space-y-2.5 overflow-y-auto pr-1">
        {shown.length === 0 && <p className="text-[15px] text-muted">No chat yet. Start on the workbench.</p>}
        {shown.map((m, i) =>
          m!.role === "user" ? (
            <div key={i} className="ml-8 rounded-[18px] rounded-br-md bg-tile px-3.5 py-2 text-[14px] leading-snug text-ink">
              {m!.text}
            </div>
          ) : (
            <div key={i} className="flex gap-2">
              <MascotHead size={24} />
              <p className="text-[14px] leading-snug text-ink-2">{m!.text}</p>
            </div>
          ),
        )}
      </div>
    </Card>
  );
}

function Concepts() {
  const concepts = useUi((s) => s.concepts);
  const steps = useSession((s) => s.steps);
  const openLesson = useUi((s) => s.openLesson);
  const understood = STEP_IDS.filter((id) => concepts[id] === "verstanden").length;
  return (
    <Card className="px-5 pt-4 pb-4">
      <div className="flex items-baseline">
        <h2 className="text-[17px] font-semibold text-ink-2">Learned</h2>
        <span className="num ml-auto text-[13px] font-semibold text-muted">
          {understood} of {STEP_IDS.length} learned
        </span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        {STEP_IDS.map((id) => {
          const l = LESSONS[id];
          const st = concepts[id];
          const reached = steps[id].status !== "pending";
          return (
            <button
              key={id}
              type="button"
              onClick={() => openLesson(id)}
              className={`rounded-[18px] p-3 text-left transition hover:bg-tile ${st ? "bg-page-2" : "bg-page-2/60 ring-1 ring-line ring-inset"} ${!reached && !st ? "opacity-60" : ""}`}
            >
              <div className="flex items-start gap-2">
                <span className="text-[15px] leading-tight font-bold">{l.concept}</span>
                <Chip tone={st === "verstanden" ? "ok" : st === "gesehen" ? "agent" : "muted"} className="ml-auto h-6! px-2! text-[11px]!">
                  {st === "verstanden" ? "learned" : st === "gesehen" ? "seen" : "open"}
                </Chip>
              </div>
            </button>
          );
        })}
      </div>
    </Card>
  );
}

function buildLogbook(args: {
  meetings: MeetingEvent[];
  versions: VersionEvent[];
  requirements: ReturnType<typeof useSession.getState>["requirements"];
  bom: ReturnType<typeof useSession.getState>["bom"];
  concepts: Record<string, string>;
}): Block[] {
  const b: Block[] = [];
  b.push(createBlock("heading1", "Drone · Logbook"));
  const stations = args.meetings.filter((m) => m.kind !== "archive" && m.status === "done").map((m) => m.title);
  b.push(createBlock("paragraph", esc(`${stations.join(" → ") || "No meeting yet"} · as of ${fmtClock(Date.now())}`)));
  if (args.requirements.length) {
    b.push(createBlock("heading2", "Requirements"));
    for (const r of args.requirements) {
      const mark = r.met === true ? "✓" : r.met === false ? "✕" : "○";
      const who = [r.speaker, r.time, r.meeting_title].filter(Boolean).join(", ");
      b.push(createBlock("bulletList", `${mark} <b>${esc(r.text)}</b>: „${esc(r.source_quote)}“${who ? ` (${esc(who)})` : ""}`));
    }
  }
  if (args.versions.length) {
    b.push(createBlock("heading2", "Jamie-Zusammenfassung"));
    for (const v of args.versions) {
      const lines = enText(v.note ?? `AnyBuild v${v.n} from ${v.meeting_title}: ${v.summary}.`).split("\n");
      b.push(createBlock("bulletList", `<b>${esc(lines[0])}</b>${lines.slice(1).map((l) => `<br>${esc(l)}`).join("")}`));
    }
  }
  if (args.bom) {
    b.push(createBlock("heading2", `Bill of materials · ${fmtEur(args.bom.total_eur)}`));
    for (const it of args.bom.items) b.push(createBlock("bulletList", esc(`${it.qty}× ${it.name}, ${fmtEur(it.unit_price_eur)}, ${fmtGram(it.weight_g)}`)));
  }
  const learned = STEP_IDS.filter((id) => args.concepts[id]);
  if (learned.length) {
    b.push(createBlock("heading2", "Learned"));
    for (const id of learned) b.push(createBlock("bulletList", `<b>${esc(LESSONS[id].concept)}</b>: ${args.concepts[id]}`));
  }
  b.push(createBlock("heading2", "Notes"));
  b.push(createBlock("paragraph", ""));
  return b;
}

function LogbookEditor() {
  const meetings = useSession((s) => s.meetings);
  const versions = useSession((s) => s.versions);
  const requirements = useSession((s) => s.requirements);
  const bom = useSession((s) => s.bom);
  const concepts = useUi((s) => s.concepts);
  const generated = useMemo(
    () => serializeBlocks(buildLogbook({ meetings, versions, requirements, bom, concepts })),
    [meetings, versions, requirements, bom, concepts],
  );
  const [content, setContent] = useState(generated);
  const edited = useRef(false);

  // Follow the session until someone edits the text by hand.
  useEffect(() => {
    if (!edited.current) setContent(generated);
  }, [generated]);

  const exportMd = () => {
    const md = blocksToMarkdown(parseBlocksFromContent(content));
    const url = URL.createObjectURL(new Blob([md], { type: "text/markdown;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `logbook-drone-${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <Card className="flex min-h-0 flex-1 flex-col pt-4 pb-4">
      <div className="flex items-center gap-2 px-5">
        <h2 className="text-[17px] font-semibold text-ink-2">Logbook</h2>
        <span className="text-[13px] text-muted">editable, “/” for blocks</span>
        <button
          type="button"
          onClick={() => {
            edited.current = false;
            setContent(generated);
          }}
          className="ml-auto rounded-full p-1.5 text-faint hover:bg-tile hover:text-ink-2"
          title="Rebuild from the session"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>
      <div className="mt-2 min-h-0 flex-1">
        <BlockEditor
          content={content}
          onChange={(c) => {
            edited.current = true;
            setContent(c);
          }}
        />
      </div>
      <div className="px-5 pt-3">
        <PillButton variant="agent" size="lg" className="w-full" onClick={exportMd}>
          <Download className="h-4.5 w-4.5" /> Export Markdown
        </PillButton>
      </div>
    </Card>
  );
}

export function LogbookView() {
  const versions = useSession((s) => s.versions);
  return (
    <div className="flex h-full min-h-0 flex-col gap-4 px-5 pb-4">
      <div className="flex items-baseline gap-3 pt-1">
        <h1 className="text-[34px] leading-none font-extrabold tracking-[-0.03em]">Logbook</h1>
        <span className="text-[17px] text-muted">Everything that was built, tested and learned.</span>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)_minmax(0,1fr)] gap-4">
        <Card className="flex min-h-0 flex-col px-5 pt-4 pb-2">
          <div className="mb-3 flex items-center gap-2">
            <h2 className="text-[17px] font-semibold text-ink-2">Versions</h2>
            <span className="text-[13px] text-muted">one per meeting in</span>
            <JamieMark />
          </div>
          <div className="scroll-soft min-h-0 flex-1 overflow-y-auto pr-1">
            {versions.length === 0 && <p className="text-[15px] text-muted">v1 comes out of the kickoff.</p>}
            {[...versions].reverse().map((v) => (
              <VersionCard key={v.n} v={v} />
            ))}
          </div>
        </Card>
        <SavedChats />
        <div className="flex min-h-0 flex-col gap-4">
          <Concepts />
          <LogbookEditor />
        </div>
      </div>
    </div>
  );
}
