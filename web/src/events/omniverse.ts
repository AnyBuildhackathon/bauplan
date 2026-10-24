import type { OmniverseEvent } from "./types";

/** The static deployment can show the same labelled fixture without a backend. */
export async function recordedOmniverse(text: string): Promise<OmniverseEvent | null> {
  if (!/\b(omniverse|isaac|gusty|gusts?|wind|payload|hover stability|train|training)\b|\d\s*g\s+camera/i.test(text)) return null;
  const mode = /\b(train|training|learn|policy)\b/i.test(text) ? "train" : "test";
  const response = await fetch("/demo/omniverse.json");
  if (!response.ok) throw new Error("The recorded demo is unavailable.");
  const fixture = (await response.json())[mode] as Pick<OmniverseEvent, "parameters" | "metrics" | "curve" | "engine" | "product_tested">;
  const payload = text.match(/(\d+(?:\.\d+)?)\s*g\b/i);
  const wind = text.match(/(\d+(?:\.\d+)?)\s*m\/s\b/i);
  const requested: Record<string, string | number> = mode === "train"
    ? { task: "Isaac-Quadcopter-Direct-v0" }
    : { scenario: /wind|gust/i.test(text) ? "wind" : payload ? "payload" : "hover",
        wind_m_s: wind ? Number(wind[1]) : /wind|gust/i.test(text) ? 6 : 0,
        payload_g: payload ? Number(payload[1]) : 0 };
  return {
    ...fixture, type: "omniverse", mode, source: "recorded", status: "recorded", requested,
    detail: "GPU not connected; nothing was measured.",
    curve: fixture.curve as [number, number][],
    video_url: "/demo/omniverse.mp4", json_url: "/demo/omniverse.json",
  };
}
