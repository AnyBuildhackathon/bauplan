// Standard parts in the studio: a saved project whose lid is screwed into heat-set inserts builds through
// the normal tools (FreeCAD, or CadQuery without it). The Assembly tab lists the screws and inserts under
// the part that holds them, ready to hide with it, and the bill of materials names them by their standard.
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { bomButton, freshBench, idle } from "./helpers";

const ID = "e2e-fasteners";
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
    id: ID, name: "Sensor box with a screwed lid", summary: "Lid screwed into heat-set inserts.", kind: "project", saved_at: "2026-10-26T00:00:00Z",
    spec, scripts: { base: { file: "base.py", generated: true }, lid: { file: "lid.py", generated: true } }, picks: {}, checks: [],
  };
  writeFileSync(`${folder}reference.json`, JSON.stringify(ref, null, 2));
});

test.afterAll(() => rmSync(folder, { recursive: true, force: true }));

test("a lid's screws and the base's inserts: in the Assembly tab under their part, and in the bill of materials", async ({ page }) => {
  // Two FreeCAD parts, the assembly, the Blender render and the bill of materials: about a minute on a loaded machine.
  test.setTimeout(180_000);
  await freshBench(page, "view=library");
  await page.locator(`[data-target="library:${ID}"]`).dispatchEvent("click");
  await expect(page.getByText("Version 1 ·", { exact: false }).first()).toBeAttached({ timeout: 120_000 });
  await idle(page);

  await page.getByRole("tablist", { name: "Panels" }).getByRole("tab", { name: "Assembly", exact: true }).click();
  const panel = page.getByRole("tabpanel", { name: "Assembly" });
  const tree = page.getByRole("tree", { name: "Assembly" });
  await expect(tree).toContainText("ISO 4762 M3x8 ×4 (hardware)");
  await expect(tree).toContainText("Heat-set insert ruthex M3x4 ×4 (hardware)");
  // Two printed parts and two kinds of standard parts; the parts that hold screws still count as parts.
  await expect(panel).toContainText("4 parts");
  // Once the model has loaded, a standard part's row stands for its four pieces in it.
  await expect(page.getByRole("button", { name: "Hide ISO 4762 M3x8 ×4 (hardware)" })).toBeVisible();
  // Hiding the lid hides the screws it holds: the lid and four screws.
  await page.getByRole("button", { name: "Hide Lid" }).dispatchEvent("click");
  await expect(panel).toContainText("4 parts · 5 hidden");

  await bomButton(page).first().dispatchEvent("click");
  const bom = page.getByRole("dialog", { name: "Bill of materials" });
  await expect(bom).toContainText("ISO 4762 M3x8 socket head cap screw");
  await expect(bom).toContainText("Heat-set insert ruthex M3x4 (GE-M3Sx40-002)");
});
