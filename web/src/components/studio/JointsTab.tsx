// The Joints tab of the right panel. A build does not export its joints yet, so the tab says
// what will show here once it does: one slider per moving part within its limits.
import { Rotate3d } from "lucide-react";
import { PanelEmpty, PanelHeader } from "./RightRail";

export function JointsTab() {
  return (
    <>
      <PanelHeader title="Joints" />
      <div className="scroll-soft min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <PanelEmpty icon={Rotate3d} title="No joints yet">
          The moving parts of a design, such as a gripper's fingers, show up here with their limits once the build exports its joints.
        </PanelEmpty>
      </div>
    </>
  );
}
