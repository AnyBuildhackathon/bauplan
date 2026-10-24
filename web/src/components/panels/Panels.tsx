// Small pieces of the build's sources, shared by the chat and the bill of materials:
// the Jamie mark and a quote as a source citation.
import type { Quote } from "../../events/types";

export function JamieMark({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex h-6 items-center gap-1 rounded-full bg-lavender px-2.5 text-[12px] font-bold text-jamie ${className}`}>
      <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
        <circle cx="5" cy="5" r="4" fill="currentColor" />
      </svg>
      Jamie
    </span>
  );
}

/** A Jamie quote as a source citation: who said it, in which meeting, when, then the words. */
export function QuoteBubble({ quote, className = "" }: { quote: Pick<Quote, "text"> & Partial<Quote>; className?: string }) {
  const by = [quote.speaker, quote.meeting_title, quote.time].filter(Boolean).join(" · ");
  return (
    <div className={`animate-rise rounded-[14px] bg-page-2 px-3.5 py-3 ${className}`}>
      {by && <p className="mb-1 text-[12px] font-medium text-muted">{by}</p>}
      <p className="font-read text-[14px] leading-normal text-ink-2">“{quote.text}”</p>
    </div>
  );
}
