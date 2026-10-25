import { expect, type Page } from "@playwright/test";

/** Each flow starts on a fresh bench: POST /api/reset through the Vite proxy, then the dashboard. */
export async function freshBench(page: Page, query = "") {
  const reset = await page.request.post("/api/reset", { data: {} });
  expect(reset.ok()).toBeTruthy();
  await page.goto(`/?mute${query ? `&${query}` : ""}`);
  await expect(page.locator('[data-target~="chat_input"]').first()).toBeVisible();
}

/** Types a request into the chat and sends it with Enter. */
export async function ask(page: Page, text: string) {
  const field = page.locator('[data-target~="chat_input"]').first();
  await field.focus();
  await field.fill(text);
  await field.press("Enter");
}

/** Waits until the backend has no run in flight. */
export async function idle(page: Page, timeout = 60_000) {
  await expect
    .poll(async () => ((await (await page.request.get("/api/health")).json()) as { busy?: boolean }).busy, { timeout, intervals: [250] })
    .toBe(false);
}

export const requirement = (page: Page, id: string) => page.locator(`[data-target~="requirement:${id}"]`);
export const bomButton = (page: Page) => page.locator('[data-target~="bom"]');
