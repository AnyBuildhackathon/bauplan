import { BenchSettings } from "./BenchSettings";
import { PartnerChips } from "./PartnerChips";

/** The app logo: the workbench cube, shown full. */
export function Logo({ size = 40 }: { size?: number }) {
  return (
    <img
      src={`${import.meta.env.BASE_URL}logo-mark.webp`}
      width={size}
      height={size}
      alt=""
      draggable={false}
      className="shrink-0 rounded-[12px] shadow-[0_0_0_1px_rgb(26_26_24_/_0.06)] select-none"
    />
  );
}

/** Partner availability and settings; meeting history lives in the Logbook. */
export function TopBar() {
  return (
    <header className="flex min-h-[56px] shrink-0 items-center gap-3 border-b border-line px-5 py-2">
      <PartnerChips />
      <BenchSettings />
    </header>
  );
}
