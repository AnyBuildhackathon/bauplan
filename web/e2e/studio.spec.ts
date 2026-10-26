// The studio layout: the canvas on the left with its view bar, tool rail and zoom pill, and
// Mechanic's panel on the right with its tabs. Like director.spec.ts the events go straight
// into the session store, so no build has to run.
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import type { AgentEvent } from "../src/events/types";
import { freshBench } from "./helpers";

async function emit(page: Page, event: AgentEvent) {
  await page.evaluate(async (ev) => {
    const module = "/src/events/store.ts";
    const { useSession } = await import(module);
    useSession.getState().apply(ev);
  }, event);
}

/** Marks the end of the event stream's backlog (its `replayed` event) on the window, for `streamed`. */
function watchBacklog(page: Page) {
  return page.addInitScript(() => {
    const Native = window.EventSource;
    window.EventSource = class extends Native {
      constructor(url: string | URL, init?: EventSourceInit) {
        super(url, init);
        this.addEventListener("message", (m) => {
          if (/"type":\s*"replayed"/.test(String(m.data))) Object.assign(window, { replayed: true });
        });
      }
    };
  });
}

/** Waits for the backlog: its leading `reset` would wipe whatever the test put in the store before it. */
const streamed = (page: Page) => page.waitForFunction(() => "replayed" in window);

/** A fresh bench with a drone on it: the product and one line from Mechanic, so the start screen gives way. */
async function droneBench(page: Page, reload = false) {
  if (reload) await page.reload();
  else {
    await watchBacklog(page);
    await freshBench(page);
  }
  await streamed(page);
  await emit(page, { type: "product", id: "drone", label: "Micro drone" });
  await emit(page, { type: "chat", role: "agent", text: "Here is the drone." });
  await expect(page.getByRole("toolbar", { name: "View" })).toBeVisible();
}

const rail = (page: Page, name: string) => page.getByRole("tablist", { name: "Panels" }).getByRole("tab", { name, exact: true });
const viewBar = (page: Page) => page.getByRole("toolbar", { name: "View" });

test("the Grid and Labels switches toggle and are remembered after a reload", async ({ page }) => {
  await droneBench(page);
  const grid = viewBar(page).getByRole("button", { name: "Grid", exact: true });
  const labels = viewBar(page).getByRole("button", { name: "Labels", exact: true });
  await expect(grid).toHaveAttribute("aria-pressed", "true");
  await expect(labels).toHaveAttribute("aria-pressed", "false");
  await grid.click();
  await labels.click();
  await expect(grid).toHaveAttribute("aria-pressed", "false");
  await expect(labels).toHaveAttribute("aria-pressed", "true");
  const stored = await page.evaluate(() => JSON.parse(localStorage.getItem("anybuild.studio") ?? "{}"));
  expect(stored).toMatchObject({ grid: false, labels: true, ortho: false });

  // A reload starts an empty bench; the switches come back as they were left.
  await droneBench(page, true);
  await expect(grid).toHaveAttribute("aria-pressed", "false");
  await expect(labels).toHaveAttribute("aria-pressed", "true");

  // The keys do the same while no text field has the focus.
  await page.locator("header").click();
  await page.keyboard.press("g");
  await page.keyboard.press("l");
  await expect(grid).toHaveAttribute("aria-pressed", "true");
  await expect(labels).toHaveAttribute("aria-pressed", "false");
});

test("Mechanic's panel sits right of the studio; its tabs show versions, assembly, joints and checks and keep the chat draft", async ({ page }) => {
  await droneBench(page);
  const canvas = page.locator('[data-target~="viewport"]');
  const panel = page.locator('[data-target="panel"]');
  const studio = (await canvas.boundingBox())!;
  expect((await panel.boundingBox())!.x).toBeGreaterThan(studio.x + studio.width);

  // The start screen's box fades out over the bench for a moment; the chat's own box is in the panel.
  const input = panel.locator('[data-target~="chat_input"]');
  await input.fill("Make the arms longer");

  await rail(page, "Versions").click();
  await expect(page.getByText("No versions yet")).toBeVisible();
  await emit(page, {
    type: "version", n: 1, label: "Build a micro drone",
    weight_g: 40, thrust_to_weight: 2, flight_time_min: 8, price_eur: 60,
    sim: "pass", parts: { battery: "550 mAh" }, diff: [], summary: "First build", product: "drone",
  });
  await expect(page.locator('[data-target="version:1"]')).toContainText("Build a micro drone");
  await expect(page.locator('[data-target="version:1"]')).toContainText("current");

  await rail(page, "Checks").click();
  await emit(page, { type: "requirement", id: "budget", text: "Total price under €120", source_quote: "under 120 euros", met: true, source: "user" });
  await expect(page.getByRole("tabpanel", { name: "Checks" })).toContainText("Total price under €120");
  await expect(page.getByRole("tabpanel", { name: "Checks" })).toContainText("1 of 1 met");

  await rail(page, "Joints").click();
  await expect(page.getByText("No joints yet")).toBeVisible();

  await rail(page, "Assembly").click();
  await emit(page, {
    type: "cad", source: "freecad", params: {}, glb_url: null, stl_url: null, step_url: null, view_png_url: null,
    tree: [{ id: "drone", label: "Drone", children: [{ id: "motors", label: "Motors ×4 · 1103 15000KV", children: [] }, { id: "battery", label: "Battery and strap", children: [] }] }],
  });
  const tree = page.getByRole("tree", { name: "Assembly" });
  await expect(tree).toContainText("Motors ×4");
  await expect(tree).toContainText("1103 15000KV");
  await expect(page.getByRole("tabpanel", { name: "Assembly" })).toContainText("2 parts");

  // The chat kept its draft behind the other tabs.
  await rail(page, "Mechanic").click();
  await expect(input).toBeVisible();
  await expect(input).toHaveValue("Make the arms longer");

  // Pressing the open tab closes the panel and the studio takes the room; any tab opens it again.
  await rail(page, "Mechanic").click();
  await expect(input).toBeHidden();
  await expect.poll(async () => (await canvas.boundingBox())!.width).toBeGreaterThan(studio.width + 300);
  await rail(page, "Mechanic").click();
  await expect(input).toHaveValue("Make the arms longer");
});

test("the view bar, the tool rail, the zoom pill and the parts panel", async ({ page }) => {
  await droneBench(page);
  const bar = viewBar(page);

  await bar.getByRole("button", { name: "Views" }).click();
  for (const view of ["Front", "Side", "Top", "Reset"]) await expect(page.getByRole("menuitem", { name: new RegExp(`^${view}`) })).toBeVisible();
  await page.getByRole("menuitem", { name: /^Top/ }).click();
  await expect(page.getByRole("menu")).toHaveCount(0);

  await bar.getByRole("tab", { name: "Ortho" }).click();
  await expect(bar.getByRole("tab", { name: "Ortho" })).toHaveAttribute("aria-selected", "true");

  await bar.getByRole("button", { name: "Explode" }).click();
  await page.getByRole("slider", { name: "Explode" }).fill("60");
  await expect(bar.getByRole("button", { name: "Explode" })).toContainText("60%");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("slider", { name: "Explode" })).toHaveCount(0);

  const tools = page.getByRole("toolbar", { name: "Tools" });
  await tools.getByRole("button", { name: "Measure (M)" }).click();
  await expect(page.getByText("Click two points on the model")).toBeVisible();
  // Escape with no point set leaves the tool.
  await page.keyboard.press("Escape");
  await expect(tools.getByRole("button", { name: "Select (V)" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("Click two points on the model")).toHaveCount(0);

  const zoom = page.getByRole("toolbar", { name: "Zoom" });
  for (const name of ["Zoom in", "Zoom out", "Fit the model"]) await expect(zoom.getByRole("button", { name })).toBeVisible();
  await zoom.getByRole("button", { name: "Zoom in" }).click();

  await tools.getByRole("button", { name: "Parts (P)" }).click();
  const parts = page.getByRole("dialog", { name: "Parts" });
  // Every word counts, in any order: the LAVA II 1S is a "lava 1s" too.
  await parts.getByRole("textbox", { name: "Search parts and builds" }).fill("lava 1s");
  await expect(parts.locator('[data-target^="part:"]')).toHaveCount(4);
  await parts.locator('[data-target="part:betafpv-lava-1s-680"]').click();
  await expect(parts.locator('[data-target="parts:picked"]')).toContainText("80 × 15 × 6.5 mm");
  await parts.getByRole("button", { name: "Ask Mechanic to use it" }).click();
  await expect(page.locator('[data-target="panel"] [data-target~="chat_input"]')).toHaveValue("Use the BetaFPV LAVA II 1S 680mAh 95C as the battery.");
});

test("the parts panel's catalog lists exactly the part models in web/public/models/parts", () => {
  const dir = fileURLToPath(new URL("../public/models/parts/", import.meta.url));
  const models = readdirSync(dir).filter((f) => f.endsWith(".glb")).sort();
  const index = (JSON.parse(readFileSync(`${dir}index.json`, "utf8")) as { parts: { glb: string }[] }).parts.map((p) => p.glb.split("/").pop()).sort();
  // A new part model needs its row: node web/scripts/parts_index.mjs
  expect(index).toEqual(models);
});
