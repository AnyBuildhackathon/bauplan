// The Checks tab of the right panel: every requirement of the build with the words behind it
// (the request's quote, or "Mechanic" for a limit he proposed) and whether the latest build
// meets it. The same lines as the requirements card in the chat, in one place to look them up.
import { ListChecks } from "lucide-react";
import { useSession } from "../../events/store";
import { RequirementLine } from "../chat/BuildCards";
import { PanelEmpty, PanelHeader } from "./RightRail";

export function ChecksTab() {
  const requirements = useSession((s) => s.requirements);
  const met = requirements.filter((r) => r.met === true).length;
  const failed = requirements.filter((r) => r.met === false).length;
  const proposed = requirements.filter((r) => r.source === "proposed").length;
  const tone = failed ? "text-fail-ink" : requirements.length && met === requirements.length ? "text-ok-ink" : "text-muted";
  return (
    <>
      <PanelHeader
        title="Checks"
        detail={
          requirements.length > 0 && (
            <>
              <span className={tone}>
                {met} of {requirements.length} met
              </span>
              {proposed > 0 && ` · ${proposed} proposed by Mechanic`}
            </>
          )
        }
      />
      <div className="scroll-soft min-h-0 flex-1 overflow-y-auto px-5 py-4" data-target="checks">
        {requirements.length === 0 ? (
          <PanelEmpty icon={ListChecks} title="No checks yet">
            Mechanic turns your request into requirements, each with your words or marked as his proposal, and checks every build against them.
          </PanelEmpty>
        ) : (
          <section className="rounded-[14px] bg-page-2 px-2 pt-2.5 pb-1.5">
            <h3 className="mb-1 px-1.5 text-[14px] font-semibold text-ink">Requirements</h3>
            <ul>
              {requirements.map((r) => (
                <RequirementLine key={r.id} r={r} />
              ))}
            </ul>
          </section>
        )}
      </div>
    </>
  );
}
