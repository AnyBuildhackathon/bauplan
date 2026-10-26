// Studio notes to Mechanic (U6) and the section view (U8) on a real build: the mock phone stand runs, the
// section cuts it across X, Y or Z from the view bar, and the person points at things in the studio, which
// land as chips in Mechanic's message box: a part with the face and point clicked (also on a cut face), a
// measurement, a marking drawn on the view and a CAD parameter. Sent with a line of text they ride under the
// message, and offline Mechanic reads each one back, a selected part with the FreeCAD script lines that build it.
import { expect, test, type Locator, type Page } from "@playwright/test";
import { ask, freshBench, idle } from "./helpers";

const STAND = "Design a phone stand for my desk";

const panel = (page: Page) => page.locator('[data-target="panel"]');
const draft = (page: Page) => panel(page).locator('[data-target="notes:draft"]');
const canvas = (page: Page) => page.locator('[data-target~="viewport"] canvas').first();
const viewBar = (page: Page) => page.getByRole("toolbar", { name: "View" });

/** Clicks spots of the canvas (fractions of its size) until `until` shows. */
async function clickModel(page: Page, until: Locator, spots: [number, number][]) {
  const box = (await canvas(page).boundingBox())!;
  for (const [x, y] of spots) {
    await page.mouse.click(box.x + box.width * x, box.y + box.height * y);
    if (await until.isVisible()) return;
  }
  throw new Error("no click on the model showed " + until.toString());
}

/** A studio key, with no text field holding the focus (adding a note focuses Mechanic's message box). */
async function studioKey(page: Page, key: string) {
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press(key);
}

async function showTab(page: Page, tab: "modell" | "cad") {
  // dispatchEvent: on a loaded machine the 3D canvas keeps the page busy, and a real click waits for it to settle.
  await page.locator(`[data-target="tab:${tab}"]`).dispatchEvent("click");
  await expect(page.locator(`[data-target="tab:${tab}"]`)).toHaveAttribute("aria-selected", "true");
}

test("the section view cuts the phone stand, and parts, a measurement, a marking and a parameter go to Mechanic as notes", async ({ page }) => {
  test.setTimeout(300_000);
  await freshBench(page);
  await ask(page, STAND);
  await idle(page, 240_000);
  await showTab(page, "modell");

  // The section is off by default; pressed, it cuts across Z at the middle of the model and shows where.
  const section = viewBar(page).getByRole("button", { name: "Section" });
  await expect(section).toHaveAttribute("aria-pressed", "false");
  await section.click();
  await expect(section).toHaveAttribute("aria-pressed", "true");
  const dialog = page.getByRole("dialog", { name: "Section" });
  await expect(dialog.getByRole("tab", { name: "Z" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator('[data-target="section:at"]')).toHaveText(/^\d+\.\d mm$/);
  await expect(section).toContainText(/Z \d+(\.\d)?/);
  // Across X the phone stand is symmetric: the middle is X = 0, and the slider moves the cut.
  await dialog.getByRole("tab", { name: "X" }).click();
  await expect(page.locator('[data-target="section:at"]')).toHaveText("0.0 mm");
  await dialog.getByRole("slider", { name: "Section along X" }).fill("-20");
  await expect(page.locator('[data-target="section:at"]')).toHaveText("-20.0 mm");
  await expect(section).toContainText("X -20.0");
  // The half facing the camera goes; Flip keeps the other one, and back.
  const kept = dialog.locator("p");
  await expect(kept).toHaveText(/Keeps the half below the cut/);
  await dialog.getByRole("button", { name: "Flip" }).click();
  await expect(kept).toHaveText(/Keeps the half above the cut/);
  await dialog.getByRole("button", { name: "Flip" }).click();
  await expect(kept).toHaveText(/Keeps the half below the cut/);

  // Looking at the cut from the side (key 2), a click on the base plate's cut face is a point inside the part.
  await studioKey(page, "Escape");
  await studioKey(page, "2");
  // The camera takes about half a second to the side view.
  await page.waitForTimeout(800);
  const attachPart = page.locator('[data-target="part:attach"]');
  await clickModel(page, attachPart, [[0.6, 0.815], [0.55, 0.815], [0.65, 0.81]]);
  await attachPart.click();
  const selection = draft(page).locator('[data-target="note:selection"]');
  await expect(selection).toHaveCount(1);
  await expect(selection).toHaveAttribute("title", /^Selection: Base plate inside, on the cut, at \(-20\.0, -?\d+\.\d, -?\d+\.\d\) mm$/);

  // S takes the cut away, and brings it back.
  await studioKey(page, "s");
  await expect(section).toHaveAttribute("aria-pressed", "false");
  await studioKey(page, "s");
  await expect(section).toHaveAttribute("aria-pressed", "true");
  await studioKey(page, "s");
  await studioKey(page, "4");
  await page.waitForTimeout(800);

  // A measurement between two points on the model.
  await page.locator('[data-target="tool:measure"]').click();
  const box = (await canvas(page).boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.42, box.y + box.height * 0.62);
  await page.mouse.click(box.x + box.width * 0.56, box.y + box.height * 0.7);
  const attachMeasure = page.locator('[data-target="measure:attach"]');
  await expect(attachMeasure).toBeVisible();
  await attachMeasure.click();
  await expect(draft(page).locator('[data-target="note:measure"]')).toHaveText(/^\d+(\.\d)? mm/);
  await studioKey(page, "Escape");

  // A marking: strokes drawn on the view, attached as the picture of the view with them on it.
  await page.locator('[data-target="tool:mark"]').click();
  const attachMarking = page.locator('[data-target="markup:attach"]');
  await expect(attachMarking).toBeDisabled();
  const ink = (await page.locator('[data-target="markup:canvas"]').boundingBox())!;
  await page.mouse.move(ink.x + ink.width * 0.4, ink.y + ink.height * 0.45);
  await page.mouse.down();
  for (let a = 0; a <= 6.4; a += 0.4) await page.mouse.move(ink.x + ink.width * (0.48 + 0.08 * Math.cos(a)), ink.y + ink.height * (0.45 + 0.07 * Math.sin(a)));
  await page.mouse.up();
  await attachMarking.click();
  const marking = draft(page).locator('[data-target="note:markup"]');
  await expect(marking).toContainText("Marking");
  await expect(marking.locator("img")).toHaveAttribute("src", /markup-1\.png/);
  await expect(page.locator('[data-target="tool:select"]')).toHaveAttribute("aria-pressed", "true");

  // A CAD parameter.
  await showTab(page, "cad");
  await page.locator('[data-target="param:attach:base.width_mm"]').click();
  await expect(draft(page).locator('[data-target="note:param"]')).toHaveText(/^Base plate · (W|w)idth 80 mm/);

  // Sent with a line of text: the chips go under the message and leave the box.
  const field = panel(page).locator('[data-target~="chat_input"]');
  await field.fill("Make the base wider where I marked it");
  await field.press("Enter");
  await expect(draft(page)).toHaveCount(0);
  const sent = panel(page).locator('[data-target="notes:sent"]').last();
  await expect(sent.locator("[data-target^='note:']")).toHaveCount(4);
  await expect(sent.locator('[data-target="note:markup"]')).toHaveAttribute("href", /markup-1\.png/);

  // Offline Mechanic reads each note back; with FreeCAD on this machine a selected part names its script lines.
  const freecad = ((await (await page.request.get("/api/adapters")).json()) as { id: string; available: boolean }[]).find((row) => row.id === "freecad")?.available;
  const reply = panel(page).getByText("I read your notes:").locator("xpath=..");
  await expect(reply).toContainText("inside on the section's cut at (");
  await expect(reply).toContainText(/\d+(\.\d)? mm from .+ to .+, \d+(\.\d)?° up/);
  await expect(reply).toContainText("Your marking on the Model view");
  await expect(reply).toContainText(/Base plate · (W|w)idth at 80 mm/);
  if (freecad) await expect(reply).toContainText(/part-[a-z-]+\.py lines \d+(-\d+)?/);
  await expect(reply).toContainText("Offline I can only read them back.");
});
