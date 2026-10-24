// Firmware and wiring in the bill-of-materials drawer: the generated Betaflight CLI file
// or Arduino sketch as a download, and the wiring table built from the same parts.
import { Cpu, Download } from "lucide-react";
import { useSession } from "../events/store";
import type { FirmwareEvent } from "../events/types";

/** Downloads the file from the event itself, so it does not need a second request. */
function download(fw: FirmwareEvent) {
  const blob = new Blob([fw.content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fw.filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const GAINS_LABEL: Record<FirmwareEvent["gains_source"], string> = {
  isaac: "Isaac Lab gains",
  browser: "Browser-tuned gains",
  defaults: "Default gains",
  none: "",
};

export function FirmwareSection() {
  const fw = useSession((s) => s.firmware);
  if (!fw) return null;
  const subtitle = fw.kind === "betaflight" ? "Betaflight CLI" : "Arduino sketch";
  const gainsLabel = GAINS_LABEL[fw.gains_source];
  return (
    <section className="card px-4 pt-4 pb-3" data-target="firmware">
      <div className="mb-2 flex items-center gap-3 px-2">
        <Cpu className="h-5 w-5 shrink-0 text-ink-2" />
        <div className="min-w-0">
          <h2 className="text-[18px] font-bold">Firmware and wiring</h2>
          <p className="truncate text-[13px] font-semibold text-muted">{subtitle}</p>
        </div>
        {gainsLabel && (
          <span className="ml-auto shrink-0 text-[13px] font-semibold text-muted" data-target="firmware:gains_source">
            {gainsLabel}
          </span>
        )}
        <button
          type="button"
          onClick={() => download(fw)}
          className={`${gainsLabel ? "" : "ml-auto "}inline-flex h-10 shrink-0 items-center gap-2 rounded-full bg-agent px-4 text-[15px] font-bold text-white hover:brightness-105`}
        >
          <Download className="h-4.5 w-4.5" /> Download firmware
        </button>
      </div>
      {fw.explanation && <p className="px-2 pb-2 text-[15px] leading-snug text-ink-2">{fw.explanation}</p>}
      <div className="overflow-x-auto px-2 pb-1">
        <table className="w-full text-left text-[14px]">
          <thead className="text-[12px] font-bold text-muted uppercase">
            <tr>
              <th className="py-1.5 pr-3">Component</th>
              <th className="py-1.5 pr-3">Pin</th>
              <th className="py-1.5 pr-3">Wire</th>
              <th className="py-1.5">Connects to</th>
            </tr>
          </thead>
          <tbody>
            {fw.wiring.map((row, i) => (
              <tr key={i} className="border-t border-line align-top">
                <td className="py-1.5 pr-3 font-semibold">{row.component}</td>
                <td className="num py-1.5 pr-3">{row.pin}</td>
                <td className="py-1.5 pr-3">{row.wire}</td>
                <td className="py-1.5 text-ink-2">
                  {row.connects_to}
                  {row.note && <span className="block text-[13px] text-muted">{row.note}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
