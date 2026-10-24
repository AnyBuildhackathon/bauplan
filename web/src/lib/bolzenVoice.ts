// Bolzen reads his fresh lines aloud: the mascot's speech bubble and the short
// question at the end of a "Rückfrage". Replayed (seeked) events stay silent.
import { useEffect, useRef } from "react";
import { INSTANT_AGE_MS, useSession } from "../events/store";
import { useSource } from "../events/source";
import { speak, stopSpeaking } from "./voice";
import { useUi } from "./ui";

const FRESH_MS = Math.min(4000, INSTANT_AGE_MS);

/** The last sentence of a question, which is the part worth saying out loud. */
function lastSentence(text: string): string {
  const parts = text.split(/\n|(?<=[.?!“])\s+/);
  return parts.at(-1) ?? text;
}

export function useBolzenVoice() {
  const voiceOn = useUi((s) => s.voiceOn);
  const mascot = useSession((s) => s.mascot);
  const questions = useSession((s) => s.questions);
  const mode = useSource((s) => s.mode);
  // Each line and each question is said once, when it arrives; while the mic is open it is skipped, not saved for later.
  const spokenLine = useRef(0);
  const spokenQuestion = useRef("");

  useEffect(() => {
    if (!mascot.say || mascot.at === spokenLine.current) return;
    spokenLine.current = mascot.at;
    if (!voiceOn || useUi.getState().listening || Date.now() - mascot.at > FRESH_MS) return;
    void speak(mascot.say, mode);
  }, [mascot, voiceOn, mode]);

  useEffect(() => {
    const open = Object.values(questions).find((q) => q.status === "open");
    if (!open || open.id === spokenQuestion.current) return;
    spokenQuestion.current = open.id;
    if (!voiceOn || useUi.getState().listening) return;
    void speak(lastSentence(open.text), mode);
  }, [questions, voiceOn, mode]);

  useEffect(() => {
    if (!voiceOn) stopSpeaking();
  }, [voiceOn]);
}
