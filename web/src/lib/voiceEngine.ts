import { create } from "zustand";
export type VoiceEngine = "gemini" | "elevenlabs";
function stored(): VoiceEngine | null {
  try {
    const value = localStorage.getItem("anybuild.voice-engine");
    return value === "gemini" || value === "elevenlabs" ? value : null;
  } catch { return null; }
}
export const useVoiceEngine = create<{
  choice: VoiceEngine | null;
  available: boolean;
  active: boolean;
  choose: (engine: VoiceEngine) => void;
}>((set) => ({
  choice: stored(), available: false, active: false,
  choose: (choice) => {
    try { localStorage.setItem("anybuild.voice-engine", choice); } catch { /* Private browsing. */ }
    set({ choice });
  },
}));
export const selectedVoiceEngine = () => {
  const s = useVoiceEngine.getState();
  return s.available ? (s.choice ?? "gemini") : "elevenlabs";
};
