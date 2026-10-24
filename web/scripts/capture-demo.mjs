// Captures 1920x1080 stills and a screen video of one full build for the demo video.
// Run against a local backend (mock mode is fine) and the dev server:
//   node web/scripts/capture-demo.mjs [outDir]
// WEB_URL defaults to http://127.0.0.1:5180/, BACKEND_URL to http://127.0.0.1:8100.
import { mkdirSync } from "node:fs";
import { chromium } from "@playwright/test";

const OUT = process.argv[2] ?? "demo-capture";
const WEB = process.env.WEB_URL ?? "http://127.0.0.1:5180/";
const API = process.env.BACKEND_URL ?? "http://127.0.0.1:8100";
const PROMPT = process.env.DEMO_PROMPT ?? "Build me a micro FPV drone that flies 8 minutes, under 120 euros";

mkdirSync(OUT, { recursive: true });
await fetch(`${API}/api/reset`, { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  recordVideo: { dir: OUT, size: { width: 1920, height: 1080 } },
});
const page = await ctx.newPage();
let n = 0;
const shot = async (name) => page.screenshot({ path: `${OUT}/${String(++n).padStart(2, "0")}-${name}.png` });

await page.goto(`${WEB}?mute`);
await page.waitForTimeout(2500);
await shot("start");
const input = page.locator("textarea").first();
await input.click();
await input.pressSequentially(PROMPT, { delay: 35 });
await shot("typed");
await page.keyboard.press("Enter");
for (let i = 0; i < 22; i++) {
  await page.waitForTimeout(2000);
  await shot(`build${i}`);
}
for (const tab of ["CAD", "Simulation", "Model"]) {
  const t = page.getByRole("tab", { name: new RegExp(tab, "i") }).first();
  if (await t.count()) {
    await t.click();
    await page.waitForTimeout(2500);
    await shot(`tab-${tab}`);
  }
}
for (const view of ["Library", "Training", "Community", "Logbook"]) {
  const b = page.getByRole("button", { name: view, exact: true }).first();
  if (await b.count()) {
    await b.click();
    await page.waitForTimeout(view === "Training" ? 8500 : 3500);
    await shot(`view-${view}`);
  }
}
await page.goto(`${WEB}?mute&bom`);
await page.waitForTimeout(3500);
await shot("bom");
await ctx.close();
await browser.close();
