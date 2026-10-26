// SolidCraft in the offline demo. The e2e backend runs with PAI_CAD_ENGINE=solidcraft, so "Build a four-bar linkage"
// builds SolidCraft's Chebyshev linkage from the library, writes its URDF and MJCF and drives them through the design's
// motion study in MuJoCo. The CAD tab shows the design as SolidCraft built it: its source, its parts, its slider and its
// script, and the slider rebuilds it through SolidCraft's timeline. Without solidcraft-cli on the machine
// (bash agent/scripts/setup_solidcraft.sh) Mechanic says so and the test skips.
import { expect, test } from "@playwright/test";
import { ask, freshBench, idle } from "./helpers";

test("solidcraft: a four-bar linkage builds, passes its MuJoCo check, and the CAD tab shows SolidCraft's design", async ({ page }) => {
  await freshBench(page);
  await ask(page, "Build a four-bar linkage in SolidCraft");
  const outcome = page.getByText(/MuJoCo drove Chebyshev cycle|SolidCraft is not installed/).first();
  await expect(outcome).toBeAttached({ timeout: 60_000 });
  test.skip(((await outcome.textContent()) ?? "").includes("not installed"), "solidcraft-cli is not installed on this machine");
  await expect(page.getByText(/all 4 joints moved, Coupler to rocker kept the loop closed/)).toBeVisible();
  await idle(page);

  // dispatchEvent: on a loaded machine the 3D canvas keeps the page busy, and a real click waits for it to settle.
  await page.locator('[data-target="tab:cad"]').dispatchEvent("click");
  await expect(page.locator('[data-target="tab:cad"]')).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("canvas").first()).toBeAttached();
  await expect(page.getByText("SolidCraft", { exact: true })).toBeVisible();
  for (const part of ["Ground", "Crank", "Coupler", "Rocker", "Tracer tip"]) await expect(page.getByText(part, { exact: true })).toBeVisible();
  await expect(page.getByText("89 × 90 × 16 mm")).toBeVisible();
  await expect(page.locator('[data-target~="param:unit_length"]')).toContainText("20.0 mm");

  await page.locator('[data-target~="cad_script"]').dispatchEvent("click");
  await expect(page.getByText("SolidCraft script", { exact: true })).toBeVisible();
  await expect(page.getByText(/"command": "joint.create"/).first()).toBeVisible();
  await page.getByRole("button", { name: "Close script" }).dispatchEvent("click");

  // The slider: SolidCraft rebuilds the linkage at a longer unit length and the picked pins follow.
  const slider = await page.request.post("/api/cad/params", { data: { name: "unit_length", value: 28 } });
  expect(slider.ok()).toBeTruthy();
  await expect(page.getByText("121 × 122 × 16 mm")).toBeVisible();
  await expect(page.locator('[data-target~="param:unit_length"]')).toContainText("28.0 mm");
});
