// Captures the real AnyBuild app (mock backend) as one screen recording plus named stills.
// Usage: node video/tools/capture.mjs <outDir>  (web on WEB, backend on API)
import { createRequire } from "node:module";
const { chromium } = createRequire(new URL("../../web/package.json", import.meta.url))("playwright");
import fs from "node:fs";

const out = process.argv[2];
const WEB = process.env.WEB || "http://127.0.0.1:5220";
const API = process.env.API || "http://127.0.0.1:8140";
const repo = new URL("../..", import.meta.url).pathname;
fs.mkdirSync(`${out}/stills`, { recursive: true });

const t0 = Date.now();
const marks = [];
const mark = (name) => marks.push({ name, t: (Date.now() - t0) / 1000 });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const post = (path, file) =>
  fetch(API + path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: file ? fs.readFileSync(repo + file) : "{}",
  });

await post("/api/reset");
const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 1,
  recordVideo: { dir: out, size: { width: 1920, height: 1080 } },
});
const page = await ctx.newPage();
const shot = async (name) => {
  mark(name);
  await page.screenshot({ path: `${out}/stills/${name}.png` });
};
const click = async (locator, name) => {
  try {
    await locator.first().click({ timeout: 4000 });
    await wait(1800);
    if (name) await shot(name);
  } catch (e) {
    console.log("miss", name, e.message.split("\n")[0]);
  }
};

await page.goto(WEB + "/?mute");
await wait(3000);
await shot("00-start");

// Kickoff: the finished Jamie meeting triggers the build.
mark("kickoff");
await post("/api/webhooks/jamie", "agent/data/webhooks/meeting-ended.json");
for (let i = 1; i <= 40; i++) {
  await wait(2000);
  await shot(`k${String(i).padStart(2, "0")}`);
  const done = await page.getByText(/Version 1/i).count().catch(() => 0);
  if (done && i > 8) break;
}
await wait(2000);
await shot("k-final");

const tab = (name) => page.getByRole("tab", { name });
await click(tab(/Agents/), "tab-agents");
await click(tab(/Simulation/), "tab-sim");
await wait(4000);
await shot("tab-sim-2");
await click(tab(/CAD/), "tab-cad");
await click(tab(/Model/), "tab-model");
await click(page.getByTitle("Open the bill of materials"), "bom");
await page.keyboard.press("Escape");
await wait(800);
await click(page.getByRole("button", { name: /Build guide/ }).or(page.getByLabel("Build guide")), "guide");
await click(page.getByRole("button", { name: /Next/ }), "guide-2");
await page.keyboard.press("Escape");
await wait(800);

// Review: the plan changes, Mechanic asks.
mark("review");
await post("/api/webhooks/jamie", "agent/data/webhooks/review-ended.json");
for (let i = 1; i <= 40; i++) {
  await wait(1500);
  await shot(`r${String(i).padStart(2, "0")}`);
  const q = page.getByRole("button", { name: /10 min/ });
  if (await q.count().catch(() => 0)) {
    await wait(2500);
    await shot("question");
    await q.first().click().catch(() => {});
    mark("answered");
    break;
  }
}
for (let i = 1; i <= 30; i++) {
  await wait(2000);
  await shot(`v${String(i).padStart(2, "0")}`);
  if ((await page.getByText(/Version 2/i).count().catch(() => 0)) && i > 6) break;
}
await wait(2500);
await shot("v-final");
await click(page.getByTitle("Open the bill of materials"), "bom-v2");
await page.keyboard.press("Escape");
await wait(800);

// Training: 1,024 MuJoCo worlds in the browser.
await click(tab(/Simulation/), null);
await click(page.getByRole("button", { name: /^Training$/ }), "training-0");
await page.getByLabel("Message to Mechanic").fill("train it");
await page.keyboard.press("Enter");
mark("training");
for (let i = 1; i <= 16; i++) {
  await wait(2500);
  await shot(`t${String(i).padStart(2, "0")}`);
}

await click(page.getByRole("button", { name: /^Library$/ }).or(page.getByText(/^Library$/)), "library");
await wait(2000);
await shot("library-2");
await page.mouse.wheel(0, 700);
await wait(1500);
await shot("library-3");

fs.writeFileSync(`${out}/marks.json`, JSON.stringify(marks, null, 1));
await ctx.close();
await browser.close();
console.log("done", (Date.now() - t0) / 1000);
