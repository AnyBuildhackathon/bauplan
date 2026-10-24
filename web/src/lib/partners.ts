import { useEffect } from "react";
import { create } from "zustand";
import { useSource } from "../events/source";
import { apiFetch } from "./api";

export interface PartnerStatus {
  id: string;
  label: string;
  state: "live" | "offline" | "mock";
  detail: string;
}

export interface IntegrationStatus {
  partners: PartnerStatus[];
  isaac: {
    host: string | null;
    gpu: string | null;
    state: "live" | "offline" | "mock";
    detail: string;
    last_run: { job_id: string | null; mode: string; status: string; source: string; stage: string | null; detail: string } | null;
  };
}

const ROSTER = [
  ["claude", "Claude"], ["jamie", "Jamie"], ["reson8", "Reson8"],
  ["elevenlabs", "ElevenLabs"], ["gemini", "Gemini Live"], ["freecad", "FreeCAD"], ["blender", "Blender"], ["isaac", "NVIDIA Isaac"],
];

function unavailable(recorded: boolean, detail: string): IntegrationStatus {
  const state = recorded ? "mock" : "offline";
  return {
    partners: ROSTER.map(([id, label]) => ({ id, label, state, detail })),
    isaac: { host: null, gpu: null, state, detail, last_run: null },
  };
}

export const usePartners = create<IntegrationStatus>(() => unavailable(false, "Waiting for backend status."));

/** Mounted once in the top bar; the GPU header shares the same status and polling loop. */
export function usePartnerStatus() {
  const mode = useSource((s) => s.mode);
  const live = useSource((s) => s.live);
  useEffect(() => {
    if (mode === "demo") {
      usePartners.setState(unavailable(true, "Recorded demo playback; this is not a live partner connection."));
      return;
    }
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    let controller: AbortController | undefined;
    const poll = async () => {
      controller = new AbortController();
      const deadline = setTimeout(() => controller?.abort(), 8000);
      try {
        const response = await apiFetch("/api/status", { signal: controller.signal });
        if (!response.ok) throw new Error("Status unavailable");
        const status = await response.json() as IntegrationStatus;
        if (active) usePartners.setState(status);
      } catch {
        if (active) usePartners.setState(unavailable(false, "Backend status unavailable; reconnect to check this integration."));
      } finally {
        clearTimeout(deadline);
        if (active) timer = setTimeout(poll, 15_000);
      }
    };
    usePartners.setState(unavailable(false, "Checking backend integration status."));
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
      controller?.abort();
    };
  }, [mode, live]);
}
