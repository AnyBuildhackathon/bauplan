// Settings → Check adapters: the dialog lists the engine behind every check from
// GET /api/adapters, grouped in Mechanics, Electronics, Simulation and Manufacturing, each one
// installed or not, with an install hint for every missing one. Which engines this machine has
// does not matter: the dialog must say exactly what the backend found.
import { expect, test } from "@playwright/test";
import { freshBench } from "./helpers";

interface Adapter {
  id: string;
  domain: string;
  remote: boolean;
  available: boolean | null;
  install_hint: string;
}

const label = (a: Adapter) => (a.available ? (a.remote ? "Connected" : "Installed") : a.remote ? "Offline" : "Missing");

test("Check adapters: every engine by domain, installed or missing, with install hints", async ({ page }) => {
  const adapters = (await (await page.request.get("/api/adapters")).json()) as Adapter[];
  expect(new Set(adapters.map((a) => a.domain))).toEqual(new Set(["mechanics", "electronics", "simulation", "manufacturing"]));

  await freshBench(page);
  await page.locator('[data-target="settings"]').click();
  await page.getByRole("button", { name: /^Check adapters/ }).click();
  const dialog = page.getByRole("dialog", { name: "Check adapters" });
  await expect(dialog).toBeVisible();
  // The Settings panel closed behind it.
  await expect(page.getByRole("button", { name: /^AnyBuild Bench results/ })).toBeHidden();

  for (const name of ["Mechanics", "Electronics", "Simulation", "Manufacturing"]) {
    await expect(dialog.getByRole("heading", { name, exact: true })).toBeVisible();
  }
  await expect(dialog.locator("[data-adapter]")).toHaveCount(adapters.length);
  const installed = adapters.filter((a) => a.available).length;
  await expect(dialog.getByText(`${installed} of ${adapters.length} available.`)).toBeVisible();
  for (const adapter of adapters.filter((a) => a.available !== null)) {
    const row = dialog.locator(`[data-adapter="${adapter.id}"]`);
    await expect(row.getByText(label(adapter), { exact: true })).toBeVisible();
    await expect(row.locator("[data-hint]")).toHaveCount(adapter.available ? 0 : 1);
  }

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("Check adapters: ?adapters opens the dialog and a click outside closes it", async ({ page }) => {
  await freshBench(page, "adapters");
  const dialog = page.getByRole("dialog", { name: "Check adapters" });
  await expect(dialog.locator("[data-adapter]").first()).toBeVisible();
  await page.mouse.click(8, 8);
  await expect(dialog).toBeHidden();
});
