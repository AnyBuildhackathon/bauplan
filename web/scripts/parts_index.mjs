// The studio parts panel's catalog: one row per part model in agent/data/models/manifest.json
// (the backend's list, PR #113), trimmed to what the panel shows and sorted by category.
// Run from the repo root whenever the part models change: node web/scripts/parts_index.mjs
// Writes web/public/models/parts/index.json; web/e2e/studio.spec.ts checks that it lists
// exactly the part models in that folder.
import { readFileSync, writeFileSync } from "node:fs";

const manifest = JSON.parse(readFileSync(new URL("../../agent/data/models/manifest.json", import.meta.url), "utf8"));
const out = new URL("../public/models/parts/index.json", import.meta.url);

const round = (mm) => Math.round(mm * 10) / 10;
const parts = Object.values(manifest.parts)
  .map((p) => ({
    id: p.id,
    name: p.name,
    category: p.category,
    kind: p.kind,
    glb: p.glb,
    size_mm: (p.bbox_mm ?? []).map(round),
    source_url: p.source_url ?? null,
  }))
  .sort((a, b) => a.category.localeCompare(b.category) || a.name.localeCompare(b.name));

// One part per line keeps the file small and its diffs readable.
const rows = parts.map((p) => `  ${JSON.stringify(p)}`).join(",\n");
writeFileSync(out, `{\n "source": "agent/data/models/manifest.json",\n "parts": [\n${rows}\n ]\n}\n`);
console.log(`${parts.length} parts -> ${out.pathname}`);
