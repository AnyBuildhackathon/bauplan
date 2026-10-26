// The explode view (U12) on a saved sensor box: an open box with an insert in each corner post, a lid on top and a
// screw through each corner of the lid. The view bar's Explode switch is off by default; pressed, the parts glide
// apart along the ways they go on (the eight standard parts along their axes, the lid off the box's rim) and its
// slider sets how far. The section still cuts the exploded model, and a part added to Mechanic's message box says
// how the studio showed it, which offline Mechanic reads back.
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { ask, freshBench, idle } from "./helpers";

const ID = "e2e-explode";
// A saved project, as the library keeps one (agent/runs/library/<id>); removed again after the test.
const folder = fileURLToPath(new URL(`../../agent/runs/library/${ID}/`, import.meta.url));

const BASE = `W, D, H = P.get("width_mm", 60.0), P.get("depth_mm", 40.0), P.get("height_mm", 20.0)
wall = 2.0
body = Part.makeBox(W, D, H, Vector(-W / 2, -D / 2, 0)).cut(Part.makeBox(W - 2 * wall, D - 2 * wall, H, Vector(-W / 2 + wall, -D / 2 + wall, wall)))
for x in (-W / 2 + 5, W / 2 - 5):
    for y in (-D / 2 + 5, D / 2 - 5):
        body = body.fuse(Part.makeCylinder(4.0, H - wall, Vector(x, y, wall)))
shape = body
`;
const LID = 'shape = Part.makeBox(60, 40, P.get("thickness_mm", 3.0), Vector(-30, -20, 20))\n';
const CORNERS = (z: number) => [[25, 15, z], [-25, 15, z], [25, -15, z], [-25, -15, z]];

test.beforeAll(() => {
  rmSync(folder, { recursive: true, force: true });
  mkdirSync(folder, { recursive: true });
  writeFileSync(`${folder}base.py`, BASE);
  writeFileSync(`${folder}lid.py`, LID);
  const spec = {
    name: "Sensor box",
    function: "A small box for a sensor board, its lid screwed down at the four corners.",
    quote: "a small sensor box with a screwed lid, under 30 euros",
    requirements: [{ text: "Costs under 30 euros", check: "cost", max: 30, unit: "eur", quote: "under 30 euros" }],
    parts: [
      {
        id: "base", name: "Base", kind: "printed", material: "PETG", size_mm: [60, 40, 20], params: { width_mm: 60, depth_mm: 40, height_mm: 20 },
        description: "Open box 60 x 40 x 20 mm with a post for an M3 insert in each corner.",
        fasteners: [{ name: "Insert", kind: "insert", size: "M3 short", at: CORNERS(20) }],
      },
      {
        id: "lid", name: "Lid", kind: "printed", material: "PETG", size_mm: [60, 40, 3], position_mm: [0, 0, 21.5], params: { thickness_mm: 3 },
        description: "Flat lid on top of the base, screwed down at the four corners.",
        fasteners: [{ name: "Screw", kind: "screw", standard: "ISO 4762", size: "M3x8", at: CORNERS(23) }],
      },
    ],
  };
  const ref = {
    id: ID, name: "Sensor box to explode", summary: "Lid screwed into heat-set inserts.", kind: "project", saved_at: "2026-10-26T00:00:00Z",
    spec, scripts: { base: { file: "base.py", generated: true }, lid: { file: "lid.py", generated: true } }, picks: {}, checks: [],
  };
  writeFileSync(`${folder}reference.json`, JSON.stringify(ref, null, 2));
});

test.afterAll(() => rmSync(folder, { recursive: true, force: true }));

const viewBar = (page: Page) => page.getByRole("toolbar", { name: "View" });

test("the Explode switch pulls the sensor box apart along its assembly directions, its slider sets how far", async ({ page }) => {
  // Two FreeCAD parts, the assembly, the Blender render and the bill of materials: about a minute on a loaded machine.
  test.setTimeout(240_000);
  await freshBench(page, "view=library");
  await page.locator(`[data-target="library:${ID}"]`).dispatchEvent("click");
  await expect(page.getByText("Version 1 ·", { exact: false }).first()).toBeAttached({ timeout: 150_000 });
  await idle(page);
  // dispatchEvent: on a loaded machine the 3D canvas keeps the page busy, and a real click waits for it to settle.
  await page.locator('[data-target="tab:cad"]').dispatchEvent("click");
  await expect(page.locator('[data-target="tab:cad"]')).toHaveAttribute("aria-selected", "true");

  // Off by default; pressed, the parts come apart all the way and the popover says how each one leaves.
  const explode = viewBar(page).getByRole("button", { name: "Explode" });
  await expect(explode).toBeEnabled();
  await expect(explode).toHaveAttribute("aria-pressed", "false");
  await explode.click();
  await expect(explode).toHaveAttribute("aria-pressed", "true");
  await expect(explode).toContainText("100%");
  const dialog = page.getByRole("dialog", { name: "Explode" });
  const slider = dialog.getByRole("slider", { name: "Explode" });
  await expect(slider).toHaveValue("100");
  await expect(dialog.locator('[data-target="explode:ways"]')).toHaveText("Each part leaves the way it goes on: 8 along their axes, 1 off its face.");

  // The slider sets how far; the switch keeps the amount while it is off.
  await slider.fill("40");
  await expect(explode).toContainText("40%");
  await dialog.getByRole("button", { name: "Off" }).click();
  await expect(explode).toHaveAttribute("aria-pressed", "false");
  await expect(explode).not.toContainText("%");
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press("e");
  await expect(explode).toHaveAttribute("aria-pressed", "true");
  await expect(explode).toContainText("40%");

  // The section still cuts the exploded model.
  const section = viewBar(page).getByRole("button", { name: "Section" });
  await section.click();
  await expect(section).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator('[data-target="section:at"]')).toHaveText(/^-?\d+\.\d mm$/);
  await expect(explode).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("Escape");

  // A part picked on the exploded model goes to Mechanic saying so; offline he reads it back.
  await page.getByRole("tablist", { name: "Panels" }).getByRole("tab", { name: "Assembly", exact: true }).click();
  await page.getByRole("tree", { name: "Assembly" }).getByTitle("Select Lid").dispatchEvent("click");
  await page.locator('[data-target="part:attach"]').click();
  await ask(page, "Which way does this come off?");
  await expect(page.getByText("seen exploded 40 %").first()).toBeVisible({ timeout: 30_000 });
});
