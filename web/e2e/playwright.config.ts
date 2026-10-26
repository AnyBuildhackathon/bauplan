// End-to-end suite for the stage flows. It starts its own backend and Vite on their own ports
// (E2E_BACKEND_PORT 8135, E2E_WEB_PORT 5215), in mock mode unless E2E_LIVE=1.
import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const backendPort = process.env.E2E_BACKEND_PORT ?? "8135";
const webPort = process.env.E2E_WEB_PORT ?? "5215";
const live = process.env.E2E_LIVE === "1";

export default defineConfig({
  testDir: here,
  testMatch: live ? "live.spec.ts" : "*.spec.ts",
  // Every test drives the one backend session, so tests run one after another.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: live ? 240_000 : 90_000,
  expect: { timeout: 30_000 },
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    trace: "retain-on-failure",
    viewport: { width: 1600, height: 1000 },
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1600, height: 1000 },
        // The full Chromium in new headless mode keeps the GPU; the software renderer stalls the 3D canvas for seconds per frame.
        channel: "chromium",
        launchOptions: { args: ["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=metal"] },
      },
    },
  ],
  webServer: [
    {
      command: "uv run physical-ai-agent",
      cwd: `${here}../../agent`,
      url: `http://127.0.0.1:${backendPort}/api/health`,
      env: {
        PORT: backendPort,
        DEMO_PACE_S: "0",
        PAI_ASK_TIMEOUT_S: "2",
        // A busy host can spend minutes in Blender; mock UI checks use its existing still fallback.
        // Robo Use off: the gripper's trial is the recorded one, the same on every machine, and nothing runs a model.
        // SolidCraft as the CAD engine: only a request that names a linkage or SolidCraft reaches it (solidcraft.spec.ts).
        ...(live
          ? {}
          : { PAI_FORCE_MOCK: "1", PAI_WARM: "0", FREECAD_GUI: "off", PAI_TIMEOUT_BLENDER_RENDER: "15", PAI_ROBOUSE_BIN: "off", PAI_CAD_ENGINE: "solidcraft" }),
      },
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --port ${webPort} --host 127.0.0.1 --strictPort`,
      cwd: `${here}..`,
      url: `http://127.0.0.1:${webPort}`,
      env: { BACKEND_URL: `http://localhost:${backendPort}` },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
