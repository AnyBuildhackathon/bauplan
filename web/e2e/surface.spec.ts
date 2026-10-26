// The surface checks' colour layer on a real build: the mock phone stand runs to print_prep, whose
// surface checks reach the studio as the `analysis` event. The view bar's Surface menu lists what
// needs a fix per check, a check paints the model with its legend, the limit slider counts again, a
// click reads the value under the pointer, and a newer build puts the layer away until it is checked again.
import { expect, test, type Page } from "@playwright/test";
import type { AgentEvent } from "../src/events/types";
import { ask, freshBench, idle } from "./helpers";

const STAND = "Design a phone stand for my desk";

const viewBar = (page: Page) => page.getByRole("toolbar", { name: "View" });
const legend = (page: Page) => page.locator('[data-target="surface:legend"]');

async function choose(page: Page, label: RegExp) {
  await viewBar(page).getByRole("button", { name: "Surface checks" }).click();
  await page.getByRole("menuitemradio", { name: label }).click();
}

test("the phone stand's surface checks paint the model, count at a moved limit and read a clicked spot", async ({ page }) => {
  // The whole mock build runs first: CadQuery or FreeCAD, the checks, Blender's fallback and print_prep.
  test.setTimeout(240_000);
  await freshBench(page);
  await ask(page, STAND);
  await idle(page, 200_000);
  const surface = viewBar(page).getByRole("button", { name: "Surface checks" });
  await expect(surface).toBeEnabled();

  // The menu says what needs a fix at Mechanic's limits: the back rest printed flat hangs over, nothing else.
  await surface.click();
  await expect(page.getByRole("menuitemradio", { name: "Off" })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByRole("menuitemradio", { name: /^Overhang \d+(\.\d)? cm²$/ })).toBeVisible();
  await expect(page.getByRole("menuitemradio", { name: "Wall thickness none" })).toBeVisible();
  await expect(page.getByRole("menuitemradio", { name: "Clearance none" })).toBeVisible();
  await page.getByRole("menuitemradio", { name: /^Overhang/ }).click();

  await expect(legend(page)).toBeVisible();
  await expect(legend(page)).toContainText("Overhang");
  await expect(legend(page)).toContainText("Printed flat");
  await expect(legend(page)).toContainText("On the bed");
  await expect(page.locator('[data-target="surface:area"]')).toHaveText(/^\d+(\.\d)? cm² over 45°$/);
  await expect(surface).toHaveAttribute("aria-expanded", "false");

  // The back rest leans at 65 degrees: past a 70 degree limit nothing hangs over; Mechanic's limit comes back.
  await legend(page).getByRole("slider", { name: "Overhang limit" }).fill("70");
  await expect(page.locator('[data-target="surface:area"]')).toHaveText("nothing over 70°");
  await legend(page).getByRole("button", { name: "Back to Mechanic's 45°" }).click();
  await expect(page.locator('[data-target="surface:area"]')).toHaveText(/cm² over 45°$/);

  // Walls: only the knife edge where the slanted back rest is cut flat is red, and that needs no fix.
  await choose(page, /^Wall thickness/);
  await expect(page.locator('[data-target="surface:area"]')).toHaveText("nothing to fix");
  await expect(page.locator('[data-target="surface:soft"]')).toContainText("red at sharp edges and specks: no fix needed");

  // A click on the model reads the wall there; the camera frames the model in the middle of the canvas.
  const canvas = page.locator('[data-target~="viewport"] canvas');
  const box = (await canvas.boundingBox())!;
  const picked = page.locator('[data-target="surface:picked"]');
  for (const [dx, dy] of [[0, 0], [0, 0.08], [-0.06, 0.04], [0.06, 0.04], [0, -0.06], [-0.1, 0.1], [0.1, 0.1]]) {
    const at = { clientX: box.x + box.width * (0.5 + dx), clientY: box.y + box.height * (0.5 + dy) };
    await canvas.dispatchEvent("pointerdown", { ...at, button: 0, pointerId: 1, isPrimary: true });
    await canvas.dispatchEvent("pointerup", { ...at, button: 0, pointerId: 1, isPrimary: true });
    if (await picked.isVisible()) break;
  }
  await expect(picked).toHaveText(/^\d+\.\d\d mm on (Base plate|Back rest) at \(-?\d+\.\d, -?\d+\.\d, -?\d+\.\d\) mm$/);

  // A newer build of the model (a slider, cad_update) is not what was measured: the layer goes until it is checked again.
  await page.evaluate(async () => {
    const module = "/src/events/store.ts";
    const { useSession } = await import(module);
    const cad = useSession.getState().cad;
    useSession.getState().apply({ ...cad, glb_url: cad.glb_url.replace(/build=\d+/, "build=999") } as AgentEvent);
  });
  await expect(legend(page)).toHaveCount(0);
  await expect(surface).toBeDisabled();
  await expect(surface).toHaveAttribute("title", /earlier build/);
});
