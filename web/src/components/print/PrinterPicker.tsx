// "I have a 3D printer": the printer model and the user's filaments, in Settings and behind
// the printer button next to the prompt (PrinterButton). lib/printer.ts keeps the choice and
// sends it to the backend; this only edits it.
import { useEffect, useRef, useState } from "react";
import { ExternalLink, Printer } from "lucide-react";
import { usePrinter } from "../../lib/printer";

const DEFAULT_MODEL = "bambu-p1s";
const DEFAULT_FILAMENTS = ["PLA", "PETG"];

export function PrinterPicker() {
  const choice = usePrinter((s) => s.choice);
  const printer = usePrinter((s) => s.printer);
  const printers = usePrinter((s) => s.printers);
  const filaments = usePrinter((s) => s.filaments);
  const error = usePrinter((s) => s.error);
  const choose = usePrinter((s) => s.choose);
  const load = usePrinter((s) => s.load);
  useEffect(() => {
    if (!printers.length) void load();
  }, [printers.length, load]);

  const on = !!choice;
  const profile = printers.find((p) => p.id === choice?.model);
  const toggleFilament = (id: string) => {
    if (!choice) return;
    const next = choice.filaments.includes(id) ? choice.filaments.filter((f) => f !== id) : [...choice.filaments, id];
    void choose({ ...choice, filaments: next });
  };
  return (
    <div data-target="printer">
      <button
        type="button"
        role="switch"
        aria-checked={on}
        onClick={() => void choose(on ? null : { model: DEFAULT_MODEL, filaments: DEFAULT_FILAMENTS })}
        className="flex w-full items-center gap-3 py-1.5 text-left"
      >
        <span className="min-w-0 flex-1">
          <span className="block text-[14px] font-semibold text-ink">I have a 3D printer</span>
          <span className="block text-[12px] text-muted">Parts are made of your filaments, sliced for your printer and simulated in FEM</span>
        </span>
        <span className={`relative h-6 w-10 shrink-0 rounded-full transition ${on ? "bg-accent" : "bg-track"}`}>
          <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-[left] ${on ? "left-[18px]" : "left-0.5"}`} />
        </span>
      </button>
      {on && choice && (
        <div className="mt-1.5 space-y-2">
          <label className="flex items-center justify-between gap-3 text-[14px] font-semibold text-ink-2">
            Printer
            <select
              name="printer-model"
              value={choice.model}
              onChange={(e) => void choose({ ...choice, model: e.target.value })}
              className="h-8 max-w-[200px] min-w-0 rounded-full bg-tile px-3 text-[13px] font-semibold text-ink outline-none hover:bg-track"
            >
              {printers.length === 0 && <option value={choice.model}>{choice.model}</option>}
              {printers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <div>
            <span className="block text-[13px] font-semibold text-ink-2">Your filaments</span>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {filaments.map((f) => {
                const has = choice.filaments.includes(f.id);
                const blocked = !!profile && !profile.materials.includes(f.id);
                return (
                  <button
                    key={f.id}
                    type="button"
                    aria-pressed={has}
                    onClick={() => toggleFilament(f.id)}
                    title={blocked ? (f.needs_enclosure && !profile?.enclosure ? `${profile?.name} has no enclosure for ${f.id}` : `${profile?.name} does not print ${f.id}`) : `${f.name}, about ${f.eur_per_kg} € per kg`}
                    className={`h-7 rounded-full px-2.5 text-[12px] font-semibold transition ${
                      has ? (blocked ? "bg-fail-soft text-fail-ink line-through" : "bg-ink text-white") : "bg-tile text-ink-2 hover:bg-track"
                    }`}
                  >
                    {f.id === "NYLON" ? "Nylon" : f.id}
                  </button>
                );
              })}
            </div>
          </div>
          {printer && (
            <p className="num text-[12px] leading-snug text-muted">
              {printer.bed_mm.join(" × ")} mm bed · {printer.nozzle_mm} mm nozzle · {printer.enclosure ? "enclosed" : "open frame"} · prints{" "}
              {printer.printable.length ? printer.printable.join(", ") : "none of your filaments"}
              {printer.not_printable.length > 0 && <span className="text-fail-ink"> · not {printer.not_printable.join(", ")}</span>}{" "}
              <a href={printer.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 font-semibold text-link hover:underline">
                specs <ExternalLink className="h-3 w-3" />
              </a>
            </p>
          )}
        </div>
      )}
      {error && <p className="mt-1 text-[12px] font-semibold text-fail-ink">{error}</p>}
    </div>
  );
}

/** The printer button next to the prompt: shows the printer when one is set, opens the picker. */
export function PrinterButton({ size }: { size: "sm" | "lg" }) {
  const choice = usePrinter((s) => s.choice);
  const printers = usePrinter((s) => s.printers);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => {
      if (e.isTrusted && !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const escape = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", escape);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", escape);
    };
  }, [open]);
  const name = printers.find((p) => p.id === choice?.model)?.name.replace(/^(Bambu Lab|Original Prusa|Prusa|Creality|Elegoo) /, "");
  const lg = size === "lg";
  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-label={choice ? `3D printer: ${name ?? choice.model}` : "I have a 3D printer"}
        title={choice ? `Printing on your ${name ?? choice.model} with ${choice.filaments.join(", ") || "no filament"}` : "I have a 3D printer"}
        data-target="printer_button"
        className={`flex items-center justify-center gap-1.5 rounded-full font-semibold transition ${
          choice ? "bg-agent-soft text-agent-ink hover:brightness-95" : "bg-tile text-faint hover:bg-track hover:text-ink-2"
        } ${lg ? "h-11 min-w-11 px-3 text-[14px]" : "h-10 min-w-10 px-2.5 text-[12px]"}`}
      >
        <Printer className={lg ? "h-5 w-5" : "h-4.5 w-4.5"} strokeWidth={2} />
        {choice && name && <span className="max-w-[90px] truncate">{name}</span>}
      </button>
      {open && (
        <div className="absolute right-0 bottom-full z-[90] mb-2 w-[320px] max-w-[calc(100vw-32px)] animate-rise rounded-[20px] bg-card p-4 shadow-[var(--shadow-float)]">
          <PrinterPicker />
        </div>
      )}
    </div>
  );
}
