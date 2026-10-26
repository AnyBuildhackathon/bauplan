// The "I have a 3D printer" flow: the button next to the prompt sets the printer, the backend
// gets it, and the offline phone stand picks materials from its filaments, runs FEM on the
// printed parts (the Stress pane) and prices them as filament on that printer.
import { expect, test } from "@playwright/test";
import { ask, freshBench, idle, requirement } from "./helpers";

test.afterEach(async ({ page }) => {
  // The printer is a backend-wide setting; the other flows run without one.
  await page.request.post("/api/settings", { data: { printer: null } });
});

test("3D printer: the prompt button sets the printer, the phone stand gets FEM and printer prices", async ({ page }) => {
  // The build with FreeCAD, MuJoCo and CalculiX may take the 180 s the idle wait below allows; the suite's 90 s would cut it short.
  test.setTimeout(240_000);
  await freshBench(page);
  await page.locator('[data-target="printer_button"]').first().click();
  await page.getByRole("switch", { name: /I have a 3D printer/ }).click();
  await expect
    .poll(async () => ((await (await page.request.get("/api/settings")).json()) as { printer?: { model: string } | null }).printer?.model, { timeout: 10_000 })
    .toBe("bambu-p1s");
  await expect(page.getByText(/256 × 256 × 256 mm bed/)).toBeVisible();
  // The choice stays in this browser.
  expect(await page.evaluate(() => localStorage.getItem("anybuild.printer"))).toContain("bambu-p1s");
  await page.keyboard.press("Escape");
  await page.locator('[data-target~="chat_input"]').first().click();

  await ask(page, "Design a phone stand for my desk");
  await idle(page, 180_000);
  await expect(page.getByText(/on your Bambu Lab P1S/).first()).toBeAttached();
  if (await page.getByText("No FEM for this part").count()) {
    // gmsh and CalculiX are not on this machine: the run says so and keeps the beam estimate.
    return;
  }
  await expect(requirement(page, "strength")).toBeAttached();
  // A real click: it pauses Director mode, which would otherwise follow the last event.
  await page.locator('[data-target="tab:simulation"]').click();
  await expect(page.locator('[data-target="tab:simulation"]')).toHaveAttribute("aria-selected", "true");
  await page.locator('[data-target~="sim:stress"]').first().click();
  await expect(page.getByRole("button", { name: /Back rest ·/ })).toBeVisible();
  await expect(page.getByText(/CalculiX/).first()).toBeVisible();
  // The FEM checked itself: held, the reactions balance the loads, the peak on a finer mesh.
  await expect(page.getByText(/Self-check: held against every motion, the reactions balance the loads/).first()).toBeVisible();
});
