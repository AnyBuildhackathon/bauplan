// Mechanic reads his fresh lines aloud: the short question at the end of a "Rückfrage",
// and, when the backend has no narrator (no Claude key, or the recorded demo), the
// mascot's speech bubble. With a narrator the backend's `say` lines are spoken instead
// (lib/speech.ts), so the bubble stays silent. Replayed (seeked) events stay silent.
import { useEffect, useRef } from "react";
import { INSTANT_AGE_MS, useSession } from "../events/store";
import { useSource } from "../events/source";
import { speak, stopSpeaking } from "./speech";
import { voiceCapabilities } from "./voice";
import { useUi } from "./ui";

const FRESH_MS = Math.min(4000, INSTANT_AGE_MS);

/** The last sentence of a question, which is the part worth saying out loud. */
function lastSentence(text: string): string {
  const parts = text.split(/\n|(?<=[.?!“])\s+/);
  return parts.at(-1) ?? text;
}

/** The person is talking: push-to-talk is held, or a hands-free turn is under way. */
const personTalking = () => {
  const ui = useUi.getState();
  return ui.listening || ui.userTalking;
};

export function useBolzenVoice() {
  const voiceOn = useUi((s) => s.voiceOn);
  const mascot = useSession((s) => s.mascot);
  const questions = useSession((s) => s.questions);
  const mode = useSource((s) => s.mode);
  // Each line and each question is said once, when it arrives; while the person talks it is skipped, not saved for later.
  const spokenLine = useRef(0);
  const spokenQuestion = useRef("");

  useEffect(() => {
    if (!mascot.say || mascot.at === spokenLine.current) return;
    spokenLine.current = mascot.at;
    if (mode === "live" && voiceCapabilities().narrator) return;
    if (!voiceOn || personTalking() || Date.now() - mascot.at > FRESH_MS) return;
    void speak(mascot.say, mode);
  }, [mascot, voiceOn, mode]);

  useEffect(() => {
    const open = Object.values(questions).find((q) => q.status === "open");
    if (!open || open.id === spokenQuestion.current) return;
    spokenQuestion.current = open.id;
    if (!voiceOn || personTalking()) return;
    void speak(lastSentence(open.text), mode);
  }, [questions, voiceOn, mode]);

  useEffect(() => {
    if (!voiceOn) stopSpeaking();
  }, [voiceOn]);
}
