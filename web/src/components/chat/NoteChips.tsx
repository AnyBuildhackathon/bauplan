// Studio notes as chips (events/notes.ts): in Mechanic's message box, each with its ×, and under a sent
// message as the backend read them. A marking shows its picture, which opens full size from a sent message.
import { Layers, MousePointer2, Ruler, SlidersHorizontal, X } from "lucide-react";
import { noteLabel, useNotes } from "../../events/notes";
import type { SentNote, StudioNote } from "../../events/types";
import { assetUrl } from "../../lib/api";

const ICONS = { selection: MousePointer2, measure: Ruler, spot: Layers, param: SlidersHorizontal } as const;

function NoteChip({ note, thumb, onRemove }: { note: StudioNote | SentNote; thumb?: string | null; onRemove?: () => void }) {
  const { text, title } = noteLabel(note);
  const picture = note.kind === "markup" ? assetUrl(thumb ?? (note as SentNote).url ?? null) : null;
  const Icon = note.kind === "markup" ? null : ICONS[note.kind];
  const built = (note as SentNote).built_as;
  const body = (
    <>
      {picture ? (
        <img src={picture} alt="" className="h-6 w-8 shrink-0 rounded-[7px] bg-stage object-cover ring-1 ring-line" />
      ) : (
        Icon && <Icon className="h-3.5 w-3.5 shrink-0 text-accent" strokeWidth={2.2} />
      )}
      <span className="min-w-0 truncate">{text}</span>
      {built && !built.current && <span className="shrink-0 font-label text-[11px] font-normal text-agent-ink">older</span>}
    </>
  );
  const shape = `inline-flex h-8 max-w-[240px] min-w-0 items-center gap-1.5 rounded-full text-[13px] font-semibold text-ink ${picture ? "pl-1" : "pl-2.5"}`;
  if (onRemove) {
    return (
      <span className={`${shape} bg-tile pr-1`} title={title} data-target={`note:${note.kind}`}>
        {body}
        <button
          type="button"
          onClick={onRemove}
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-faint transition hover:bg-track hover:text-ink-2"
          aria-label={`Remove the note ${text}`}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </span>
    );
  }
  const sent = `${shape} bg-card pr-2.5 ring-1 ring-line`;
  return picture ? (
    <a href={picture} target="_blank" rel="noreferrer" className={`${sent} transition hover:bg-page-2`} title={`${title} (opens the picture)`} data-target={`note:${note.kind}`}>
      {body}
    </a>
  ) : (
    <span className={sent} title={title} data-target={`note:${note.kind}`}>
      {body}
    </span>
  );
}

/** The notes waiting in the message box; empty, nothing shows. */
export function DraftNoteChips() {
  const notes = useNotes((s) => s.notes);
  const remove = useNotes((s) => s.remove);
  if (notes.length === 0) return null;
  return (
    <div className="flex w-full min-w-0 flex-wrap gap-1.5" role="list" aria-label="Notes for Mechanic" data-target="notes:draft">
      {notes.map((d) => (
        <span key={d.id} role="listitem" className="min-w-0">
          <NoteChip note={d.note} thumb={d.thumb} onRemove={() => remove(d.id)} />
        </span>
      ))}
    </div>
  );
}

/** The notes a sent message carried, under its bubble. */
export function SentNoteChips({ notes }: { notes: SentNote[] }) {
  return (
    <div className="mt-1 flex max-w-full flex-wrap justify-end gap-1.5" data-target="notes:sent">
      {notes.map((note, i) => (
        <NoteChip key={i} note={note} />
      ))}
    </div>
  );
}
