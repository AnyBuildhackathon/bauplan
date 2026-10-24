// Renders the v3 type cards, kicker overlays and window mask as 1920x1080 PNGs (ffmpeg here has no drawtext).
// Usage: node video/v3/cards.mjs <workDir>   (reads <workDir>/../brand, writes <workDir>/png)
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const { chromium } = createRequire(new URL("../../web/package.json", import.meta.url))("playwright");
const work = path.resolve(process.argv[2]);
const out = path.join(work, "png");
fs.mkdirSync(out, { recursive: true });
const uri = (f) => "data:image/png;base64," + fs.readFileSync(path.join(work, "../brand", f)).toString("base64");

const css = `@import url("https://fonts.googleapis.com/css2?family=Inter+Tight:wght@500;700;800;900&display=block");
*{margin:0;box-sizing:border-box} html,body{width:1920px;height:1080px;overflow:hidden;font-family:"Inter Tight",sans-serif}
.dark{width:100%;height:100%;background:radial-gradient(60% 70% at 70% 110%,rgba(255,138,61,.55),transparent 60%),radial-gradient(50% 60% at 15% -10%,rgba(124,92,255,.35),transparent 60%),#0b0b0d;color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}
h1{font-size:132px;font-weight:900;letter-spacing:-.045em;line-height:1.02}
h1 em,h2 em{font-style:normal;color:#ff8a3d}
.w{opacity:0} .w.on{opacity:1}
.sub{margin-top:34px;font-size:40px;font-weight:500;color:rgba(255,255,255,.72);letter-spacing:-.01em}
.word{font-size:180px} .mark{width:200px;height:200px;margin-bottom:28px;border-radius:44px}
.kick{position:absolute;left:56px;top:44px;display:flex;align-items:center;gap:18px;background:rgba(14,14,13,.92);color:#fff;border-radius:22px;padding:18px 30px;box-shadow:0 18px 50px rgba(0,0,0,.28)}
.kick b{font-size:22px;font-weight:800;letter-spacing:.14em;color:#ff8a3d}
.kick span{font-size:42px;font-weight:800;letter-spacing:-.02em}
.mascot{display:flex;align-items:center;gap:80px} .mascot img{height:640px;border-radius:44px;box-shadow:0 30px 90px rgba(0,0,0,.6)}
.mascot h1{text-align:left;font-size:120px}
.tech{display:grid;grid-template-columns:repeat(3,480px);gap:26px;margin-top:50px}
.tech div{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.14);border-radius:26px;padding:28px 34px;text-align:left}
.tech b{display:block;font-size:46px;font-weight:800} .tech span{font-size:26px;color:rgba(255,255,255,.7)}
.small{font-size:26px;letter-spacing:.2em;font-weight:800;color:#ff8a3d}
.end p{font-size:34px;color:rgba(255,255,255,.8);margin-top:18px} .end .credit{font-size:20px;color:rgba(255,255,255,.5);margin-top:40px}
.mask{width:100%;height:100%;background:#000;display:flex;align-items:center;justify-content:center}
.mask div{width:1600px;height:900px;border-radius:30px;background:#fff}`;

const cards = {};
// Kinetic cards: one PNG per revealed word.
const kinetic = (name, html, sub = "") => {
  const words = html.split(" ");
  words.forEach((_, i) => {
    cards[`${name}-${i}`] = `<div class="dark"><h1>${words.map((w, j) => `<span class="w ${j <= i ? "on" : ""}">${w}</span>`).join(" ")}</h1>${sub && i === words.length - 1 ? `<p class="sub">${sub}</p>` : ""}</div>`;
  });
};
kinetic("c01", "Every product starts as a <em>conversation.</em>");
kinetic("c02", "Designed. Tested. <em>Priced.</em>", "Before you spend a single euro.");
cards.logo = `<div class="dark"><img class="mark" src="${uri("logo-mark.png")}"><h1 class="word">Any<em>Build</em></h1><p class="sub">From your meeting to a real product.</p></div>`;
cards.mascot = `<div class="dark"><div class="mascot"><img src="${uri("og-mechanic.png")}"><div><p class="small">MEET MECHANIC</p><h1>You talk.<br><em>I build.</em></h1></div></div></div>`;
for (const [n, t] of [["listens", "It <em>listens.</em>"], ["plans", "It <em>plans.</em>"], ["tests", "It <em>tests.</em>"], ["builds", "It <em>builds.</em>"], ["changes", "Then the team <em>changes its mind.</em>"], ["learns", "It <em>learns.</em>"], ["ships", "It <em>ships.</em>"], ["any", "Not just <em>drones.</em>"]])
  cards[`ch-${n}`] = `<div class="dark"><h1>${t}</h1></div>`;
cards.tech = `<div class="dark"><p class="small">UNDER THE HOOD</p><div class="tech">${[["Jamie", "Meetings in, notes and tasks out"], ["Reson8", "Live speech to text"], ["Claude", "Opus plans, Sonnet sub-agents build"], ["FreeCAD", "Real parametric CAD"], ["MuJoCo", "Physics tests and training"], ["Blender", "Studio renders"]].map(([a, b]) => `<div><b>${a}</b><span>${b}</span></div>`).join("")}</div></div>`;
cards.end = `<div class="dark end"><img class="mark" src="${uri("logo-mark.png")}"><h1 class="word">Any<em>Build</em></h1><p style="font-size:48px;color:#fff;font-weight:700">From your meeting to a real product.</p><p>anybuild-demo.vercel.app &nbsp;·&nbsp; github.com/AnyBuildhackathon/bauplan</p><p>Batuhan Caniberk · Ansorjon Juraev &nbsp;·&nbsp; {Tech: Europe} Agentic AI Hack Berlin 2026</p><p class="credit">Music: "The Complex" Kevin MacLeod (incompetech.com), licensed under CC BY 4.0</p></div>`;
cards.mask = `<div class="mask"><div></div></div>`;
const kick = JSON.parse(fs.readFileSync(path.join(work, "kickers.json")));
for (const [n, k, t] of kick) cards[`k-${n}`] = `<div class="kick"><b>${k}</b><span>${t}</span></div>`;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
for (const [name, html] of Object.entries(cards)) {
  await page.setContent(`<!doctype html><html><head><style>${css}</style></head><body style="background:transparent">${html}</body></html>`);
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: path.join(out, name + ".png"), omitBackground: name.startsWith("k-") });
}
await browser.close();
console.log("cards", Object.keys(cards).length);
