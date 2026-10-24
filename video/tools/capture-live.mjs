// Records a live Claude build in the real AnyBuild app (backend with real keys) as one screen recording plus stills.
// Usage: node video/tools/capture-live.mjs <outDir> "<prompt>"  (web on WEB, backend on API)
import { createRequire } from "node:module";
const { chromium } = createRequire(new URL("../../web/package.json", import.meta.url))("playwright");
import fs from "node:fs";

const [out, prompt] = process.argv.slice(2);
const WEB = process.env.WEB || "http://127.0.0.1:5220";
const API = process.env.API || "http://127.0.0.1:8140";
fs.mkdirSync(`${out}/stills`, { recursive: true });

const t0 = Date.now();
const marks = [];
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const busy = () => fetch(API + "/api/health").then((r) => r.json()).then((j) => j.busy).catch(() => true);

await fetch(API + "/api/reset", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });
const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  recordVideo: { dir: out, size: { width: 1920, height: 1080 } },
});
const page = await ctx.newPage();
const shot = async (name) => {
  marks.push({ name, t: (Date.now() - t0) / 1000 });
  await page.screenshot({ path: `${out}/stills/${name}.png` });
};
const click = async (locator, name) => {
  try {
    await locator.first().click({ timeout: 4000 });
    await wait(2500);
    await shot(name);
  } catch (e) {
    console.log("miss", name, e.message.split("\n")[0]);
  }
};

await page.goto(WEB + "/?mute");
await wait(3500);
await shot("start");
const box = page.getByLabel("Message to Mechanic");
await box.first().click();
await box.first().pressSequentially(prompt, { delay: 28 });
await wait(600);
await shot("typed");
await page.keyboard.press("Enter");
for (let i = 1; i <= 110; i++) {
  await wait(3000);
  await shot(`l${String(i).padStart(3, "0")}`);
  if (i > 8 && !(await busy())) break;
}
await wait(3000);
await shot("l-final");
const tab = (name) => page.getByRole("tab", { name });
await click(tab(/CAD/), "tab-cad");
await wait(2000);
await click(tab(/Simulation/), "tab-sim");
await wait(4000);
await shot("tab-sim-2");
await click(tab(/Model/), "tab-model");
await click(page.getByTitle("Open the bill of materials"), "bom");
await page.keyboard.press("Escape");
await wait(800);
await click(page.getByRole("button", { name: /^Library$/ }).or(page.getByText(/^Library$/)), "library");
await page.mouse.wheel(0, 600);
await wait(2500);
await shot("library-2");

fs.writeFileSync(`${out}/marks.json`, JSON.stringify(marks, null, 1));
await ctx.close();
await browser.close();
console.log("done", (Date.now() - t0) / 1000);
