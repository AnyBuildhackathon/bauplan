// Runs SparkBench headless for AnyBuild's circuit_design tool (agent/src/pai_agent/sparkbench.py).
//   node node_modules/tsx/dist/cli.mjs bridge.ts <request.json>   (from the SparkBench checkout)
// The request holds the board and AnyBuild's parts, each either a SparkBench feature kind or a part to look up
// in SparkBench's parts library. SparkBench's own planner wires them; then come its design checks, its acceptance
// tests and a 5 s simulation, and every file is written like SparkBench's scripts/build-project.ts.
// Servos behind a servo driver stay out: SparkBench's PCA9685 has no channel pins, and wiring them to the board
// instead would be another circuit. Each one is listed in gaps with the channel it plugs into.
// result.json in the request's output folder says what happened. The same request gives the same files and
// result: the dates come from the request and the simulator's sensor noise from a fixed seed.
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';

interface RequestPart {
  key: string;
  label: string;
  // The part's name and catalog id, searched for a library part number when there is no feature; then its aliases.
  text: string;
  alt?: string;
  qty: number;
  feature?: { kind: string; props?: Record<string, unknown> };
}

interface Request {
  name: string;
  board: 'esp32' | 'pico';
  date: string;
  parts: RequestPart[];
  out: string;
}

interface LibraryPart {
  spec: any;
  patterns: RegExp[];
}

const SIM_MS = 5000;
// As in build-project.ts: every button is held from 2.5 s to 3.5 s, so button-driven circuits show their behaviour.
const PRESS_MS = [2500, 3500];
const SNAPSHOTS_MS = [500, 1000, 1500, 2000, 2700, 3000, 3300, 4000, 4500];
const SERIAL_TAIL = 12;
// More of one part would only run the board out of pins.
const MAX_QTY = 8;
const MODULES = [
  'src/core/planner.ts',
  'src/core/autowire.ts',
  'src/core/checks.ts',
  'src/core/acceptance.ts',
  'src/sim/node-runner.ts',
  'src/sim/run-tests.ts',
  'src/core/netlist.ts',
  'src/core/schematic.ts',
  'src/core/breadboard.ts',
  'src/core/bbplace.ts',
  'src/core/kicad.ts',
  'src/core/spice.ts',
  'src/core/bom.ts',
  'src/core/docs.ts',
  'src/core/parts.ts',
  'src/core/boards.ts',
];

// mulberry32, standing in for Math.random, which the simulator uses for sensor noise.
function seeded(seed: number): () => number {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const words = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

/** A library part number as a pattern over a part's words: MG996R also finds MG-996R and mg 996r, SG90 360 sg90-360. */
function numberPattern(mpn: string): RegExp | null {
  const runs = words(mpn).match(/[a-z]+|\d+/g) ?? [];
  const joined = runs.join('');
  // Bare catalog numbers say nothing on their own: Adafruit's 4409 is not Pololu's 4409.
  if (joined.length < 4 || (/^\d+$/.test(joined) && joined.length < 6)) return null;
  return new RegExp(`(?:^| )${runs.join(' ?')}(?: |$)`);
}

/** The parts that passed SparkBench's part check, findable by part number or by their library name. */
function loadLibrary(dir: string): LibraryPart[] {
  const skills = join(dir, '.claude', 'skills');
  const out: LibraryPart[] = [];
  for (const name of readdirSync(skills).sort()) {
    const file = join(skills, name, 'part.json');
    if (!name.startsWith('part-') || !existsSync(file)) continue;
    const spec = JSON.parse(readFileSync(file, 'utf8'));
    if (spec?.library?.status !== 'checked') continue;
    const patterns = [numberPattern(String(spec.mpn ?? '')), numberPattern(String(spec.type).replace(/^custom-/, ''))];
    out.push({ spec, patterns: patterns.filter((p): p is RegExp => p !== null) });
  }
  return out;
}

/** The library part whose number names this part; the longest match wins (an MG996R is not an MG996). */
function findInLibrary(library: LibraryPart[], text: string): any | undefined {
  const haystack = ` ${words(text)} `;
  let best: { spec: any; length: number } | undefined;
  for (const entry of library) {
    for (const pattern of entry.patterns) {
      const found = pattern.exec(haystack)?.[0].trim();
      if (found && (!best || found.length > best.length)) best = { spec: entry.spec, length: found.length };
    }
  }
  return best?.spec;
}

function uniqueLabel(used: Set<string>, base: string): string {
  let label = base;
  for (let n = 2; used.has(label.toLowerCase()); n++) label = `${base} (${n})`;
  used.add(label.toLowerCase());
  return label;
}

/** Where servos plug into a servo driver, which SparkBench cannot draw: the channels taken, in order. */
function channelGap(label: string, qty: number, driver: any, first: number): string {
  const count = driver.sim.pwmChannels.count;
  const last = first + qty - 1;
  const where = qty > 1 ? `plug into ${driver.mpn} channels ${first} to ${last}` : `plugs into ${driver.mpn} channel ${first}`;
  const full = last >= count ? ` The ${driver.mpn} has only ${count} channels.` : '';
  return `${label}: ${where} and ${qty > 1 ? 'get their' : 'gets its'} power from the ${driver.mpn}'s V+ terminal; SparkBench's ${driver.mpn} has no channel pins, so ${qty > 1 ? 'they are' : 'it is'} not in the circuit.${full}`;
}

/** What a frame shows, in build-project.ts's words, plus driver channels and pixel rings. */
function visibleState(project: any, frame: any): string {
  return project.parts
    .map((p: any) => {
      const v = frame.parts[p.id] ?? {};
      const bits: string[] = [];
      if (v.led !== undefined) bits.push(`${p.ref} ${v.led > 0.05 ? `ON ${(v.ma ?? 0).toFixed(1)} mA` : 'off'}`);
      if (v.rgb) bits.push(`${p.ref} rgb(${v.rgb.map((x: number) => Math.round(x * 255)).join(',')})`);
      if (v.tone) bits.push(`${p.ref} tone ${v.tone} Hz`);
      if (v.angle !== undefined) bits.push(`${p.ref} ${Math.round(v.angle)}°`);
      if (v.relay !== undefined) bits.push(`${p.ref} relay ${v.relay ? 'ON' : 'off'}`);
      if (v.spin) bits.push(`${p.ref} motor running`);
      if (v.inputs && v.active !== undefined) bits.push(`${p.ref} ${v.active ? 'on ' + Object.keys(v.inputs).filter((k) => v.inputs[k]).join(' ') : 'idle'}`);
      if (v.pixels) bits.push(`${p.ref} ${v.pixels.some((x: number) => x > 10) ? 'lit' : 'dark'}`);
      if (v.lcd) bits.push(`${p.ref} "${String.fromCharCode(...v.lcd.chars.slice(0, 16)).trimEnd()} / ${String.fromCharCode(...v.lcd.chars.slice(16)).trimEnd()}"`);
      if (v.oledOn) bits.push(`${p.ref} OLED drawing (${v.oled.filter((b: number) => b).length} lit bytes)`);
      if (v.epaper?.refreshes) bits.push(`${p.ref} e-paper refreshed ×${v.epaper.refreshes}`);
      return bits.join(', ');
    })
    .filter(Boolean)
    .join(' | ');
}

function finish(out: string, result: object): void {
  mkdirSync(out, { recursive: true });
  writeFileSync(join(out, 'result.json'), JSON.stringify(result, null, 2));
}

async function main(): Promise<void> {
  const request: Request = JSON.parse(readFileSync(process.argv[2], 'utf8'));
  const day = Date.parse(`${request.date}T00:00:00Z`);
  if (!Number.isFinite(day)) throw new Error(`date must be YYYY-MM-DD, not ${request.date}`);
  const dir = process.env.SPARKBENCH_DIR || process.cwd();
  Math.random = seeded(20261026);
  const [planner, autowire, checksMod, acceptance, runner, testsMod, netlist, schematic, breadboard, bbplace, kicad, spice, bomMod, docs, parts, boards] = await Promise.all(
    MODULES.map((path) => import(pathToFileURL(join(dir, path)).href)),
  );
  const library = request.parts.some((part) => !part.feature) ? loadLibrary(dir) : [];

  const gaps: string[] = [];
  const notes: string[] = [];
  const used = new Set<string>();
  const features: any[] = [];
  const fromLibrary: { key: string; spec: any; labels: string[] }[] = [];
  // The AnyBuild part each feature label and each SparkBench part id stands for.
  const featureOwners = new Map<string, string>();
  const owners = new Map<string, string>();
  const found = request.parts.map((part) => ({ part, spec: part.feature ? undefined : findInLibrary(library, part.text) ?? findInLibrary(library, part.alt ?? '') }));
  const driver = found.find((f) => f.spec?.sim?.pwmChannels)?.spec;
  let channel = 0;
  for (const { part, spec } of found) {
    if (driver && (part.feature?.kind === 'servo' || spec?.sim?.kind === 'servo')) {
      gaps.push(channelGap(part.label, part.qty, driver, channel));
      channel += part.qty;
      continue;
    }
    const qty = Math.max(1, Math.min(MAX_QTY, Math.round(part.qty)));
    if (part.qty > MAX_QTY) gaps.push(`${part.label}: only ${MAX_QTY} of the ${part.qty} are in the circuit.`);
    const labels = Array.from({ length: qty }, (_, i) => uniqueLabel(used, qty > 1 ? `${part.label} ${i + 1}` : part.label));
    if (part.feature) {
      for (const label of labels) {
        features.push({ kind: part.feature.kind, label, ...(part.feature.props ? { props: part.feature.props } : {}) });
        featureOwners.set(label, part.key);
      }
    } else if (spec) fromLibrary.push({ key: part.key, spec, labels });
    else gaps.push(`${part.label}: SparkBench has no model for it, so it is not in the circuit.`);
  }

  let project: any;
  try {
    project = planner.buildProject({ board: request.board, features, title: request.name }, { name: request.name });
    for (const entry of fromLibrary) {
      for (const label of entry.labels) {
        const added = autowire.withCustomPart(project, entry.spec, { label });
        project = added.project;
        owners.set(added.id, entry.key);
        notes.push(...added.notes.map((note: string) => `${label}: ${note}`));
      }
    }
  } catch (error: any) {
    // The planner's own words, such as a board out of free pins.
    finish(request.out, { ok: false, error: String(error?.message ?? error), gaps });
    return;
  }
  for (const feature of project.features ?? []) for (const id of feature.parts) if (featureOwners.has(feature.label)) owners.set(id, featureOwners.get(feature.label)!);
  // Stable ids and dates: the KiCad UUIDs hash the project id, and the title blocks print the date.
  project = { ...project, id: `anybuild-${words(request.name).replace(/ /g, '-')}`, createdAt: day, updatedAt: day };

  const checks = checksMod.runChecks(project);
  const results = await testsMod.runTests(project, acceptance.deriveTests(project));
  const buttons = project.parts.filter((p: any) => p.type === 'pushbutton');
  const inputs = buttons.flatMap((b: any) => PRESS_MS.map((atMs, i) => ({ atMs, part: b.id, key: 'pressed', value: i === 0 ? 1 : 0 })));
  const { engine, snapshots } = await runner.simulate(project, { untilMs: SIM_MS, inputs, onFrameAt: SNAPSHOTS_MS });
  const outputs = snapshots.map((s: any) => ({ t_s: s.atMs / 1000, text: visibleState(project, s.frame) }));
  const lines = bomMod.buildBom(project);

  const put = (name: string, text: string) => {
    mkdirSync(dirname(join(request.out, name)), { recursive: true });
    writeFileSync(join(request.out, name), text);
    return name;
  };
  const stem = kicad.kicadName(project);
  const files = {
    firmware: Object.entries(project.files as Record<string, string>).map(([name, text]) => put(`firmware/${name}`, text)),
    schematic_svg: put('schematic.svg', schematic.renderSchematicSvg(project, { theme: 'light' })),
    breadboard_svg: put('breadboard.svg', breadboard.renderBreadboardSvg(bbplace.planBreadboard(project).layout, { labels: true })),
    kicad_sch: put(`${stem}.kicad_sch`, kicad.exportKicadSchematic(project)),
    kicad_pro: put(`${stem}.kicad_pro`, kicad.exportKicadProject(project)),
    netlist: put(`${stem}.net`, kicad.exportKicadNetlist(project)),
    footprints: Object.entries(kicad.exportKicadFootprints(project) as Record<string, string>).map(([name, text]) => put(name, text)),
    spice: put(`${stem}.cir`, spice.exportSpice(project, spice.defaultSpiceOptions(project))),
    bom_csv: put('bom.csv', bomMod.bomToCsv(lines)),
    build_md: put('BUILD.md', docs.buildGuide(project)),
    project_json: put('project.sparkbench.json', JSON.stringify(project, null, 2)),
    checks_txt: put('checks.txt', checks.map((c: any) => `[${c.severity}] ${c.title} — ${c.detail}`).join('\n') || 'No problems found.'),
    simulation_log: put(
      'simulation.log',
      [
        `status: ${engine.status} after ${(engine.timeUs / 1e6).toFixed(1)} s simulated`,
        engine.error ? `error: ${engine.error.raw}` : 'error: none',
        ...engine.allWarnings.map((w: any) => `${w.severity}: ${w.text}`),
        buttons.length ? '--- outputs (buttons held from 2.5 s to 3.5 s) ---' : '--- outputs ---',
        ...outputs.map((o: any) => `t=${o.t_s.toFixed(1)}s  ${o.text || '(no visible outputs)'}`),
        '--- serial ---',
        ...engine.serialAll,
      ].join('\n'),
    ),
  };

  const ref = (id: string) => project.parts.find((p: any) => p.id === id)?.ref ?? id;
  const end = (r: { part: string; pin: string }) => `${ref(r.part)}.${r.pin}`;
  const joined = (net: any) => !!net && new Set(net.pins.map((r: any) => r.part)).size > 1;
  const { nets, netOf } = netlist.buildNets(project);
  finish(request.out, {
    ok: true,
    board: request.board,
    board_name: boards.BOARDS[request.board].name,
    name: project.name,
    parts: project.parts.map((p: any) => {
      const def = parts.partDef(p.type);
      const pins: Record<string, string | null> = {};
      for (const pin of def.pins) {
        const net = netOf.get(`${p.id}:${pin.name}`);
        // The board lists only its connected pins; a part lists every pin, null when it goes nowhere.
        if (joined(net)) pins[pin.name] = net.name;
        else if (def.category !== 'board') pins[pin.name] = null;
      }
      return { ref: p.ref, type: p.type, label: p.label ?? def.name, mpn: def.bom?.mpn ?? null, anybuild: owners.get(p.id) ?? null, pins };
    }),
    nets: nets.filter(joined).map((n: any) => ({ name: n.name, pins: n.pins.map(end) })),
    wires: project.wires.map((w: any) => ({ from: end(w.a), to: end(w.b), color: w.color ?? null })),
    checks: checks.map((c: any) => ({ id: c.id, severity: c.severity, title: c.title, detail: c.detail })),
    tests: results.map((r: any) => ({ id: r.id, name: r.title, pass: r.pass, detail: r.detail })),
    sim: {
      status: engine.status,
      simulated_s: Math.round(engine.timeUs / 1e5) / 10,
      error: engine.error ? engine.error.message : null,
      warnings: engine.allWarnings.map((w: any) => ({ severity: w.severity, text: w.text })),
      serial_tail: engine.serialAll.slice(-SERIAL_TAIL),
      outputs,
    },
    bom_total_usd: Math.round(bomMod.bomTotal(lines) * 100) / 100,
    notes: [...project.notes, ...notes],
    gaps,
    files,
  });
}

await main();
