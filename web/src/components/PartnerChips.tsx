import { usePartners, usePartnerStatus } from "../lib/partners";
import { useUi } from "../lib/ui";

const TONES = {
  live: "bg-ok-soft text-ok-ink",
  offline: "bg-tile text-muted",
  mock: "bg-agent-soft text-agent-ink",
};

export function PartnerChips() {
  usePartnerStatus();
  const partners = usePartners((s) => s.partners);
  const gpu = usePartners((s) => s.isaac.gpu);
  return (
    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5" aria-label="Partner integrations">
      {partners.map((partner) => {
        const isaac = partner.id === "isaac";
        const status = isaac && partner.state === "live" ? `Connected${gpu ? ` · ${gpu}` : ""}` : partner.state;
        const label = `${partner.label}: ${status}. ${partner.detail}`;
        const content = <><span className={`h-1.5 w-1.5 shrink-0 rounded-full ${partner.state === "live" ? "bg-ok" : partner.state === "mock" ? "bg-agent" : "bg-faint"}`} aria-hidden />{partner.label}<span className="capitalize">{status}</span></>;
        const className = `inline-flex min-w-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-semibold ${TONES[partner.state]}`;
        return isaac ? (
          <button key={partner.id} type="button" title={label} aria-label={label} data-partner={partner.id} data-state={partner.state}
            onClick={() => { useUi.getState().setView("werkbank"); useUi.getState().selectTab("omniverse"); }}
            className={`${className} transition hover:brightness-95`}>{content}</button>
        ) : (
          <span key={partner.id} title={label} aria-label={label} tabIndex={0} data-partner={partner.id} data-state={partner.state} className={className}>{content}</span>
        );
      })}
    </div>
  );
}
