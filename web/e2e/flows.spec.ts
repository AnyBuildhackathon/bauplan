// The stage flows in mock mode: no key, no FreeCAD or Blender needed (CadQuery and the recorded still stand in).
import { expect, test } from "@playwright/test";
import { ask, bomButton, freshBench, idle, requirement, timeline } from "./helpers";

const GRIPPER = "Design a robot gripper that picks up a 200 g soda can, 66 mm wide";
const STAND = "Design a phone stand for my desk";

test("drone reference: Library, Rebuild, v1 with every check met", async ({ page }) => {
  await freshBench(page, "view=library");
  await page.locator('[data-target="library:micro-drone"]').dispatchEvent("click");
  await expect(page.locator('[data-target="library_rebuild"]')).toBeEnabled();
  await page.locator('[data-target="library_rebuild"]').dispatchEvent("click");
  // The mock rebuild takes about 30 s on a loaded machine, as long as the default expect timeout.
  await expect(timeline(page)).toContainText("v1", { timeout: 60_000 });
  await expect(page.locator('[data-target~="requirements"]')).toContainText(/(\d+) of \1 met/);
  await expect(bomButton(page)).toContainText("€");
  await idle(page);
  // dispatchEvent: on a loaded machine the 3D canvas keeps the page busy, and a real click waits for it to settle.
  await page.locator('[data-target="tab:cad"]').dispatchEvent("click");
  await expect(page.locator('[data-target="tab:cad"]')).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("canvas").first()).toBeAttached();
});

test("review: Start and End on the timeline rebuild v2, the question closes by its default", async ({ page }) => {
  // Continues the bench of the drone test; a fresh page replays the backlog.
  await page.goto("/?mute");
  await expect(timeline(page)).toContainText("v1");
  await page.locator('[data-target="meeting_end"]').dispatchEvent("click");
  await expect(page.locator('[data-target="meeting_end"]')).toHaveText("End");
  await page.locator('[data-target="meeting_end"]').dispatchEvent("click");
  // The flight-time question opens and closes on its own after PAI_ASK_TIMEOUT_S.
  await expect(timeline(page)).toContainText("v2", { timeout: 45_000 });
  await idle(page);
  // v2 only builds after the question closed; its card stays in the chat with the default marked.
  await expect(page.locator('[data-target~="question"]').first()).toBeAttached();
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
