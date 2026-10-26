// Captures 1920x1080 stills and a screen video of one full build for the demo video.
// Run against a local backend (mock mode is fine) and the dev server:
//   node web/scripts/capture-demo.mjs [outDir]
// WEB_URL defaults to http://127.0.0.1:5180/, BACKEND_URL to http://127.0.0.1:8100.
// For the public site set WEB_URL=https://anybuild-demo.vercel.app/ and NO_RESET=1; Chromium's
// local-network check is switched off so the page can reach a tailnet backend.
import { mkdirSync } from "node:fs";
import { chromium } from "@playwright/test";

const OUT = process.argv[2] ?? "demo-capture";
const WEB = process.env.WEB_URL ?? "http://127.0.0.1:5180/";
const API = process.env.BACKEND_URL ?? "http://127.0.0.1:8100";
const PROMPT = process.env.DEMO_PROMPT ?? "Build me a micro FPV drone that flies 8 minutes, under 120 euros";

mkdirSync(OUT, { recursive: true });
if (!process.env.NO_RESET) {
  await fetch(`${API}/api/reset`, { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });
}

// A visible cursor, so the recording shows every move and click.
const CURSOR = `addEventListener("DOMContentLoaded", () => {
  const c = document.createElement("div");
  c.style.cssText = "position:fixed;left:0;top:0;width:28px;height:28px;z-index:2147483647;pointer-events:none;transition:transform .08s";
  c.innerHTML = '<svg viewBox="0 0 24 24" width="28" height="28"><path d="M4 2l15 9-7 1.5L8.5 20z" fill="#15191c" stroke="#fff" stroke-width="1.6"/></svg>';
  document.body.appendChild(c);
  addEventListener("mousemove", (e) => { c.style.left = e.clientX - 4 + "px"; c.style.top = e.clientY - 2 + "px"; }, true);
  addEventListener("mousedown", () => { c.style.transform = "scale(.8)"; }, true);
  addEventListener("mouseup", () => { c.style.transform = "scale(1)"; }, true);
});`;

const browser = await chromium.launch({
  args: ["--disable-features=LocalNetworkAccessChecks,BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessSendPreflights"],
});
const ctx = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  recordVideo: { dir: OUT, size: { width: 1920, height: 1080 } },
});
await ctx.addInitScript(CURSOR);
const page = await ctx.newPage();
const clickOn = async (locator) => {
  const box = await locator.boundingBox();
  if (!box) return false;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 30 });
  await page.waitForTimeout(250);
  await page.mouse.down();
  await page.mouse.up();
  return true;
};
let n = 0;
const shot = async (name) => page.screenshot({ path: `${OUT}/${String(++n).padStart(2, "0")}-${name}.png` });

await page.goto(`${WEB}?mute`);
await page.waitForTimeout(2500);
await shot("start");
const input = page.locator("textarea").first();
await clickOn(input);
await input.pressSequentially(PROMPT, { delay: 35 });
await shot("typed");
if (!(await clickOn(page.locator('button[title="Send"]').first()))) await page.keyboard.press("Enter");
for (let i = 0; i < 22; i++) {
  await page.waitForTimeout(2000);
  await shot(`build${i}`);
}
for (const tab of ["CAD", "Simulation", "Model"]) {
  const t = page.getByRole("tab", { name: new RegExp(tab, "i") }).first();
  if (await t.count()) {
    await clickOn(t);
    await page.waitForTimeout(2500);
    await shot(`tab-${tab}`);
  }
}
for (const view of ["Library", "Training", "Community", "Logbook"]) {
  const b = page.getByRole("button", { name: view, exact: true }).first();
  if (await b.count()) {
    await clickOn(b);
    await page.waitForTimeout(view === "Training" ? 8500 : 3500);
    await shot(`view-${view}`);
  }
}
await page.goto(`${WEB}?mute&bom`);
await page.waitForTimeout(3500);
await shot("bom");
await ctx.close();
await browser.close();
