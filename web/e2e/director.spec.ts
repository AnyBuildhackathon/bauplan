import { expect, test, type Page } from "@playwright/test";
import type { AgentEvent } from "../src/events/types";
import { freshBench } from "./helpers";

// Exercise the same reducer fed by SSE, without spending 30 seconds building CAD per assertion.
async function emit(page: Page, event: AgentEvent) {
  await page.evaluate(async (ev) => {
    const module = "/src/events/store.ts";
    const { useSession } = await import(module);
    useSession.getState().apply(ev);
  }, event);
}

const tab = (page: Page, name: string) => page.getByRole("tab", { name, exact: true });

test("Director follows CAD and tests; manual tabs get 30 seconds then resume the latest shot", async ({ page }) => {
  await freshBench(page, "live");
  await page.clock.install();
  await emit(page, { type: "step", id: "cad", status: "running", label: "CAD" });
  await expect(tab(page, "CAD")).toHaveAttribute("aria-selected", "true");
  await emit(page, { type: "step", id: "simulation", status: "running", label: "Simulation" });
  await expect(tab(page, "Simulation")).toHaveAttribute("aria-selected", "true");
  await tab(page, "Model").click();
  await emit(page, { type: "step", id: "cad", status: "running", label: "CAD" });
  await page.clock.fastForward(29_000);
  await expect(tab(page, "Model")).toHaveAttribute("aria-selected", "true");
  await page.clock.fastForward(1_100);
  await expect(tab(page, "CAD")).toHaveAttribute("aria-selected", "true");
  await emit(page, { type: "step", id: "simulation", status: "running", label: "Simulation" });
  await tab(page, "Training").click();
  await emit(page, { type: "step", id: "cad", status: "running", label: "CAD" });
  await page.clock.fastForward(29_000);
  await expect(tab(page, "Simulation")).toHaveAttribute("aria-selected", "true");
  await expect(tab(page, "Training")).toHaveAttribute("aria-selected", "true");
  await page.clock.fastForward(1_100);
  await expect(tab(page, "CAD")).toHaveAttribute("aria-selected", "true");
});

test("Director preference persists and leaves other main views alone", async ({ page }) => {
  await freshBench(page, "live");
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  const director = page.getByRole("switch", { name: /Director mode/ });
  await expect(director).toHaveAttribute("aria-checked", "true");
  await director.click();
  await emit(page, { type: "step", id: "cad", status: "running", label: "CAD" });
  await expect(tab(page, "Model")).toHaveAttribute("aria-selected", "true");
  await page.reload();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(director).toHaveAttribute("aria-checked", "false");
  await director.click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Logbook", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "Jamie meetings" })).toBeVisible();
  await emit(page, { type: "step", id: "simulation", status: "running", label: "Simulation" });
  await expect(page.getByRole("heading", { name: "Logbook", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Workbench", exact: true }).click();
  await expect(tab(page, "Simulation")).toHaveAttribute("aria-selected", "true");
});

test("completed rebuild shows the Model version diff", async ({ page }) => {
  await freshBench(page, "live");
  const version = {
    type: "version" as const, n: 1, meeting_id: "kickoff", meeting_title: "Kickoff",
    weight_g: 40, thrust_to_weight: 2, flight_time_min: 8, price_eur: 60,
    sim: "pass" as const, parts: { battery: "550 mAh" }, diff: [], summary: "First build", product: "drone" as const,
  };
  await emit(page, version);
  await expect(tab(page, "Model")).toHaveAttribute("aria-selected", "true");
  await emit(page, { type: "step", id: "cad", status: "running", label: "CAD" });
  await expect(tab(page, "CAD")).toHaveAttribute("aria-selected", "true");
  await emit(page, { ...version, n: 2, flight_time_min: 10, parts: { battery: "680 mAh" }, summary: "Longer flight" });
  await expect(tab(page, "Model")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator('[data-target="compare"]')).toBeVisible();
  await expect(page.locator('[data-target="diff:part:battery"]')).toContainText("680 mAh");
  await page.getByRole("button", { name: "Close compare" }).click();
  await emit(page, { type: "chat", role: "agent", text: "Build complete." });
  await expect(page.locator('[data-target="compare"]')).toHaveCount(0);
  await page.clock.install();
  await tab(page, "CAD").click();
  await emit(page, { type: "reset" });
  await page.clock.fastForward(31_000);
  await expect(tab(page, "CAD")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator('[data-target="compare"]')).toHaveCount(0);
});

test("independent partner states, NVIDIA header and job progress", async ({ page }) => {
  await page.route("**/api/status", (route) => route.fulfill({ json: {
    partners: [
      { id: "claude", label: "Claude", state: "live", detail: "Credentials configured." },
      { id: "jamie", label: "Jamie", state: "mock", detail: "Local outbox." },
      { id: "reson8", label: "Reson8", state: "offline", detail: "Browser fallback." },
      { id: "isaac", label: "NVIDIA Isaac", state: "live", detail: "SSH connected." },
    ],
    isaac: { host: "gpu.example", gpu: "NVIDIA A40", state: "live", detail: "SSH connected.", last_run: null },
  } }));
  await freshBench(page, "live");
  await expect(page.locator('header [data-partner="claude"]')).toHaveAttribute("data-state", "live");
  await expect(page.locator('header [data-partner="jamie"]')).toHaveAttribute("data-state", "mock");
  await expect(page.locator('header [data-partner="reson8"]')).toHaveAttribute("data-state", "offline");
  await expect(page.locator("header").getByRole("navigation", { name: "Jamie meetings" })).toHaveCount(0);
  await page.locator('[data-partner="isaac"]').click();
  const header = page.locator('[data-target="isaac:connection"]');
  await expect(header).toContainText("NVIDIA A40");
  await expect(header).toContainText("gpu.example");
  await expect(header).toContainText("No job in this session");
  await emit(page, { type: "omniverse", mode: "test", status: "running", source: "live", stage: "execute", detail: "Running physics on the GPU.", requested: { wind_m_s: 6 }, metrics: {}, curve: [], video_url: null, json_url: null });
  await expect(header).toContainText("test · running · execute");
  await expect(page.getByRole("list", { name: "Experiment progress" })).toBeVisible();
  await expect(page.getByText("Running physics on the GPU.")).toBeVisible();
});

test("unavailable status marks every provider offline without hiding settings", async ({ page }) => {
  await page.route("**/api/status", (route) => route.fulfill({ status: 503, json: { detail: "Unavailable" } }));
  await freshBench(page, "live");
  await expect(page.locator("header [data-partner]")).toHaveCount(7);
  await expect(page.locator('header [data-partner][data-state="offline"]')).toHaveCount(7);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByRole("switch", { name: /Director mode/ })).toBeVisible();
});
