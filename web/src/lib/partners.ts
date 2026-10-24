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

function unavailable(detail: string): IntegrationStatus {
  return {
    partners: ROSTER.map(([id, label]) => ({ id, label, state: "offline", detail })),
    isaac: { host: null, gpu: null, state: "offline", detail, last_run: null },
  };
}

export const usePartners = create<IntegrationStatus>(() => unavailable("Waiting for backend status."));

/** Mounted once from the top bar; the Omniverse panel shares this polling loop. */
export function usePartnerStatus() {
  const live = useSource((s) => s.live);
  useEffect(() => {
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
        if (active) usePartners.setState(unavailable("Backend status unavailable; reconnect to check this integration."));
      } finally {
        clearTimeout(deadline);
        if (active) timer = setTimeout(poll, 15_000);
      }
    };
    usePartners.setState(unavailable("Checking backend integration status."));
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
      controller?.abort();
    };
  }, [live]);
}
