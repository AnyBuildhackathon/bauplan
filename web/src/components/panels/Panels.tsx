// Small pieces of the build's sources, shared by the chat and the bill of materials:
// a quote as a source citation.
import type { Quote } from "../../events/types";

/** A quote as a source citation: who it comes from and when, then the words. */
export function QuoteBubble({ quote, className = "" }: { quote: Pick<Quote, "text"> & Partial<Quote>; className?: string }) {
  const by = [quote.speaker, quote.time].filter(Boolean).join(" · ");
  return (
    <div className={`animate-rise rounded-[14px] bg-page-2 px-3.5 py-3 ${className}`}>
      {by && <p className="mb-1 text-[12px] font-medium text-muted">{by}</p>}
      <p className="font-read text-[14px] leading-normal text-ink-2">“{quote.text}”</p>
    </div>
  );
}
