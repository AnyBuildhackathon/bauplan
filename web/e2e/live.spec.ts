// One live smoke against Claude: E2E_LIVE=1 and ANTHROPIC_API_KEY in the backend's environment or agent/.env.
import { expect, test } from "@playwright/test";
import { ask, freshBench, idle } from "./helpers";

test.skip(process.env.E2E_LIVE !== "1", "Live smoke runs only with E2E_LIVE=1 and a key");

test("live: a phone stand from scratch meets every requirement within 180 s", async ({ page }) => {
  test.setTimeout(240_000);
  const health = (await (await page.request.get("/api/health")).json()) as { mode?: string };
  expect(health.mode, "the backend has no ANTHROPIC_API_KEY").toBe("claude");
  await freshBench(page);
  const started = Date.now();
  await ask(page, "Design a phone stand for my desk");
  await expect(page.locator('[data-target~="requirements"]')).toContainText(/met/, { timeout: 120_000 });
  await idle(page, 180_000);
  expect(Date.now() - started).toBeLessThan(180_000);
  await expect(page.locator('[data-target~="requirements"]')).toContainText(/(\d+) of \1 met/);
});
