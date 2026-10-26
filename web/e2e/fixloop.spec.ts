// The fix loop in the offline demo: "Gripper that puts a 400 g cube into a bowl" builds v1, and Robo Use, here the trial
// recorded on exactly that design (PAI_ROBOUSE_BIN=off), drops the cube in the carry although AnyBuild's own grip test
// passes it. Mechanic offers three fixes as a question; nobody answers, so its default (the DS3218 servo) becomes v2,
// which Robo Use passes. The comparison Mechanic opens, the Versions tab and the chat show both verdicts.
import { expect, test, type Page } from "@playwright/test";
import { ask, freshBench, idle } from "./helpers";

const rail = (page: Page, name: string) => page.getByRole("tablist", { name: "Panels" }).getByRole("tab", { name, exact: true });

test("fix loop: Robo Use fails v1, the default fix passes as v2, and the versions show both verdicts", async ({ page }) => {
  // The gripper story builds in FreeCAD and renders in Blender twice.
  test.setTimeout(300_000);
  await freshBench(page);
  await ask(page, "Gripper that puts a 400 g cube into a bowl");

  // v1's verdict, then the question with the fixes; nobody answers within PAI_ASK_TIMEOUT_S, so its default builds v2.
  const first = page.locator('[data-target~="trial:card"]').first();
  await expect(first).toContainText("Failed · reward 0.0", { timeout: 180_000 });
  await expect(first).toContainText("fell out during the carry");
  const question = page.locator('[data-target~="question"]', { hasText: "Which fix goes into v2?" });
  await expect(question).toBeVisible();
  await idle(page, 180_000);
  await expect(question).toContainText("DS3218 servo, 19 kg cm: grip safety 4.3x, +7.00 €");

  // Mechanic opens the comparison: v1 with Robo Use 0 next to v2 with Robo Use 1, and the verdicts lead the table.
  const compare = page.locator('[data-target="compare"]');
  await expect(compare).toBeVisible();
  for (const [n, reward] of [[1, 0], [2, 1]]) {
    const verdict = compare.locator(`[data-target~="version:${n}:verdict"]`);
    await expect(verdict).toContainText(`Robo Use ${reward}`);
    await expect(verdict).toContainText("recorded");
  }
  const verdictRow = compare.locator('[data-target="diff:verdict:robouse"]');
  await expect(verdictRow).toContainText("failed · reward 0");
  await expect(verdictRow).toContainText("passed · reward 1");
  await expect(verdictRow).toContainText("+1");
  await expect(compare.locator("tbody tr").first()).toContainText("Own test");
  await expect(compare.locator('[data-target="diff:part:servo"]')).toContainText("DSSERVO DS3218 20 kg servo");

  // The Versions tab: each version with its own test and its verdict side by side, v2 as the fix.
  await rail(page, "Versions").click();
  const v1 = page.locator('[data-target="version:1"]');
  const v2 = page.locator('[data-target="version:2"]');
  await expect(v1.locator('[data-target~="version:1:own"]')).toHaveText("Own test passed");
  await expect(v1.locator('[data-target~="version:1:verdict"]')).toContainText("Robo Use 0");
  await expect(v2.locator('[data-target~="version:2:verdict"]')).toContainText("Robo Use 1");
  await expect(v2).toContainText("Fix for Robo Use: DS3218 servo");
  await expect(v2).toContainText("25.64 €");

  // In the chat, v2's card names the verdict that flipped, and Mechanic says both.
  await rail(page, "Mechanic").click();
  await expect(page.getByText("Robo Use scores v1 0 and v2 1", { exact: false })).toBeVisible();
});
