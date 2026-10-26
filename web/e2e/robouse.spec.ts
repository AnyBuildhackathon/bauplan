// Robo Use in the offline demo: after the gripper is built, "Test it in Robo Use" runs robouse_trial. The mock
// backend runs with Robo Use off (PAI_ROBOUSE_BIN=off), so the trial recorded on this same design stands in, and
// the Simulation tab's Robo Use pane shows its verdict, video, step track, robo requests and the hand's path.
import { expect, test } from "@playwright/test";
import { ask, freshBench, idle } from "./helpers";

test("robo use: the recorded trial shows its verdict, video, step track and the hand's path", async ({ page }) => {
  // The gripper story builds in FreeCAD and renders in Blender first.
  test.setTimeout(240_000);
  await freshBench(page);
  await ask(page, "Design a robot gripper that picks up a 200 g soda can, 66 mm wide");
  await expect(page.getByText("Version 1", { exact: false }).first()).toBeAttached({ timeout: 150_000 });
  await idle(page, 120_000);

  await ask(page, "Test it in Robo Use");
  const card = page.locator('[data-target~="trial:card"]');
  await expect(card).toContainText("Passed · reward 1.0");
  await expect(card).toContainText("Recorded earlier on this same design");
  await expect(card).toContainText("Reference 1.0 · No-op 0.0 · valid");
  await idle(page);
  // dispatchEvent: on a loaded machine the 3D canvas keeps the page busy, and a real click waits for it to settle.
  await card.getByRole("button", { name: "Watch video" }).dispatchEvent("click");
  await expect(page.locator('[data-target~="sim:robouse"]')).toHaveAttribute("aria-selected", "true");

  const pane = page.locator('[data-target="trial"]');
  const verdict = pane.locator('[data-target~="trial:verdict"]');
  await expect(verdict).toContainText("Passed · reward 1.0");
  await expect(verdict).toContainText("Put the cube in the bowl");
  await expect(verdict).toContainText("Recorded");
  await expect(verdict).toContainText("Reference 1.0 · No-op 0.0 · valid");

  // The recording, served from the session's files.
  const video = pane.locator('[data-target~="trial:video"] video');
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState), { timeout: 30_000 }).toBeGreaterThanOrEqual(2);
  expect(await video.evaluate((v: HTMLVideoElement) => v.duration)).toBeCloseTo(4.4, 1);
  expect(await video.evaluate((v: HTMLVideoElement) => v.videoWidth)).toBe(960);

  // The step track: one mark per robo request; the grip's mark jumps the video to where the fingers close.
  const marks = pane.locator('[data-target~="trial:mark"]');
  await expect(marks).toHaveCount(9);
  await video.evaluate((v: HTMLVideoElement) => v.pause());
  await marks.nth(2).dispatchEvent("click");
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.currentTime)).toBeCloseTo(1.333, 1);
  await expect(pane.locator('[data-target~="trial:track"]')).toContainText("3/9 · grip 1 --steps 25");

  const steps = pane.locator('[data-target~="trial:steps"]');
  await expect(steps).toContainText("robo grip 1 --steps 25");
  await expect(steps).toContainText("holding cube");
  await expect(steps).toContainText('robo done "the cube is in the bowl"');

  // The hand's path on AnyBuild's stage, and the contact force beside the requests.
  await expect(pane.locator('[data-target~="trial:path"] canvas')).toBeVisible();
  await expect(pane.locator('[data-target~="trial:force"]')).toContainText("peak 5.8 N");
});
