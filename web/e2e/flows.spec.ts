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
