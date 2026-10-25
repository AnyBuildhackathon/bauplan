import { usePartnerStatus, usePartners } from "../lib/partners";
import { BenchSettings } from "./BenchSettings";

const PROVIDER = { api: "Claude · API key", subscription: "Claude · subscription", mock: "Offline mock" } as const;

/** Which Claude runs the bench: the API key, the local Claude Code subscription or the offline mock. */
function ProviderChip() {
  const claude = usePartners((s) => s.partners.find((p) => p.id === "claude"));
  if (!claude?.provider) return null;
  return (
    <span title={claude.detail} data-target="provider" className="flex h-8 items-center rounded-full bg-tile px-3 text-[13px] font-semibold text-ink-2">
      {PROVIDER[claude.provider]}
    </span>
  );
}

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

/** Settings on the right, with the Claude provider beside them. Meeting history lives in the Logbook. Partner status still polls for the Omniverse panel. */
export function TopBar() {
  usePartnerStatus();
  return (
    <header className="flex min-h-[56px] shrink-0 items-center justify-end gap-3 border-b border-line px-5 py-2">
      <ProviderChip />
      <BenchSettings />
    </header>
  );
}
