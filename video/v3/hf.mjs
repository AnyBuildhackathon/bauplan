// Writes the HyperFrames composition for the v3 film (1920x1080) from build.py's timeline and raw clips.
// Usage: node video/v3/hf.mjs <workDir>   then: npx hyperframes@0.8.168 render <workDir>/hf -o <out.mp4>
import fs from "node:fs";
import path from "node:path";

const work = path.resolve(process.argv[2]);
const hf = path.join(work, "hf");
fs.mkdirSync(path.join(hf, "assets/clips"), { recursive: true });
const { total, starts } = JSON.parse(fs.readFileSync(path.join(work, "timeline.json")));
const shots = JSON.parse(fs.readFileSync(path.join(work, "segraw/shots.json")));
const kick = Object.fromEntries(JSON.parse(fs.readFileSync(path.join(work, "kickers.json"))).map(([n, k, t]) => [n, [k, t]]));
for (const f of ["logo-mark.png", "og-mechanic.png"]) fs.copyFileSync(path.join(work, "../brand", f), path.join(hf, "assets", f));
fs.copyFileSync(path.join(work, "audio.wav"), path.join(hf, "assets/soundtrack.wav"));

const words = (h) => h.split(" ").map((w) => (w.startsWith("*") ? `<span class="w acc">${w.slice(1)}</span>` : `<span class="w">${w}</span>`)).join(" ");
const CARDS = {
  c01: `<h1>${words("Every product starts as a *conversation.")}</h1>`,
  logo: `<img class="mark" src="assets/logo-mark.png"><h1 class="word"><span class="w">Any</span><span class="w acc">Build</span></h1><p class="sub">From your meeting to a real product.</p>`,
  c02: `<h1>${words("Designed. Tested. *Priced.")}</h1><p class="sub">Before you spend a single euro.</p>`,
  mascot: `<div class="mascot"><img class="mimg" src="assets/og-mechanic.png"><div><p class="small">MEET MECHANIC</p><h1>${words("You talk.")}<br>${words("*I *build.")}</h1></div></div>`,
  "ch-listens": `<h1>${words("It *listens.")}</h1>`, "ch-plans": `<h1>${words("It *plans.")}</h1>`, "ch-tests": `<h1>${words("It *tests.")}</h1>`,
  "ch-builds": `<h1>${words("It *builds.")}</h1>`, "ch-changes": `<h1>${words("Then the team *changes *its *mind.")}</h1>`,
  "ch-learns": `<h1>${words("It *learns.")}</h1>`, "ch-ships": `<h1>${words("It *ships.")}</h1>`, "ch-any": `<h1>${words("Not just *drones.")}</h1>`,
  tech: `<p class="small">UNDER THE HOOD</p><div class="tech">${[["Jamie", "Meetings in, notes and tasks out"], ["Reson8", "Live speech to text"], ["Claude", "Opus plans, Sonnet sub-agents build"], ["FreeCAD", "Real parametric CAD"], ["MuJoCo", "Physics tests and training"], ["Blender", "Studio renders"]].map(([a, b]) => `<div class="t"><b>${a}</b><span>${b}</span></div>`).join("")}</div>`,
  end: `<img class="mark" src="assets/logo-mark.png"><h1 class="word"><span class="w">Any</span><span class="w acc">Build</span></h1><p class="line l1">From your meeting to a real product.</p><p class="line">anybuild-demo.vercel.app &nbsp;·&nbsp; github.com/AnyBuildhackathon/bauplan</p><p class="line">Batuhan Caniberk · Ansorjon Juraev &nbsp;·&nbsp; {Tech: Europe} Agentic AI Hack Berlin 2026</p><p class="line credit">Music: "The Complex" Kevin MacLeod (incompetech.com), licensed under CC BY 4.0</p>`,
};

const html = [], tl = [];
shots.forEach(([i, kind, name], k) => {
  const t0 = starts[i], d = (k + 1 < shots.length ? starts[i + 1] : total) - t0, sel = `#s${i}`;
  const attrs = `id="s${i}" class="clip scene" data-start="${t0.toFixed(3)}" data-duration="${d.toFixed(3)}" data-track-index="1"`;
  if (kind === "clip") {
    fs.copyFileSync(path.join(work, "segraw", `${String(i).padStart(2, "0")}.mp4`), path.join(hf, `assets/clips/${i}.mp4`));
    const [kk, kt] = kick[name];
    html.push(`<section ${attrs}><div class="win"><video class="clip" src="assets/clips/${i}.mp4" muted playsinline data-start="${t0.toFixed(3)}" data-duration="${d.toFixed(3)}" data-track-index="2"></video></div><div class="kick"><b>${kk}</b><span>${kt}</span></div></section>`);
    const prev = shots[k - 1];
    if (!prev || prev[1] !== "clip") tl.push(`tl.fromTo("${sel} .win", { y: 220, rotateX: 22, rotateY: -14, scale: 0.84, opacity: 0, transformPerspective: 1800 }, { y: 0, rotateX: 0, rotateY: 0, scale: 1, opacity: 1, duration: 0.8, ease: "power3.out" }, ${t0});`);
    tl.push(`tl.fromTo("${sel} .win", { scale: 1 }, { scale: 1.025, duration: ${d.toFixed(2)}, ease: "none" }, ${t0 + 0.01});`);
    tl.push(`tl.fromTo("${sel} .kick", { x: -60, opacity: 0, filter: "blur(8px)" }, { x: 0, opacity: 1, filter: "blur(0px)", duration: 0.5, ease: "power3.out" }, ${t0 + 0.25});`);
  } else {
    html.push(`<section ${attrs}><div class="center">${CARDS[name]}</div></section>`);
    const stagger = name === "c01" ? 0.36 : name === "c02" ? 0.55 : 0.12;
    const at = name === "c01" ? t0 + 0.7 : t0 + 0.12;
    tl.push(`tl.fromTo("${sel} .w", { y: 60, opacity: 0, filter: "blur(14px)" }, { y: 0, opacity: 1, filter: "blur(0px)", duration: 0.55, ease: "power3.out", stagger: ${stagger} }, ${at});`);
    tl.push(`tl.fromTo("${sel} .center", { scale: 1 }, { scale: 1.05, duration: ${d.toFixed(2)}, ease: "none" }, ${t0});`);
    if (name === "logo" || name === "end") tl.push(`tl.fromTo("${sel} .mark", { scale: 0.3, opacity: 0, rotate: -60 }, { scale: 1, opacity: 1, rotate: 0, duration: 0.9, ease: "back.out(1.7)" }, ${t0 + 0.05});`);
    if (name === "mascot") tl.push(`tl.fromTo("${sel} .mimg", { x: -120, opacity: 0, rotateY: 30, transformPerspective: 1400 }, { x: 0, opacity: 1, rotateY: 0, duration: 0.9, ease: "power3.out" }, ${t0});`);
    if (name === "tech") tl.push(`tl.fromTo("${sel} .t", { opacity: 0, y: 80, rotateX: 40, transformPerspective: 1200 }, { opacity: 1, y: 0, rotateX: 0, duration: 0.6, ease: "power3.out", stagger: 0.18 }, ${t0 + 0.2});`);
    tl.push(`tl.fromTo("${sel} .sub, ${sel} .small, ${sel} .line", { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 0.5, ease: "power2.out", stagger: 0.35 }, ${t0 + 0.9});`);
  }
  if (k < shots.length - 1 && !(kind === "clip" && shots[k + 1][1] === "clip"))
    tl.push(`tl.to("${sel} > *", { opacity: 0, scale: 1.04, filter: "blur(10px)", duration: 0.22, ease: "power2.in" }, ${(t0 + d - 0.22).toFixed(3)});`);
});

const css = `@import url("https://fonts.googleapis.com/css2?family=Inter+Tight:wght@500;700;800;900&display=block");
*{margin:0;box-sizing:border-box} html,body{width:1920px;height:1080px;overflow:hidden;background:#0b0b0d;font-family:"Inter Tight",sans-serif}
.bg{position:absolute;inset:-20%;background:radial-gradient(40% 50% at 75% 95%,rgba(255,138,61,.55),transparent 70%),radial-gradient(35% 45% at 15% 5%,rgba(124,92,255,.38),transparent 70%),#0b0b0d;background-size:140% 140%}
.scene{position:absolute;inset:0;color:#fff}
.center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}
h1{font-size:132px;font-weight:900;letter-spacing:-.045em;line-height:1.04} .w{display:inline-block} .acc{color:#ff8a3d}
.word{font-size:180px} .mark{width:190px;height:190px;border-radius:44px;margin-bottom:26px}
.sub{margin-top:34px;font-size:42px;font-weight:500;color:rgba(255,255,255,.75)}
.small{font-size:26px;letter-spacing:.2em;font-weight:800;color:#ff8a3d;margin-bottom:12px}
.mascot{display:flex;align-items:center;gap:80px;text-align:left} .mimg{height:640px;border-radius:44px;box-shadow:0 30px 90px rgba(0,0,0,.6)} .mascot h1{font-size:124px}
.tech{display:grid;grid-template-columns:repeat(3,500px);gap:26px;margin-top:40px}
.t{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.16);border-radius:26px;padding:30px 36px;text-align:left} .t b{display:block;font-size:50px;font-weight:800} .t span{font-size:27px;color:rgba(255,255,255,.72)}
.line{font-size:34px;color:rgba(255,255,255,.82);margin-top:16px} .l1{font-size:52px;font-weight:700;color:#fff} .credit{font-size:20px;color:rgba(255,255,255,.5);margin-top:36px}
.win{position:absolute;left:60px;top:34px;width:1800px;height:1013px;border-radius:28px;overflow:hidden;box-shadow:0 40px 120px rgba(0,0,0,.65),0 0 0 1px rgba(255,255,255,.12)}
.win video{width:100%;height:100%;object-fit:cover;display:block}
.kick{position:absolute;left:96px;top:64px;display:flex;align-items:center;gap:18px;background:rgba(14,14,13,.93);border-radius:22px;padding:18px 30px;box-shadow:0 18px 50px rgba(0,0,0,.35)}
.kick b{font-size:22px;font-weight:800;letter-spacing:.14em;color:#ff8a3d} .kick span{font-size:42px;font-weight:800;letter-spacing:-.02em}`;

fs.writeFileSync(path.join(hf, "index.html"), `<!doctype html>
<!-- Generated by video/v3/hf.mjs -->
<html lang="en" data-resolution="landscape">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>${css}</style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="${total.toFixed(3)}" data-width="1920" data-height="1080" data-fps="30">
      <div class="bg"></div>
      ${html.join("\n      ")}
      <audio id="soundtrack" src="assets/soundtrack.wav" data-start="0" data-duration="${total.toFixed(3)}" data-track-index="3" data-volume="1"></audio>
    </div>
    <script>
      window.__timelines = window.__timelines || {};
      const tl = gsap.timeline({ paused: true });
      ${tl.join("\n      ")}
      tl.fromTo(".bg", { backgroundPosition: "0% 0%" }, { backgroundPosition: "100% 100%", duration: ${total.toFixed(2)}, ease: "none" }, 0);
      window.__timelines["main"] = tl;
      tl.seek(0);
    </script>
  </body>
</html>
`);
fs.writeFileSync(path.join(hf, "hyperframes.json"), JSON.stringify({ $schema: "https://hyperframes.heygen.com/schema/hyperframes.json", paths: { assets: "assets" }, media: { autoProxy: true } }, null, 2));
console.log("hf composition", total.toFixed(2), "s,", shots.length, "shots");
