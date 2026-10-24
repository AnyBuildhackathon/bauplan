// Learning mode: glossary terms in a text get a dotted underline and a small tooltip on
// hover and keyboard focus.
import { GLOSSARY, glossSegments } from "../../lib/glossary";

export function Term({ term, children }: { term: string; children: string }) {
  return (
    <span className="group relative inline">
      <span tabIndex={0} className="cursor-help underline decoration-faint decoration-dotted underline-offset-[3px] outline-none focus-visible:decoration-ink">
        {children}
      </span>
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-[95] mb-1.5 w-[240px] -translate-x-1/2 rounded-[12px] bg-ink px-3 py-2 text-[13px] leading-snug font-medium text-white opacity-0 shadow-[var(--shadow-float)] transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
      >
        <span className="font-bold">{term}</span>: {GLOSSARY[term]}
      </span>
    </span>
  );
}

/** Plain text with the glossary terms wrapped in <Term>. */
export function Glossed({ text }: { text: string }) {
  return (
    <>
      {glossSegments(text).map((s, i) =>
        s.term ? (
          <Term key={i} term={s.term}>
            {s.text}
          </Term>
        ) : (
          <span key={i}>{s.text}</span>
        ),
      )}
    </>
  );
}
