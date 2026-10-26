// The stage flows in mock mode: no key, no FreeCAD or Blender needed (CadQuery and the recorded still stand in).
import { expect, test } from "@playwright/test";
import { ask, bomButton, freshBench, idle, requirement } from "./helpers";

const GRIPPER = "Design a robot gripper that picks up a 200 g soda can, 66 mm wide";
const STAND = "Design a phone stand for my desk";

test("drone reference: Library, Rebuild, v1 with every check met", async ({ page }) => {
  await freshBench(page, "view=library");
  await page.locator('[data-target="library:micro-drone"]').dispatchEvent("click");
  // The mock rebuild takes about 30 s on a loaded machine, as long as the default expect timeout.
  await expect(page.getByText("Version 1 ·", { exact: false }).first()).toBeAttached({ timeout: 60_000 });
  await expect(page.locator('[data-target~="requirements"]')).toContainText(/(\d+) of \1 met/);
  await expect(bomButton(page)).toContainText("€");
  await idle(page);
  // dispatchEvent: on a loaded machine the 3D canvas keeps the page busy, and a real click waits for it to settle.
  await page.locator('[data-target="tab:cad"]').dispatchEvent("click");
  await expect(page.locator('[data-target="tab:cad"]')).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("canvas").first()).toBeAttached();
});

test("typed drone request: the requirements card is built from the prompt, a typed change builds v2", async ({ page }) => {
  // Two builds with their mission flights, each allowed 60 s below; the suite's 90 s would cut the second short on a busy machine.
  test.setTimeout(240_000);
  await freshBench(page);
  await ask(page, "I want to build a drone that hunts flies under 150 euros");
  await expect(page.getByText("Version 1", { exact: false }).first()).toBeAttached({ timeout: 60_000 });
  const budget = requirement(page, "budget");
  // The typed limit, quoted from the prompt: no stock budget, no meeting.
  await expect(budget).toContainText("Total price under €150");
  await expect(budget).toContainText("you");
  await expect(requirement(page, "hover")).toContainText("Mechanic");
  await expect(page.locator('[data-target~="requirements"]')).toContainText("from your request");
  await expect(page.getByText(/Jamie|kickoff/i)).toHaveCount(0);
  await idle(page);
  await ask(page, "Make it fly 10 minutes.");
  await expect(page.getByText("Version 2", { exact: false }).first()).toBeAttached({ timeout: 60_000 });
  await expect(requirement(page, "flight_time")).toContainText("At least 10 minutes of flight time");
  await idle(page);
  await expect(bomButton(page)).toContainText("€");
});

test("fly hunter: the request picks mission tests, each a requirement, replayed in the Missions pane", async ({ page }) => {
  await freshBench(page);
  await ask(page, "a fly hunter drone, incredibly fast, small and light, under 100 euros");
  await expect(page.getByText(/Missions · \d of 3 passed/)).toBeVisible({ timeout: 60_000 });
  await expect(requirement(page, "top_speed")).toContainText("Top speed at least 60 km/h");
  await expect(requirement(page, "chase_time")).toContainText("Mechanic");
  await idle(page);
  await page.locator('[data-target="tab:simulation"]').dispatchEvent("click");
  await page.locator('[data-target~="sim:missions"]').dispatchEvent("click");
  for (const mission of ["speed_run", "turn", "chase"]) await expect(page.locator(`[data-target="mission:${mission}"]`)).toBeVisible();
  await page.locator('[data-target="mission:chase"]').dispatchEvent("click");
  await expect(page.getByText(/Chase · (passed|failed)/)).toBeVisible();
  await expect(page.getByText("Distance to the fly")).toBeVisible();
});

test("racing drone: the hardware check passes, the controller trains on the missions, and the trained run decides", async ({ page }) => {
  // Training on the missions, the re-flight and 50 stress worlds take about a minute on the backend.
  test.setTimeout(240_000);
  await freshBench(page);
  await ask(page, "Build me a racing drone");
  await expect(page.getByText(/Missions · \d of 2 passed/)).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/On the missions, MuJoCo/).first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Missions · trained controller · 2 of 2 passed/)).toBeVisible({ timeout: 150_000 });
  await expect(page.getByText(/Reference controller: /).first()).toBeVisible();
  await expect(page.getByText(/the firmware writes exactly these gains/).first()).toBeVisible({ timeout: 60_000 });
  await idle(page, 120_000);
});

test("robot gripper from a chat request: the grip test holds and the BOM closes", async ({ page }) => {
  await freshBench(page);
  await ask(page, GRIPPER);
  await expect(bomButton(page)).toContainText("€", { timeout: 60_000 });
  await idle(page);
  await page.locator('[data-target="tab:simulation"]').dispatchEvent("click");
  await expect(page.getByText(/Run \d+ · holds/)).toBeVisible();
});

test("phone stand from scratch: the tap check fails, the fix makes it pass, a render shows", async ({ page }) => {
  await freshBench(page);
  await ask(page, STAND);
  const tap = requirement(page, "tap");
  await expect(tap).toBeVisible();
  // The run says that the first base tips over before it deepens it.
  await expect(page.getByText(/tips|tip over|tipped/i).first()).toBeVisible();
  await idle(page);
  await expect(tap).toHaveAttribute("data-state", "ok");
  await expect(bomButton(page)).toContainText("€");
  // The run is over, so no step is left running: the chat offers the next changes.
  await expect(page.locator('[data-target="follow_ups"]')).toBeVisible();
  await page.locator('[data-target~="look:render"]').first().dispatchEvent("click");
  await expect(page.getByText(/Studio|Recorded, Blender is offline/).first()).toBeVisible();
});

test("pause, resume and stop: the run holds between tool calls and Stop keeps the bench", async ({ page }) => {
  await freshBench(page);
  await ask(page, "Build me a racing drone");
  const controls = page.locator('[data-target="run_controls"]');
  await expect(controls).toContainText("Mechanic is working");
  await page.locator('[data-target="run_pause"]').click();
  await expect(controls).toContainText("Paused");
  const held = await page.request.get("/api/health");
  expect(((await held.json()) as { run: string }).run).toBe("paused");
  await page.locator('[data-target="run_resume"]').click();
  await expect(controls).toContainText("Mechanic is working");
  await page.locator('[data-target="run_stop"]').click();
  await expect(page.getByText("Stopped. Everything built so far stays on the bench.")).toBeVisible();
  await expect(controls).toBeHidden();
  await idle(page);
});
