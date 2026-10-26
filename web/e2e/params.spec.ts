// The parameter contract in the CAD tab. The phone stand's scripts declare their parameters in PARAMS
// (agent/src/pai_agent/part_params.py), so every slider has its declared label, range, step and unit, and a slider
// move is the user's value: FreeCAD builds the part with it and a value outside the range is refused.
import { expect, test } from "@playwright/test";
import { ask, freshBench, idle } from "./helpers";

test("phone stand: the CAD sliders come from the scripts' PARAMS, and a slider move rebuilds the part", async ({ page }) => {
  await freshBench(page);
  await ask(page, "Design a phone stand for my desk");
  await idle(page);

  const cadTab = page.locator('[data-target="tab:cad"]');
  // dispatchEvent: on a loaded machine the 3D canvas keeps the page busy, and a real click waits for it to settle.
  await cadTab.dispatchEvent("click");
  await expect(cadTab).toHaveAttribute("aria-selected", "true");
  const depth = page.locator('[data-target~="param:base.depth_mm"]');
  await expect(depth).toContainText("Base plate · Depth");
  await expect(depth).toContainText("110 mm");
  for (const [name, value] of [["min", "40"], ["max", "160"], ["step", "1"]]) await expect(depth.getByRole("slider")).toHaveAttribute(name, value);
  const thickness = page.locator('[data-target~="param:base.thickness_mm"]');
  await expect(thickness.getByRole("slider")).toHaveAttribute("step", "0.5");
  await expect(thickness).toContainText("5.0 mm");
  const angle = page.locator('[data-target~="param:back-rest.angle_deg"]');
  await expect(angle).toContainText("Back rest · Lean angle");
  await expect(angle).toContainText("65°");

  // The call the slider makes: the base is built 100 mm wide, and the checks run again.
  const moved = await page.request.post("/api/cad/params", { data: { name: "base.width_mm", value: 100 } });
  expect(moved.ok()).toBeTruthy();
  await idle(page);
  await cadTab.dispatchEvent("click");
  await expect(page.locator('[data-target~="param:base.width_mm"]')).toContainText("100 mm");
  await expect(page.getByText("100 × 110 × 154 mm")).toBeVisible();
  const refused = await page.request.post("/api/cad/params", { data: { name: "base.width_mm", value: 200 } });
  expect(refused.status()).toBe(400);
  expect(await refused.text()).toContain("base.width_mm must be between 60 and 140.");
});
