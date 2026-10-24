// Mechanic never reads his chat lines, bubbles or questions aloud: he speaks only inside a
// voice conversation the person started (lib/geminiLive.ts). The header mute toggle cuts
// whatever he is saying at once.
import { useEffect } from "react";
import { stopSpeaking } from "./speech";
import { useUi } from "./ui";

export function useBolzenVoice() {
  const voiceOn = useUi((s) => s.voiceOn);
  useEffect(() => {
    if (!voiceOn) stopSpeaking();
  }, [voiceOn]);
}
