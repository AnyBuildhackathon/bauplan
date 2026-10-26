# Event contract

The backend listens on `http://127.0.0.1:8100`.
The web app listens on `http://127.0.0.1:5180`.
This file is the only copy of the wire format.

## HTTP

`POST /api/prompt` with `{"text": "..."}` starts or continues the one local session; `"voice": true` marks the text as a spoken turn.
The response is `{"ok": true, "mode": "mock"|"claude", "status": "started"|"already_running"|"answered"|"ui"}`.
`mode` is `mock` when no Claude runs (no `ANTHROPIC_API_KEY` and no logged-in local Claude Code subscription under `PAI_LLM_PROVIDER`, see [Settings](#settings)) or `PAI_FORCE_MOCK` is `1`.

`POST /api/sketch` with `{"image_base64": "...", "media_type": "image/png", "note": "..."}` starts a new product from a photo of a hand sketch, on a fresh bench.
`image_base64` is plain base64 or a data URL; the type is read from the bytes: PNG, JPEG or WebP up to 8 MB, anything else (HEIC too) is HTTP 400, and while Mechanic builds it is HTTP 409.
The photo is stored as `sketch-<n>.<ext>` in the session and served under `/files/`; the backend publishes `sketch` with status `reading` and runs `sketch_to_spec`, then `product_spec` and the normal flow.
The response is `{"ok": true, "mode": ..., "status": "started", "sketch": "sketch-1.png", "url": "/files/{session}/sketch-1.png"}`.
`GET /api/sketch/sample` returns the sample sketch of a phone stand (`agent/data/sketches/phone-stand.png`).

`GET /api/events` is a Server-Sent Events stream.
Each event is one `data: ` line of JSON, followed by a blank line.
Comments of the form `: keepalive` are not events.
A client that connects late receives the events already published, then the live ones.

`POST /api/reset` clears the session, the chat memory, and the event buffer, then publishes a `reset` event, a fresh tool snapshot, pending steps, and the timeline.
Every stream starts with a `reset` event, so a client that reconnects replays onto an empty state.

State-changing calls without a typed body (`/api/reset`, `/api/run/*`, `/api/cad/params`, `/api/cad/open`, `/api/versions/{n}/restore`, `/api/history/{id}/open`) need `Content-Type: application/json`, else HTTP 415, so a web page cannot fire them as a plain cross-site form post.

### Pause and stop

`POST /api/run/pause`, `POST /api/run/resume` and `POST /api/run/stop` (each with `Content-Type: application/json`, body `{}`) control the build that runs now, whatever started it: a message, a library item, Run test or Rebuild.
They answer `{"ok": true, "status": "..."}` with the new [run](#run) status, or HTTP 409 when nothing runs (pause, stop) or nothing is paused (resume).
A run only ever holds or ends at a checkpoint: before each tool call and before each orchestrator or sub-agent model round.
A tool that is running finishes first, so no file, version or chat card is left half written.
Pause answers `pausing` and the stream sends `paused` once the run reaches its checkpoint; Resume continues the same run from there, with the same conversation, so it is a true resume and not a restart.
Stop answers `stopping`; at the checkpoint the run ends, Mechanic says "Stopped. Everything built so far stays on the bench." and the status returns to `idle`.
Everything already built stays: parts, CAD files, renders, test results and committed versions.
With Claude, the conversation is closed cleanly (tool calls that did not run get a "stopped by the user" result), so the next message continues it.
A `POST /api/prompt` while the run is `paused` (and no question is open) stops that run at its checkpoint and starts the new message from there; while it is running or pausing it answers `status: already_running` as before.
The web shows Pause, Resume and Stop in a bar above the chat composer while a run is not `idle`.

A prompt that only asks to see or operate something in the dashboard ("show me the CAD", "open the library", "pull it apart", "compare v1 and v2", "focus on the battery", "mute") is answered with `status: "ui"` and `controls`: it becomes `ui_control` calls at once, also while a build runs, and never reaches the orchestrator.
`agent/src/pai_agent/app_control.py` matches these short commands; anything that changes the design goes to the orchestrator, which has the same tool.
A test or a rebuild requested during a build answers `already_running`.

`POST /api/control` with `{"control": "run:test"}` or `{"control": "run:rebuild"}` is a person pressing Run test (Simulation tab) or Rebuild and recheck (CAD tab): the product's MuJoCo test, or the CAD built again from the current numbers with the numbers and the test rerun.
It answers `{"ok": true, "status": "started"}`, or `ok: false` with `error` while a build runs or before anything is built.

`POST /api/answer` with `{"id": "...", "answer_id": "..."}` answers the open `question`.
It is HTTP 409 when no such question is open.
A `POST /api/prompt` while a question is open answers it when the text names an option's number ("fifteen", "15", "fünfzehn") or agrees ("yes", "ok", "agreed", "ja", "passt"), and returns `status: answered`.

`POST /api/cad/params` recomputes the current frame and emits a new `cad` event.
The body is either `{"name": "arm_length_mm", "value": 30}` or a flat object `{"arm_length_mm": 30, "thickness_mm": 2, "motor_spacing_mm": 6.6}`.
Missing names keep the last value, or the defaults 36 mm, 2 mm, and 6.6 mm.
A value outside the limits is HTTP 400 and does not emit `cad`; while Mechanic is building it is HTTP 409.

When the newest CAD build is a generated part (`cad_part`), the same call reruns that part's script with the new value, no model call needed, and any name from its `params` works within its slider limits.
For a product built from a spec, the slider names are `{part_id}.{param}` (such as `base.depth_mm`): that part is rebuilt from its script, the product is reassembled and every check that ran before runs again.
For the gripper, `grip_calc` then runs again, so a longer finger shows up as a lower finger force.

`POST /api/cad/open` opens the current part in the FreeCAD app.
The response is `{"ok": true, "path": "frame.FCStd"}` when the app launches, or `{"ok": false, "detail": "..."}` when there is no part or no FreeCAD app.
It prefers `frame.FCStd`, then STEP, then STL.

`GET /api/voice` returns `{"gemini_live": true, "stt": "reson8"|"browser", "realtime_url": "...", "turns_url": "...", "language": "en", "phrases": [...], "custom_model_id": null}`.
`gemini_live` says whether Mechanic's only voice, Gemini Live (`WS /api/voice/live`, see [GEMINI_LIVE.md](GEMINI_LIVE.md)), is configured.
`realtime_url` is Reson8's Realtime endpoint for push-to-talk dictation; `turns_url` is unused since the voice conversation is Gemini Live only.
`phrases` bias Reson8 toward our vocabulary (the `phrases` query parameter); a `custom_model_id` from `RESON8_CUSTOM_MODEL_ID` replaces them.
Mechanic never reads chat, `mascot` or `question` lines aloud; without Gemini Live he is silent and his text is the caption, and the system voice is never used.
`POST /api/voice/token` returns `{"access_token": "...", "expires_in": 600}`, a short-lived Reson8 token for the browser's WebSocket (subprotocols `["bearer", token]`), or HTTP 503 without `RESON8_API_KEY`.

### Library

The library holds the reference builds and the projects users saved, for a library view to browse and rebuild.

`GET /api/library` answers `{"ok": true, "items": [item, ...]}` in this order: the code references (the micro FPV drone first, the robot gripper second), the reference builds of the registry, then saved projects, newest first.
Each item is:

```json
{
  "id": "phone-stand",
  "name": "Desk phone stand",
  "summary": "Two PETG parts and four rubber feet; holds a 200 g phone at 65 degrees and takes a tap on the screen.",
  "kind": "reference",
  "source": "registry",
  "product": "generic",
  "printed": 2,
  "bought": 1,
  "requirements": 6,
  "thumbnail_url": "/api/library/phone-stand/thumbnail",
  "saved_at": "2026-10-24T13:02:11"
}
```

`kind` is `reference` (a known product) or `project` (saved from a session).
`source` is `code` (built by its own flow: the drone from the drone catalog, the gripper from the gripper flow, so their parts are never copied), `registry` (`agent/data/references/{id}/`, in the repository) or `saved` (`agent/runs/library/{id}/`, local).
`product` is `drone`, `gripper` or `generic`.
`requirements` is the number of requirements, or `null` for a code reference, whose requirements come from its own flow.
`thumbnail_url` is a studio render (PNG) or `null`; `saved_at` is local time or `null`.

`POST /api/library/{id}/open` (HTTP 404 for an unknown id) starts a fresh bench from that item: a code reference runs its own flow, any other item rebuilds the spec, the printed parts from their stored scripts, the bought parts, the assembly, every stored check, the render and the bill of materials, through the same tools and events as any build; then Mechanic asks what to change.
The response is like `POST /api/prompt`, with `reference`: `{"ok": true, "mode": "claude", "status": "started", "reference": "phone-stand"}`, or `status: already_running`.

`GET /api/library/{id}/thumbnail` returns the PNG, HTTP 404 without one.

`POST /api/library` with `{"id": "...", "name": "...", "summary": "..."}` (all optional) saves the current product build as a project with its latest render as thumbnail and answers `{"ok": true, "item": {...}}`; HTTP 400 when there is no finished product build or the id is taken by a reference, 409 while Mechanic is building.

With `"kind": "reference"` the same call promotes the build into the registry (`agent/data/references/{id}/`, with its scripts, picks, checks and render), so it can be committed; that needs `PAI_ADMIN=1` in the backend environment and answers HTTP 403 without it.

### Versions

`GET /api/versions` answers `{"ok": true, "versions": [...]}`, every version of the session in the `version` event shape without `type`.
`POST /api/versions/{n}/restore` makes version `n` current: Mechanic rebuilds it through the same tools as any build (a product from the spec, part scripts, picks and checks saved with it; the drone by re-picking its catalog parts, the frame with its parameters, the hover test, the render and the bill of materials) and commits the result as a new version with `trigger` `restore` and `restored_from` `n`, so history only grows.
It answers like `POST /api/prompt` with `restoring: n`; HTTP 404 for an unknown `n`, 409 while Mechanic is building.
Versions live in the session; a reset clears them.

### Chat history

Every chat is saved in its session directory (`agent/runs/sessions/<id>/`): `chat.json` (the list entry), `events.json` (the event log) and `state.pkl` (the build state and Claude's message history).
It is saved after every run, before a reset or a reopen, on shutdown, and when the history is listed; a bench nobody typed on and no version was built on is not saved.
A reset (the logo, or `POST /api/reset`) ends the chat, so the next one is a new entry.
The history belongs to the backend, like the bench: every access session sees the same bench, so it sees the same history.

`GET /api/history` answers `{"ok": true, "current": "<id>", "items": [...]}`, newest first, at most 100.
Each item is `{"id", "title", "product", "created_at", "updated_at", "messages", "versions"}`: the title is the first user message (cut to 60 characters), else the product name; `product` is the product label or empty; times are Unix seconds; `messages` counts chat lines.
`GET /api/history/{id}` answers `{"ok": true, "item": {...}}`, the list entry plus `chat`, the chat lines as `{"role", "text"}`, for reading a chat without opening it; HTTP 404 for an unknown id.
`POST /api/history/{id}/open` reopens a saved chat on the bench: the current chat is saved, the saved build state and Claude's memory come back, so the next prompt builds on that product, and every client receives the saved event log as a backlog: `{"type": "reset", "replay": true}`, the events, then `replayed`, followed by a fresh tool snapshot.
A question still open when the chat was saved comes back answered with its default.
It answers `{"ok": true, "id", "status": "opened"}`, or `status: "current"` for the chat already open; HTTP 404 for an unknown id, 409 while Mechanic is building.

### Optimizer

`POST /api/optimize/apply` with `{"id": "opt1", "variant": "C"}` builds that variant of an `optimize` run (a click on its point in the chart): Mechanic picks its battery with `parts_search`, builds the frame with `cad_frame`, then `physics_calc`, `simulate_drone`, `blender_render` and `bom_build`, and commits it as the next version labelled `Optimizer: C <label>` with its `diff` to the last version.
It answers like `POST /api/prompt` with `variant`; HTTP 404 for an unknown run or variant, 409 while Mechanic is building.

### Export

All three answer HTTP 404 before the first `bom`.
`GET /api/export/bom.csv` returns the current bill of materials as `anybuild-{product}-bom.csv`: UTF-8 with a byte order mark (so Excel reads it), comma separated, dot decimals, columns `name, qty, unit_price_eur, line_total_eur, weight_g, shop, url, price_source, availability, checked_at`, then a `Total` row.
`GET /api/export/bundle.zip` writes `anybuild-{product}-v{n}.zip` into the session directory and returns it. One folder holds `cad/` (every STL and STEP of the build: the drone frame, each spec part, the gripper part, `assembly.stl` and `assembly.glb`), `scripts/` (the FreeCAD scripts), `bom.csv`, `build-guide.md` (the latest `build_guide`, else an ordered list from the bill of materials: print the printed parts, fit the bought ones, verify the checks), `firmware/` with the latest firmware file, `render.png` (the latest studio render, or the recorded still without Blender) and `README.md` (requirements with pass/fail and detail, key numbers, print settings per material, and any STL without a STEP under "Missing files").
`GET /api/export/order` answers `{"ok": true, "shops": [{"shop", "items": [{name, qty, unit_price_eur, line_total_eur, url, price_source}], "total_eur", "live"}], "print": {"items": [{name, qty, material, mass_g}], "filament_g", "cost_eur"}, "total_eur"}`, shops by total, most expensive first; printed parts (shop `printed` or a `url` that is not an http link) go to `print`. The shop totals plus `print.cost_eur` add up to `total_eur`.
Share in the dashboard saves a spec product with `POST /api/library` and copies `?project={id}`; the drone and the gripper share their code reference id (`micro-drone`, `robot-gripper`) without saving.
The dashboard opens `?project={id}` by calling `POST /api/library/{id}/open` once when the backend is live, then drops the parameter from the URL; an id that is not in the library shows a notice instead.

### Community

The community holds projects people published, for others to open and keep working on (remix).
Seed entries live in the repository under `agent/data/community/{id}/entry.json` and rebuild from a library item; published entries live under `agent/runs/community/{id}/` (local, not committed) with the whole project.
`agent/scripts/seed_community.py` rebuilds the seeds in mock mode, writes their real numbers into `entry.json`, and exports the same feed to `web/public/community/feed.json`, which the dashboard reads while the backend is offline.

`GET /api/community?sort=new|popular&q=...` answers `{"ok": true, "items": [entry, ...]}`: newest first, or with `sort=popular` the most remixed first; `q` keeps the entries whose title, description, author or product mentions it.
HTTP 400 for another `sort`.
Each entry is:

```json
{
  "id": "quiet-desk-fan",
  "title": "Quiet USB desk fan",
  "description": "An 80 mm USB fan on a printed neck, bracket and 150 mm base.",
  "author": "maker.kai",
  "published_at": "2026-10-23T09:30:00",
  "product": "generic",
  "product_label": "USB Desk Fan",
  "base": "desk-fan",
  "seed": true,
  "remixed_from": null,
  "remixes": 4,
  "metrics": {"requirements_passed": 6, "requirements": 6, "parts": 5, "cost_eur": 16.53, "mass_g": 280.1, "printed": 3},
  "bom": [{"name": "80 mm 5 V USB fan 80x80x25", "qty": 1, "unit_price_eur": 5.5}],
  "versions": [],
  "files": [],
  "thumbnail_url": "/api/community/quiet-desk-fan/thumbnail"
}
```

`product` is `drone`, `gripper` or `generic`; `base` is the library id a remix rebuilds from, or `null` when the entry stores its own spec, FreeCAD scripts and picks (a published product built from a spec).
`remixed_from` is `{"id", "title", "author"}` of the original or `null`.
`remixes` is a seed's starting count plus the number of entries published as remixes of it.
`metrics` always has `mass_g`, `cost_eur`, `parts` (bill of materials lines), `requirements_passed` and `requirements`; the drone adds `thrust_to_weight` and `flight_time_min`, the gripper `grip_force_n`, a spec product `printed`.
`bom` is the bill of materials, `versions` the versions in the `version` event shape, `files` the studio renders and CAD files (STEP, STL) the entry keeps.

`GET /api/community/{id}` answers `{"ok": true, "item": entry}`, HTTP 404 for an unknown id.
`GET /api/community/{id}/thumbnail` returns the PNG (the entry's latest render, else its base library item's), HTTP 404 without one.
`GET /api/community/{id}/files/{name}` returns one of the entry's `files`.

`POST /api/community` with `{"title": "...", "description": "...", "author": "..."}` publishes the current build and answers `{"ok": true, "item": entry}`.
It keeps the spec, the FreeCAD script of every printed part, the picks and the checks (a spec product), the bill of materials, the numbers, the versions, the studio renders and the CAD files.
The drone and the gripper are built by their own code, so their entries rebuild through that flow (`base` is `micro-drone` or `robot-gripper`) and keep the published numbers, parts, renders and CAD files next to it.
When the bench holds a remix, the new entry's `remixed_from` links to the original.
HTTP 400 without a title or author or without a finished build (no bill of materials yet), 409 while Mechanic is building.

`POST /api/community/{id}/remix` (HTTP 404 for an unknown id) opens the entry on a fresh bench: it sends a `remix` event, rebuilds the entry through the same tools and events as `POST /api/library/{id}/open`, and Mechanic asks what to change.
The response is like `POST /api/prompt`, with `remix`: `{"ok": true, "mode": "mock", "status": "started", "remix": "quiet-desk-fan"}`, or `status: already_running`.

### Objects

NVIDIA's SimReady objects are real things a build stands next to, is sized for or picks up: the 2,575 packages of the Hugging Face dataset `nvidia/simready-assets` at the pinned revision `524747d9b5e1` (food, kitchenware, boxes, hand tools and more), each a USD asset with its mesh, textures, mass, friction and Wikidata semantics, all under CC BY 4.0.
The catalogue is offline in `agent/data/simready/index.json`, built once by `agent/scripts/build_simready_index.py`; a package itself is fetched when `scene_object` first uses it (see [object](#object)).

`GET /api/objects?q=banana&limit=20&offset=0` answers `{"ok": true, "total": 23, "source": "nvidia/simready-assets@524747d9b5e1", "items": [object, ...]}`, best match first.
Every word of `q` must match the object's Wikidata class, title, id, category or description (a plural matches its singular, a word of three letters or more matches as a prefix); the class weighs most, among equally good matches the smaller download comes first, and an empty `q` lists the catalogue by id.
`limit` is 1 to 100 (default 20) and `offset` 0 or more, else HTTP 400.
Each item is:

```json
{
  "id": "food_produce_banana_a01",
  "title": "Banana",
  "category": "Food",
  "description": "banana fruit",
  "wikidata": {"class": "banana", "qcode": "Q503"},
  "size_mm": [116.0, 162.2, 31.6],
  "mass_g": 242.8,
  "mass_estimated": true,
  "download_mb": 1.2,
  "thumbnail_url": "/api/objects/food_produce_banana_a01/thumbnail",
  "license": "CC-BY-4.0",
  "source": "nvidia/simready-assets@524747d9b5e1"
}
```

`size_mm` is the object's bounding box `[x, y, z]` with Z up.
`mass_g` is SimReady's estimate from the material's density, the volume and a fill ratio, so `mass_estimated` is always `true`.
`download_mb` is what the first use of the object downloads: food and kitchenware take one to a few megabytes, while equipment ships hundreds, almost all of it textures.

`GET /api/objects/{id}/thumbnail` returns the object's studio render on a transparent background as a 256 px WebP (`image/webp`).
The first request downloads that one file and checks it against the SHA-256 the catalogue keeps for it; every later request is the cached image, without the network.
It is HTTP 404 for an id that is not in the catalogue, and 503 when the render is not cached yet and Hugging Face is unreachable.

### Bench

`GET /api/bench` answers `{"ok": true, "runs": [run, ...]}`: the results `agent/bench/run.py` wrote to `agent/bench/results/live.json` and `agent/bench/results/mock.json`, the live run first; a missing file is left out, so no run yet is `"runs": []`.
A run is `{"mode": "live" | "mock", "note", "started_at", "finished_at", "orchestrator_model", "subagent_model", "concurrency", "timeout_s", "budget_s", "prompts_total", "summary", "results"}`; `note` says a mock run is not a measure of the live agent, and the models are `null` in mock mode.
`summary` is `{"prompts", "ran", "passed", "pass_rate", "checks_passed", "checks_total", "check_pass_rate", "cost_usd", "cost_per_product_usd", "cost_per_valid_product_usd", "time_s", "retries", "cad_fallbacks", "input_tokens", "output_tokens"}`.
Each result is one prompt: `{"id", "title", "category", "prompt", "status": "done" | "timeout" | "error" | "skipped", "error", "pass", "checks": [{"id", "label", "pass", "detail"}], "checks_passed", "checks_total", "time_s", "tool_calls", "tool_errors", "fixes", "retries", "cad_fallbacks", "input_tokens", "output_tokens", "cache_read_tokens", "cost_usd", "agents", "model_rounds", "product", "mass_g", "parts_eur", "session_id"}`.
`pass` is true when the run finished and every expected check passed. A check id is `built`, `cad`, `bom`, `render`, or `req:<id or check>`, which passes when the build has that requirement and it is met.
The bench sends no SSE events of its own; "Open on bench" in the drawer runs the prompt again with `POST /api/reset` and `POST /api/prompt`.

### Settings

`GET /api/settings` answers `{"ok": true, "orchestrator_model": "claude-opus-5-5", "orchestrator_effort": "high", "subagent_model": "claude-sonnet-5-5", "subagent_effort": "medium", "delegation": true, "models": [{id, label}], "efforts": ["low", "medium", "high", "xhigh", "max"]}`.
`POST /api/settings` with any of those five fields changes them for the next request and answers the same shape; HTTP 400 for an unknown effort or a model id that does not start with `claude-`.
The answer also carries `llm_provider` (`auto`, `api` or `subscription`, from `PAI_LLM_PROVIDER` until changed), `provider` (`{"requested", "active": "api"|"subscription"|"mock", "detail", "public"}`) and `providers` (`[{id, label}]`).
`POST /api/settings` with `llm_provider` switches where Claude runs: `api` is the Anthropic API key, `subscription` the Claude Code installed and logged in on this machine, `auto` the key when set, else the subscription when logged in, else the mock.
With `ANYBUILD_ACCESS_CODE` set (a public server) `subscription` is refused with HTTP 400 and the reason in `detail`.
The defaults come from `PAI_ORCHESTRATOR_MODEL` (else `ANTHROPIC_MODEL`), `PAI_ORCHESTRATOR_EFFORT`, `PAI_SUBAGENT_MODEL`, `PAI_SUBAGENT_EFFORT` and `PAI_DELEGATION`.

The same answer carries the user's 3D printer: `printer` is `null`, or `{model, name, maker, bed_mm, nozzle_mm, max_hotend_c, max_bed_c, enclosure, materials, source_url, filaments, printable, not_printable}` (`filaments` the user's spools, `printable` those this printer prints, `not_printable` the rest, for example ABS or ASA on a printer without an enclosure).
`printer_catalog` is `{printers: [{id, name, maker, bed_mm, nozzle_mm, max_hotend_c, max_bed_c, enclosure, materials, source_url}], filaments: [{id, name, eur_per_kg, needs_enclosure}], checked}`; the profiles come from each maker's spec page (`source_url`), the filament properties from the makers' data sheets (`agent/src/pai_agent/printers.py`).
`allow_estimated` (from `PAI_ALLOW_ESTIMATED`, default `false`) is the parts exploration switch; `POST /api/settings` with `allow_estimated` true lets a part found on the web carry labelled estimates for its non-critical numbers so a test build goes on, false keeps every part number sourced.
`POST /api/settings` with `printer` `{model, filaments}` sets it (filaments `PLA`, `PETG`, `ABS`, `ASA`, `NYLON`, `TPU`; leaving `filaments` out takes every material the printer prints) and `null` clears it; HTTP 400 for an unknown model or filament.
The dashboard keeps the choice in the browser and sends it again whenever the backend connects. With a printer set, every request to the orchestrator starts with one line naming the printer, its bed and the filaments it prints; without one the build runs as before.

### Learning mode

`POST /api/explain` with `{"kind": "...", "id": "...", "chat": false}` explains one decision of the current build (`agent/src/pai_agent/explain.py`).
`kind` is `swap` (`id` a part category: the part before and after, the numbers on each side and the runs around it), `part` (a category or spec part id), `requirement` (a requirement id), `sim` (a run number) or `param` (a CAD parameter, `arm_length_mm` or `{part_id}.{param}`).
It answers `{"ok": true, "key", "kind", "target_id", "title", "text", "formula", "numbers": [{"label", "value", "unit"}], "source": "claude"|"template", "model": "claude-haiku-5-5"|null}`; HTTP 404 when the decision does not exist yet, such as a requirement whose check has not run.
The facts and the formula line come from the build state and the published events (the same formulas as `analysis.py` and `tools/physics.py`), so their numbers are computed.
With `ANTHROPIC_API_KEY` or the local Claude subscription, Claude Haiku (`ANTHROPIC_VOICE_MODEL`) writes `text` from the facts and the formula only; a reply with a number that is not in them, a 6 s timeout or no key gives the template text and `source: "template"`.
Answers are cached in memory by `key` (kind, id and a hash of the facts), so a repeated call is instant and a rebuild with new numbers gets a new explanation.
Every answer is also published as an `explain` event; `chat` is copied into it.

`POST /api/training/{job_id}/claim` with `{"client": "..."}` lets one dashboard tab take a queued browser training job; it returns the job's `spec`, `population`, and `generations`.
It is HTTP 409 when another client already holds the job, and 404 for a job of an earlier session.
`POST /api/training/{job_id}/progress` with `{"client", "status": "running"|"done"|"failed", "step", "generation", "best_score", "best_params", "best_metrics", "gains", "error"}` from the claiming client publishes a `training` event (`gains` is kept only with `status: "done"`); other clients get HTTP 409.
`POST /api/stress/{job_id}/claim` with `{"client": "..."}` lets one dashboard tab take a queued drone stress test; it returns `{"ok", "job_id", "product", "spec", "gains", "seed", "worlds"}`, where `worlds` are the 50 seeded worlds `{i, mass_scale, motor_scale, gust_mps, gust_dir_deg, gust_start_s, gust_len_s, downdraft_share, noise_m}`.
It is HTTP 409 when another client holds the job or it is over, and 404 for a job of an earlier session.
`POST /api/stress/{job_id}/progress` with `{"client", "status": "running"|"done"|"failed", "results": [{i, metrics, trajectory}], "error"}` from the claiming client hands finished worlds to the backend, which scores them and publishes the `stress` events; `metrics` are the drone episode's `crashed`, `drift_m`, `low_z_m`, and `tail_z_m`, and `trajectory` is `[[t, x, y, z], ...]` at 20 Hz.
`GET /api/training/browser` returns `{"ok": true, "job": {...}}` with the latest browser job of the session in the `training` event shape without `type`, or `job: null`.

`GET /api/health` returns `{"ok": true, "mode": "mock"|"claude", "provider": "api"|"subscription"|"mock", "busy": bool, "access": "open"|"required"}`; `busy` is true while a run is in flight, which the end-to-end tests and agent/scripts/profile_build.py wait on.
The dashboard calls it on start: when the backend answers it opens with an empty bench (after the access code, when `access` is `required`); without a backend it shows "Live backend offline, try again shortly" and retries.

### Partner status and Director mode

`GET /api/status` returns `{"partners": [{"id", "label", "state", "detail"}], "isaac": {"host", "gpu", "state", "detail", "last_run"}}`; the Claude row also has `provider` (`api`, `subscription` or `mock`), which the top bar shows.
It requires the same access session as other API routes and never returns keys, tokens or private-key paths.
Partner ids are `claude`, `reson8`, `gemini`, `freecad`, `blender` and `isaac`.
`state` is `live`, `offline` or `mock`; `detail` explains the provider and its fallback in English.
For remote APIs, `live` means credentials are configured and the integration is enabled, not that authentication or quota has been verified.
Status checks make no billable API calls.
Claude is `mock` when disabled or forced into mock mode.
Missing speech keys are `offline`, with browser recognition or text replies as the fallback.
FreeCAD and Blender report local availability; observed tool errors and CAD fallback to CadQuery override availability until a later successful result or session reset.
Gemini Live is Mechanic's only voice; without it Mechanic replies with text.
Gemini availability follows the existing Studio key or Vertex project and `gcloud` configuration.
The frontend polls every 15 seconds and marks unavailable status responses offline.

The Isaac chip opens the Omniverse tab, including on an empty bench, and reports `Connected` with the GPU name only after a successful read-only SSH `nvidia-smi` probe.
The probe uses the existing `ISAAC_SSH_*` / `RUNPOD_SSH_*` configuration and the job's noninteractive `accept-new` host policy, with a disposable known-hosts sink so polling never changes the user's SSH files.
It times out after five seconds and caches its result for 15 seconds.
No configured host, rejected SSH authentication or a failed GPU query reports `offline`.
`isaac.last_run` is `null` before the first job, otherwise `{job_id, mode, status, source, stage, detail}` from the latest Omniverse event; absent fields are `null`.
The Omniverse connection header shows host, GPU, status and last run; existing SSE `omniverse` events update its live export, upload, execute and download progress.
Running Isaac jobs requires a connected GPU and the supported drone reference.

Director mode is a browser preference, enabled by default and toggled in Settings.
Running `teile` or `cad` steps and CAD artifacts select CAD; running `simulation` steps and simulation results select Simulation; rendering selects the Model render view.
Live Omniverse job events select Omniverse; recorded GPU fallbacks do not take over the canvas.
A `version` event selects the 3D Model and compares it with the previous version of the same product when available.
Manual canvas tab clicks pause Director for 30 seconds, then apply the latest pending activity even if no additional event arrives.
A `tab` URL parameter gets the same initial grace period.
Director preserves browsing in other main views and uses a short canvas fade that respects reduced-motion preferences.
The top bar contains partner status and Settings; the versions are in the Logbook.

### Check adapters

`GET /api/adapters` answers a list with one row per engine behind AnyBuild's checks, so a person sees what this machine can check and what is missing; the dashboard shows it under Settings → Check adapters (or with `?adapters`).
It requires the same access session as other API routes and never starts a tool: it reads PATH, the usual application and bin folders and version files, so it answers within milliseconds.
Each row is:

```json
{
  "id": "calculix",
  "name": "CalculiX and gmsh",
  "domain": "mechanics",
  "provides": ["FEM of printed parts"],
  "remote": false,
  "available": true,
  "version": null,
  "path": "/Applications/FreeCAD.app/Contents/Resources/bin/ccx",
  "detail": "Meshes each printed part with gmsh and solves its load cases in CalculiX; both ship with FreeCAD 1.1.4.",
  "install_hint": "Comes with FreeCAD (`brew install --cask freecad`), next to freecadcmd; `PAI_CCX` and `PAI_GMSH` name other executables.",
  "last": {"at": 1792970692, "pass": true, "summary": "FEM of Base plate passed: safety 3.1x, needs 2x"}
}
```

The rows come in this order, grouped by `domain`: `mechanics` (`freecad`, `calculix`, `blender`), `electronics` (`sparkbench`, `kicad`, `ngspice`, `freerouting`, `node`), `simulation` (`mujoco`, `robouse`, `isaac`) and `manufacturing` (`slicer`).
`provides` names the checks and outputs the engine gives, such as `ERC` and `DRC` for `kicad`.
`remote` is `true` for an engine on another machine, the Isaac GPU host, whose `available` means reachable; the dashboard shows Connected or Offline there, Installed or Missing for the others.
`available` is `true` when the engine is where the code that runs it looks, `false` when it is not, and `null` while the Isaac SSH probe still runs; the dashboard then asks again after a few seconds.
`version` comes from files (the Info.plist of the app the tool ships in, a Homebrew or nvm folder, a package's dist-info, the jar's name, SparkBench's commit), else `null`; `path` is where the engine was found, with the home folder as `~`, else `null`.
`detail` says in one or two English sentences what the engine does here or what happens without it, and `install_hint` how to install it, with commands in backticks.

Each engine is looked up the way the code that runs it looks:

- `freecad`: `freecadcmd` as `cad_part` finds it, plus the open FreeCAD window (freecad-mcp at `FREECAD_MCP_URL`, a local port check, skipped with `FREECAD_GUI=off`); either one makes it available.
- `calculix`: gmsh and `ccx` as `fem_check` finds them (`PAI_GMSH`, `PAI_CCX`, PATH, next to `freecadcmd`).
- `blender`: as `blender_render` finds it.
- `slicer`: PrusaSlicer or OrcaSlicer as `print_prep` finds it (`PAI_SLICER`).
- `kicad`, `ngspice`, `freerouting`: where SparkBench's server finds them: `KICAD_CLI`, then `KiCad.app` from `KICAD_APP`, `~/Applications`, `/Applications/KiCad` or `/Applications`, then PATH and `/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin`; ngspice on PATH or in those folders; `FREEROUTING_JAR` or `~/.cache/sparkbench/freerouting/freerouting-2.5.0.jar`, with Java 21 or later from `JAVA`, Homebrew's OpenJDK or `/usr/lib/jvm/default-java`, never PATH.
  KiCad before 8 and Java before 21 count as missing.
- `sparkbench` and `node`: as `circuit_design` finds them ([circuit](#circuit), `agent/src/pai_agent/sparkbench.py`): the checkout at `SPARKBENCH_DIR` or `~/.cache/anybuild/sparkbench/<commit>` with its npm packages, the bridge's own `tsx`, and Node.js on PATH or in Homebrew's folders; `detail` names what is missing.
- `mujoco`: the Python package in the backend environment.
- `robouse`: `anybuild-robouse` as `robouse_trial` finds it ([trial](#trial)): `PAI_ROBOUSE_BIN` (`off` turns it off), the bridge's own environment (`anybuild-robouse/.venv`), else on PATH; Robo Use without the bridge counts as missing.
- `isaac`: a GPU host in `RUNPOD_SSH_HOST` or `ISAAC_SSH_HOST` that passes the SSH `nvidia-smi` probe of [Partner status](#partner-status-and-director-mode); the row reuses that probe's 15 s cache, waits at most 0.2 s for a new one and answers the last known state meanwhile.

`last` is the adapter's latest run on this machine, or `null`: `at` in Unix seconds, `pass`, and `summary`, one English line.
The backend records runs from the live event stream, never from a backlog or a reopened chat, in `agent/runs/adapters.json` (not committed), so they outlast a reset and a restart.
A run is a `cad` event of a part or the drone (`source: "freecad"` passes; `cadquery` fails, while FreeCAD is installed), a `render` (the recorded still fails, while Blender is installed), a `sim` or `mission` result (MuJoCo), a `fem` result (CalculiX), a `print` plan the slicer made (a part's `slicer_error` fails it; an estimate without a slicer is no run), a `circuit` (SparkBench, its `ok`), a finished `trial` (Robo Use, its `verdict`; a recorded trial is no run, a refused task fails) and a live, finished `omniverse` result.
KiCad, ngspice and Freerouting have no run until the tools that run them publish their results.

### Access

With `ANYBUILD_ACCESS_CODE` set on the backend, every route except `GET /api/health` and `POST /api/access` (including `GET /api/events`, the voice routes and `/files/`) needs a session, else HTTP 401 with `{"detail": "...", "access": "required"}`.
`POST /api/access` with `{"code": "..."}` (`Content-Type: application/json`) returns `{"ok": true, "token": "...", "expires_at": <unix seconds>}` and sets the same token as an `anybuild_session` cookie (`HttpOnly; Secure; SameSite=None`), valid for 24 hours.
A wrong code is HTTP 401; ten wrong codes from one IP in 15 minutes (or 200 from all IPs) are HTTP 429 until the window passes.
Clients send the token as `Authorization: Bearer <token>`, as the cookie, or as `?access_token=<token>` on URLs the browser loads itself (EventSource, images, models, videos).
`GET /api/access` is HTTP 200 while the session is valid, and always 200 without an access code.

With an access code, these calls are rate limited per session and, at three times the limit, per IP, in a sliding hour: builds (`POST /api/prompt`, `POST /api/sketch`, `POST /api/library/{id}/open`, `POST /api/versions/{n}/restore`, `POST /api/control`; `ANYBUILD_LIMIT_BUILDS`, default 20), `POST /api/voice/speak` (`ANYBUILD_LIMIT_SPEECH`, 300), `POST /api/voice/token` (`ANYBUILD_LIMIT_STT`, 60), `POST /api/cad/params` (`ANYBUILD_LIMIT_CAD`, 120), and `POST /api/explain` (`ANYBUILD_LIMIT_EXPLAIN`, 120).
Over the limit, the answer is HTTP 429 with `{"detail": "Hourly limit of 20 builds reached. Try again in 12 minutes.", "limit": "build"}` and a `Retry-After` header; the dashboard shows `detail` as a notice.

Browsers may call the backend from localhost, the Mac app, `https://anybuild-demo.vercel.app` and its preview deployments, and origins in `ANYBUILD_CORS_ORIGINS`, with credentials.

`GET /files/{bucket}/{name}` serves one file.
`bucket` is the session id, or `fallback` for recorded clips.
`name` is a single path segment such as `frame.stl`, `frame.step`, `frame.glb`, `view.png`, `studio-v1.png`, `render.png`, or `hover.mp4`.
CAD URLs in events carry `?build=N`, which the server ignores; it only keeps browsers from showing an older part.

These reads stay as aliases and are not part of the event stream:

- `GET /api/artifacts/frame.stl` returns the current session STL.
- `GET /api/artifacts/fallback-training.mp4` returns the offline clip when that file exists.
- `GET /api/artifacts/training.mp4` returns a video copied back from the pod.

## SSE events

Every object has `type`.
Unknown extra fields should be ignored.

### reset

The first event of every stream and of every server reset: drop all session state.
`replay: true` (only after `POST /api/history/{id}/open`) means a saved chat's events follow up to `replayed`, to be applied as a backlog without animations or speech.

### explain

One decision explained, the `POST /api/explain` answer without `ok`, plus `chat`.
`chat: true` means a live event asked for it (learning mode on: a part swap after its new numbers, a requirement turning `met: false`, a failed `sim`, a changed CAD parameter), so the client shows it as a chat card; otherwise it is the answer to a "Why?" click and only shows there.
The client keeps the latest event per `key`.

### replayed

No fields, and only on this connection: everything before it was backlog from earlier, everything after it is live.
Apply the backlog without animations.

### run

`status` of the build on the bench: `running`, `pausing` (asked to pause, the current step still finishes), `paused`, `stopping` (asked to stop, the current step still finishes) or `idle`.
Sent when a run starts and ends and on every change through [pause and stop](#pause-and-stop).

### step

`id` is `meeting`, `teile`, `cad`, `render`, `simulation`, `training`, or `stueckliste`.
The mock story uses `training` for the train loop after a request's missions pass (`train_controller`), and a "train it" prompt does too.
`status` is `pending`, `running`, `done`, or `failed`.
`label` is `Spec`, `Parts`, `CAD`, `Render`, `Simulation`, `Training`, or `BOM`; the `meeting` id is the spec step, its name kept for older recordings.

A step can be `done` while a tool on that step is `offline`.
In the mock story, render is done after Blender and Isaac Sim have both been asked.
Training is done when the fallback curve has been played.
The tool pill still shows `offline`.

### chat

`role` is `user` or `agent`.
`text` is the utterance.
`voice: true` marks a spoken line: a user turn transcribed by Gemini Live (or dictated with push-to-talk through Reson8 or the browser), or a line Mechanic said aloud in a Gemini Live conversation.

### tool

`name` is the tool name from the list below.
`status` is `connected`, `running`, `ok`, `error`, or `offline`.
`detail` is a short English line.
The final event of a call (any status but `running`) carries `ms`, the tool's wall time in milliseconds.
`timed_out: true` marks a tool stopped by its time limit (agent/src/pai_agent/timeouts.py); `status` is then `error` (Blender: `offline` with the recorded still) and `detail` names the tool and the limit, the same line the agent says in the chat.
`cached: true` marks a FreeCAD part reused from agent/runs/cache/ because the script, parameters and material were identical.
A `cad` event's `source` is `cadquery` when FreeCAD was missing or stuck and CadQuery built the part's envelope as a plain block.

### requirement

Requirements come from what the user typed or said, never from a template or a recording.
For the drone, `id` is `budget`, `flight_time`, `weight`, `hover`, `printable`, or a mission row: `top_speed` (min km/h), `turn_rate` (min °/s), `hold_error` (max cm) or `chase_time` (max s); `product_brief` sets `budget`, `flight_time`, `weight` and any mission limit from the numbers in the request, and adds `hover` and `printable`.
`simulate_mission` adds the row of each mission it flies when the brief has none, as Mechanic's proposal (60 km/h, 120 °/s, 15 cm, 4 s), and judges it; a revised brief keeps the mission rows it does not mention.
`text` is the requirement.
`source` is `user` when the limit is in the user's words, or `proposed` when Mechanic proposed it because the request named no number.
A requirement counts as `user` only when its quote is really in a request of this session; any other quote turns it into `proposed`.
`source_quote` is the user's words (`speaker` `You`), or Mechanic's reason for a proposal (`speaker` `Mechanic`); `time` is when it was set.
`changed_from` is the earlier text when a later message changed it, else `null`.
`met` is `true`, `false`, or `null`.
`null` means the build does not know yet.
For a product built from a spec, `id` is the spec requirement id, the quote is the user's request, and `detail` is the number its check found against the limit, such as `0.81 N, min. 0.75 N`; `detail` is absent or `null` before the check ran.
The first `fem_check` adds the row `strength` (min `2x` safety factor of the printed parts, proposed by Mechanic) when no requirement judges strength yet; the drone gets it too, judged by the printed frame's FEM.

### metrics

`weight_g`, `thrust_to_weight`, `flight_time_min`, `price_eur`.
Numbers are already rounded.
The drone's `physics_calc` adds its flight performance from the chosen parts' specs, every one an estimate (`estimate: true`): `top_speed_mps` and `top_speed_kmh` (drag against the thrust that fades with airspeed, on a fresh pack), `accel_mps2` (horizontal, from a hover), `time_to_90pct_s`, `climb_rate_mps`, `turn_rate_dps` (90 degrees over the time to turn them at the hard-turn mission's 8 m/s, rolling in included) and `turn_radius_m`, `flip_time_s` (a 180 degree roll), `flight_time_full_speed_min` and `flight_time_full_throttle_min` (on the sagging, draining pack).
`performance` also carries `top_speed_end_kmh` (the top speed at the end of a full-speed flight), `flight_time_hover_min`, `thrust_full_fresh_g` (full-throttle thrust on the fresh pack under load) and `pack_sag_v`.
They use the airframe and power train the MuJoCo missions fly (the same thrust curve, pack sag, drag and 95 % thrust and 70 degree tilt limits), so `top_speed_kmh` and `turn_rate_dps` estimate what the speed run and the hard turn measure.
`estimated_inputs` (only when there are any) lists the chosen parts whose numbers are estimates rather than stated on their pages, one `"Part name: field, field"` line each; the results card says the numbers rest on them.
A field is absent when the parts cannot give it; all are `0` when the build cannot hover.
`price_eur` is a total to verify, not a checkout: catalog samples, or live shop prices once `bom_build` found them.
After `bom_build` finds live prices, a second `metrics` event carries the live total in `price_eur`; the other numbers repeat.

For a product other than the drone the event carries `cards` instead of the drone numbers, and the panel shows those.
Each card is `{key, label, value, unit, digits, limit, ok, pending}`: `limit` is the line under the number (such as `min. 2 ×`), `ok` says whether it meets its requirement, and `pending: true` means its check has not run yet.
A product built from a spec sends `weight_g` and `price_eur` (product mass without external loads, and cost) and four cards: Mass, Cost, and the next two requirements with a number (tip-over, deflection, torque safety, runtime, push test tilt, drop load, size, power headroom, thermal or roll-over).
The gripper sends `weight_g`, `price_eur`, `grip_force_n`, `safety_factor`, and the cards Grip safety, Finger force, Weight and Price.

### product

`id` is `drone`, `gripper`, or the slug of a product spec such as `phone-stand`; `label` is the display name.
`kind` is `generic` for a product built from a spec.
Sent by `product_brief` and `product_spec`; a revised spec that keeps the name or any part id keeps the same `id` (only the `label` changes). `requirements` lists the requirement ids the product has now (a spec, or a drone brief), so the client drops the others.
When the product changes, the client drops the other product's requirements, numbers, parts, runs, CAD, renders and bill of materials.
Without this event a fresh bench has no product; the first drone event (drone metrics, a drone part, a hover run, the frame CAD, a version) makes it the drone.

### sketch

The photo of a hand sketch a build started from: `id` (`sketch-1`), `url` (under `/files/`, never the image data), `status` and `note` (what the user wrote with it).
`reading` comes first, when the photo is stored; `sketch_to_spec` then publishes `read` with `summary` (one sentence), `read` (`[{label, value, unit, confidence}]`, confidence `high`, `medium` or `low`), `unreadable` (strings), `product` (the spec id) and `source` (`claude` or `recorded`), or `failed` with `error` and `unreadable`.
The client shows the latest sketch in the Model tab; a `reset` drops it, and so does a `product` event for another product than the sketch's.

### remix

`{"type": "remix", "id": "quiet-desk-fan", "title": "Quiet USB desk fan", "author": "maker.kai"}` says the bench holds a remix of that community entry.
Sent once when `POST /api/community/{id}/remix` starts; the client shows a "Remixed from" link back to the original until the next reset, and publishing the build links the new entry to it.

### object

A NVIDIA SimReady object in the scene, placed by `scene_object`: context for the build (the mug a holder fits, the banana a gripper picks up, the pan it goes into), never part of the bill of materials.

```json
{
  "type": "object",
  "id": "kitchenware_pan_a01",
  "title": "Frying pan",
  "wikidata": {"class": "frying pan", "qcode": "Q127666"},
  "size_mm": [259.3, 431.0, 44.5],
  "mass_g": 2956.5,
  "mass_estimated": true,
  "mass_source": "SimReady estimate (the rigid body's mass properties)",
  "friction": 0.4,
  "glb_url": "/files/{session}/simready-kitchenware_pan_a01.glb?v=e8aca0e5dd",
  "thumbnail_url": "/api/objects/kitchenware_pan_a01/thumbnail",
  "mjcf_url": "/files/{session}/simready-kitchenware_pan_a01.xml?v=38cfd49199",
  "license": "CC-BY-4.0",
  "attribution": "\"kitchenware_pan_a01\" by NVIDIA, from the SimReady assets (https://huggingface.co/datasets/nvidia/simready-assets/tree/524747d9b5e1f21b5b18b56041788c01d745f1a1/kitchenware_pan_a01), licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Changed by AnyBuild: converted from USD to STL meshes and an MJCF body for MuJoCo (Z up, metres); collision split into 12 convex parts with CoACD instead of one convex hull; converted from USD to glTF binary (GLB) with Blender; thumbnail resized to 256 px WebP.",
  "changes": ["Converted from USD to STL meshes and an MJCF body for MuJoCo (Z up, metres)", "Collision split into 12 convex parts with CoACD instead of one convex hull", "Converted from USD to glTF binary (GLB) with Blender", "Thumbnail resized to 256 px WebP"],
  "source": "nvidia/simready-assets@524747d9b5e1",
  "role": "target",
  "position_mm": [0.0, 0.0, 22.2],
  "rotation_deg": [0.0, 0.0, 0.0],
  "origin_mm": [0.0, 85.8, -0.9],
  "collision": {"method": "coacd", "parts": 12, "cavity_mm": 22.8},
  "grasp_points_mm": [[-167.4, 0.0, 13.9], [167.4, 0.0, 13.9]],
  "textured": true,
  "warnings": [],
  "reason": "The gripper puts the banana into it."
}
```

`id` is the SimReady package id; `title`, `wikidata` (class and Q-code from the USD's semantics), `size_mm` and `mass_g` are as in [Objects](#objects).
`mass_estimated` is always `true`, because SimReady computed every mass from density, volume and a fill ratio; `mass_source` says which mass the USD declares, the rigid body's own or the sum of its colliders' (UsdPhysics precedence).
`friction` is the sliding friction MuJoCo uses: the dynamic friction of the physics material the USD binds to the largest collision group, the lower of the two coefficients, so a grasp that holds in MuJoCo is not held by friction the object lacks.
`mjcf_url` is a standalone MJCF file with one `<body>`: a free joint, an `<inertial>` with the USD's mass, centre of mass and full inertia, the visual meshes per material (group 2, no contact, the material's colour), the convex collision meshes (group 3, with the friction) and the grasp points as sites (group 4).
Its meshes are STL files next to it in the session, so it loads on its own or `<include>`s into a scene; the body sits at `origin_mm` with the rotation, in metres.
`glb_url` is the model for the 3D view: glTF binary, Y up, metres, the same origin as the MJCF body, with base colour, metallic-roughness and normal textures, each scaled down to at most 1024 px (then `changes` says so); `textured` is `false` when Blender was missing or failed and the GLB carries the materials' base colours only.
`collision` is `{method, parts, cavity_mm}`: `hull` is one convex hull per collision mesh, `coacd` a convex decomposition by CoACD into `parts`.
MuJoCo collides every mesh as its convex hull, and one hull is a lid over a pan or a bowl: a banana dropped into the pan lies on that lid 30 mm up, while the decomposed pan holds it at its bottom.
`cavity_mm` is the deepest water the object's top surface holds; the default `auto` decomposes an object holding at least 5 mm over at least 10 % of its box and gives everything else hulls.
`role` is `context`, `payload` (what the product grips or carries) or `target` (where a payload goes).
`position_mm` is the centre of the object's bounding box in the scene (millimetres, Z up, the product's frame), `rotation_deg` the rotation about X, then Y, then Z (as for a spec part), and `origin_mm` where the MJCF and GLB origin sits.
`grasp_points_mm` are SimReady's grasp points in the object's own frame.
`license` is always `CC-BY-4.0`, since the backend refuses every other package.
`attribution` is the CC BY 4.0 notice (title, author, source link, license link and the changes), and `changes` lists each change AnyBuild made, as the license asks; show the attribution wherever the object is shown.
The MJCF file, the STL headers and the GLB's `asset.copyright` carry the same notice.
`source` names the dataset and its pinned revision.
`warnings` lists what the conversion could not keep, such as a decomposition that ran out of time and fell back to hulls; `reason` is Mechanic's line for why the object is in the scene.

`{"type": "object", "id": "kitchenware_pan_a01", "removed": true}` takes it out of the scene again.
Objects stay on the bench until a reset, and the client keeps the latest event per `id`.

### sim

`run` is `1` for the heavy pack and `2` after the swap in the mock story.
`result` is `pass` or `fail`.
`summary` is one English sentence.
`trajectory` is `[[t, x, y, z], ...]` in seconds and meters.
The test climbs to 0.5 m; from 1.6 s to 1.9 s a downdraft of 35 % of the weight pushes on it.
It passes when the drone never drops below 0.2 m after the gust and holds 0.35 m or more over the last half second.

`kind` is `grip` for the gripper test (absent for the drone).
Then `trajectory` z is how far the object has risen, `hand` is `[[t, z], ...]` for the hand, and the event also carries `object_width_mm`, `payload_g`, `force_n` (per finger) and `slip_mm`.
The fingers are hinges on the template's gear axes, coupled like the gears, and the servo's holding torque closes them on a cube as wide as `object_width_mm`, so the pad tips touch it at half its height, or higher on a cube taller than the pads are long.
The hand lifts 15 cm from 0.4 s to 1.4 s, holds, and shakes ±1.5 cm at 2.5 Hz from 2.0 s to 2.8 s; from 3.2 s to 3.5 s a pull of the object's weight once more builds up and holds until 4.0 s.
It passes when the object never lags the hand by more than 10 mm, so it has to hold twice its weight.

`kind` is `rigid` for the MuJoCo test of a whole assembled product (`simulate_assembly`).
The assembly is one rigid body: the convex hull of all its bodies collides with the floor, its mass and centre of mass come from the CAD masses, the picked parts and the external loads.
`mode` is `push` or `drop`.
`poses` is `[[t, x, y, z, qw, qx, qy, qz], ...]` every 0.02 s for the body frame (metres, z up), `tilt` is `[[t, degrees], ...]`, and `trajectory` holds the same positions as `[t, x, y, z]`.
`glb_url` is the assembly model; the body frame is the assembly frame shifted down by `floor_mm`, so the model is drawn at `z - floor_mm`.
`bbox_mm` and `size_mm` describe the assembly.
A push carries `force_n`, `push_point_mm` (body frame, mm), `push_dir` (plan view unit vector), `push_window_s` (`[0.5, 0.8]`) and `limit_deg`; it passes when the final tilt stays within `limit_deg`.
A drop falls from `drop_height_mm` with a 5° tilt and reports the peak load in g in `summary`.

### mission

One mission test of the drone (`simulate_mission`), flown in MuJoCo with the chosen parts: `run` (counts up per mission flown), `mission` (`speed_run`, `turn`, `hold` or `chase`), `label`, `result` (`pass` or `fail` against the requirement), `summary` (one sentence with the number and the limit), `why` (what limits this build in this mission, the direction for a fix), `requirement_id`, `limit`, `limit_kind` (`min` or `max`), `unit`, `value` (the judged number, `null` when there is none, such as no fly caught), `metrics` (every number of the run), `mass_g` and `parts` (the motor, propeller, battery, flight controller and frame ids it flew).
`poses` is `[[t, x, y, z, qw, qx, qy, qz], ...]` every 0.02 s (metres, z up, the nose on +y) and `series` is `[[t, value], ...]` of the mission's own curve: speed in m/s, course in degrees, drift in cm, or distance to the fly in cm.
`speed_run`: full throttle along +x from a hover at 1.5 m, height held; `top_speed_kmh` and `time_to_top_s` (to 95 % of it).
`turn`: at 8 m/s (29 km/h) along +x, a 90° course change at 1 s; `turn_rate_dps` is 90° over the time to 85.5°, plus `overshoot_pct` and `peak_body_rate_dps`.
`hold`: hold a point at 1.5 m in a 3 m/s side wind gusting by up to 3 m/s with a cross gust, and a 2 m/s downdraft at 2.5 s; `hold_error_cm` is the worst drift, `rms_error_cm` the mean; `wind` is `[[t, wx, wy, wz], ...]` of the air.
`chase`: five flies at 9 km/h, each darting 45° to 120° off course every 0.5 to 0.9 s in a 12 × 12 × 3 m room; a fly is caught within 12 cm. `capture_s` is the median capture time (a missed fly counts as never), `captured` of `flies`, `capture_times_s` per fly, `miss_distance_cm` the closest miss; the drone sees the flies only through its camera: `detect_range_m` (where a 6 mm fly still covers 2 pixels), `sensing_delay_ms`, `first_fix_s` (median), `reacquire_s` (mean time per fly spent finding a lost fly) and `tracks_lost`; `target` is `[[t, x, y, z], ...]` of the fly closest to the median, and `poses` that chase.
Every mission's `metrics` carry `pack_v_start`, `pack_v_min` and `pack_used_mah`; the hold adds `ground_effect_pct`.
The model behind it is in `agent/src/pai_agent/mission_sim.py` and `agent/src/pai_agent/plant.py`: mass and inertia from every part at its place, thrust from the motors' load tables along measured propeller curves on a sagging, draining pack, ground effect, motor lag from the propeller size, body and rotor drag, and the camera's view for the chase; `docs/validation.md` compares it with real drones. The client shows the newest run of each mission in the Simulation tab's Missions pane, and one chat card per `simulate_mission` call.
`controller` is `reference` (simulate_mission: the reference controller, the same for every build, the hardware check) or `trained` (train_controller flies the missions again with the trained gains).
`reference` is `null`, or on a `trained` run the reference controller's `{value, result, summary}` on the same build, so the card shows both; the trained run is the one its requirement row judges.
`estimated_inputs` (only when there are any) lists the estimated part numbers the result rests on, as in `metrics`, and on a chase `"camera defaults: ..."` for camera fields the chosen camera did not carry.

### geometry

The drone's parts at their real sizes (`agent/src/pai_agent/drone_geometry.py`), sent after any tool call that changed a part or the frame: `arm_length_mm`, `thickness_mm`, `motor` (`id`, `bell_diameter_mm`, `height_mm`, `stator_diameter_mm`, `stator_height_mm` from the motor code, `shaft_mm`, `size`), `propeller` (`id`, `diameter_mm`, `pitch_in`, `blades`, `z_mm`), `battery` (`id`, `size_mm` length, width, height), `flight_controller` (`id`, `mount_mm`, `board_mm`), `prop_clearance_mm`, `total_mass_g` (the same mass `physics_calc` and the mission simulator weigh) and `assumed` (fields a part did not carry, filled from the reference build).
The CAD builds its motors, propellers, pack and board from the same numbers; the client scales a part chosen after the last CAD build from the size baked into the model (the `drone` node's `extras`) to this one.

### cad

`source` is `freecad` or `cadquery`.
`tree` is `[{id, label, children}]`.
A FreeCAD drone build has the tree `Drone` with `Printed parts` (`X-frame`, `Canopy with antenna tube`, `Battery holder`), then the motors, propellers, flight controller stack, FPV camera, battery and strap, and receiver antenna, each labelled with the chosen part's name.
Its GLB is the whole drone, Y-up in metres with the nose at -Z, one node per part target below plus `canopy`, `camera`, `battery_strap`, and `antenna`; each propeller node is a child of its motor and spins about its own origin, and the `battery` node's extras carry `size_mm`.
Its materials are named `pai:#rrggbb {look}`, the CAD-tab colour then the look (`carbon`, `prop`, `bell`, ...).
A CadQuery fallback has the tree `Frame` with `Hub`, `Arms`, and `Motor pads` and a frame-only GLB.
`params` maps each name to `{value, min, max, unit}`:
`arm_length_mm` 20-80 mm, `thickness_mm` 1.2-6 mm, `motor_spacing_mm` 4-16 mm.
`glb_url`, `stl_url`, and `step_url` are `/files/{session}/{file}` paths.
`view_png_url` is `/files/{session}/view.png` when the frame was built in the open FreeCAD window (freecad-mcp on `127.0.0.1:9875`), otherwise `null`.
While the window builds, `tool` events for `cad_frame` stay `running` and carry the step in `detail`, such as `FreeCAD: Arm 2 of 4`.
The motor, propeller, battery, flight controller and camera nodes show the chosen part's own 3D model when it has one (`agent/data/models/manifest.json`, or one built for a part found on the web), in place of the simple solid.
`part_models` lists those nodes as `{node, part_id, part_name, model_kind, model_missing, model_source}`, and each such node's extras carry the same fields; `model_kind` is `official` (the maker's or a library's model, under its license), `look-alike` (built from the part's measured numbers) or `approximate` (`model_missing` names the numbers no real source gave, drawn in proportion).

A part from `cad_part` adds `script_url` (`/files/{session}/part-{name}.py`, the FreeCAD script that built it) and `part`, `{name, material, mass_g, bbox_mm, attempts, generated}`.
`bbox_mm` is `[xmin, ymin, zmin, xmax, ymax, zmax]`, `attempts` counts script runs including failed ones, `generated` is `true` when Claude wrote the script and `false` for a library template.
Its tree is the part with one child per body, `(bought)` marking reference parts such as the servo.
Its GLB has one node per body; a material named `pai:#rrggbb` carries that body's color.
Generated parts are Z-up, like FreeCAD.
A `pai:#rrggbbaa` material is see-through with that alpha, used for external loads such as the phone a stand holds.

A whole product built from a spec sends `assembly: true`.
Its tree is the product with one node per assembly and one per part (`(bought)` and `(load)` mark bought parts and loads, each label ends in its mass and material or its catalog name).
Its `params` are every printed part's sliders as `{part_id}.{param}`, each with a `label` such as `Base plate · depth`.
`bodies` has one row per GLB node, `{name, part_id, part_name, kind, group, mass_g}`, where `name` is the node name, `group` the spec assembly id or `null`, and `mass_g` the body's mass (the explode view groups and labels the parts with it).
`glb_url` and `stl_url` are `assembly.glb` (all bodies; bought parts as their own 3D models fitted to their size and position when they have one, listed in `part_models` as for a drone, else as blocks; loads as blocks) and `assembly.stl` (printed bodies), `step_url` is `null` (each part has its own STEP), `script_url` is `assembly-scripts.py` with every part's script, and `part` sums the printed parts.

### render

`source` is `blender`.
`png_url` is `/files/{session}/studio-v{n}.png` after a headless render, one file per version, or `/files/fallback/render.png` when Blender is missing.
`label` is a short English caption.
The tool pill stays `offline` when the recorded still is served.

### draw

`kind` is `halo`, `arrow`, `circle`, or `note`.
`target` is a scene name from the list below.
`text` is the overlay label.

### bom

`items` is a list of `{name, qty, unit_price_eur, weight_g, shop, url}`, for a product built from a spec also `price_source` (`sample` for a catalog price, `estimated`, or `live` from a price provider) and `category` (the spec part id).
Printed parts are priced at filament cost, and their `url` is the part's STL.
`weight_g` is the mass of one piece, not the line.
`url` may be an empty string for the printed frame.
`total_eur` is the sum of `unit_price_eur * qty`.
`prices` is `catalog`, `searching`, or `live`.
With `ANTHROPIC_API_KEY` set, or on the local Claude subscription (one Claude Code web search for all lines), `bom_build` first sends the catalog list with `prices: "searching"`, then a second `bom` with the live lines; the second replaces the first.
Without the key every line stays on the catalog and `prices` is `catalog`.
`prices` is `live` when at least one line has a live price, else `catalog`.
Each item also has `price_source` (`live`, or `catalog` for the drone and gripper; a spec product keeps `sample` or `estimated` when no live price is found), `currency`, and `availability` (`in_stock`, `out_of_stock`, or `unknown`).
A `live` item's `unit_price_eur`, `shop`, and `url` come from a web search (Claude with the server-side web search tool, EU shops first); it adds `price` and `currency` as the shop shows them, `pack_qty` when the shop sells a multipack, `catalog_price_eur`, and `checked_at` (ISO time).
A line falls back to the catalog when the search fails, finds nothing, or returns a price more than four times off the catalog sample; printed parts (shop `printed`, or a `url` that is not an http link) are never searched.
Live results are cached in memory for 15 minutes (failed searches for one minute), so a rebuild only searches the changed parts, and later `metrics` keep using the cached live prices in `price_eur`.
Older recordings have no `prices` or `price_source`; read them as `catalog`.
`stl_path` is the STL path relative to the repository root, or an empty string before CAD.
With the user's 3D printer set, printed lines are named `{part}, printed on your {printer} in {material}` with `price_source` `printer`: `bom_build` prices them from the part's mass at that filament's price per kg, and `print_prep` replaces that with the grams it plans to print (supports included) and adds the grams to the name.
The drone's frame is then printed instead of bought: its line (`category` `frame`, shop `printed`) costs its filament, and `physics_calc` uses that price and the printed frame's mass.
After `print_prep` the list ends with one filament line (`category: "filament"`, shop `printed`, `weight_g` 0, `unit_price_eur` 0) naming the material and grams of the print plan; it never changes `total_eur`, because printed parts already carry their filament cost and the drone's printed frame is an optional test print next to the bought carbon frame.

### mascot

`state` is `ruhig`, `denkt`, `erklaert`, `freut_sich`, or `besorgt`.
`say` is the short line in the speech bubble.

### version

A finished build.
`n`, `weight_g`, `thrust_to_weight`, `flight_time_min`, `price_eur` (the same numbers as the last `metrics`), and `sim` (`pass`, `fail`, or `null`).
`parts` maps each category to the part name.
`diff` lists what changed against the previous version: `{key, label, before, after, unit}`.
Number rows have a `unit`; part rows have `key` `part:{category}`, names in `before` and `after`, and an empty `unit`.
`summary` is one line such as `48.4 g · 10.4 min · 117.60 €`.
Every rebuild is a version: every product, the drone included, commits one after its `bom_build`.
Each version is published once, with the fields below.
`trigger` is `chat`, `library`, `check_failed` (a chat rebuild that makes a requirement pass that the last version failed) or `restore`.
`product` is `drone`, `gripper` or `generic`; `label` names the trigger in one line (the chat request, the library item, `Restored v1`).
For a non-drone product `weight_g` and `price_eur` are set, `thrust_to_weight` and `flight_time_min` are `null`, and `cards` are its metric cards as the last `metrics` event had them.
`requirements` is `[{id, text, met, detail}]` at commit time, `params` the CAD parameters (`arm_length_mm` for the drone frame, `{part_id}.{param}` for a product), and `nodes` maps a product's part ids to the body names in its GLB.
`files` is `{glb_url, render_url}`: a copy of the model made for this version (`/files/{session}/v{n}-frame.glb`, `v{n}-assembly.glb`, `v{n}-part-….glb`) and its studio render; either is `null` when there was none.
`restored_from` is the version a restore rebuilt, else `null`; `at` is the local commit time.
The diff also covers changed CAD parameters (key `param:{name}`) and requirements that flipped (key `req:{id}`, `before` and `after` are `pass` or `fail`).

### part

A part was chosen.
`category`, `id`, `name`, `mass_g`, `size_mm` (`[length, width, height]` when the part has all three, else `null`), and `diameter_mm` (propellers, motors).
`provenance` is `curated` (the parts library with specs from product pages: `agent/data/parts.json`, `agent/data/catalogs/makers.json`), `web` (found during a build on the web or at a distributor, its specs validated, kept in the learned library), `catalog` (an older sample catalog part) or `estimate` (no part fits, mass and price estimated); `source_url` is the page its specs come from.
`confidence` says how its numbers are known: `sourced` (stated on its pages), `derived` (some read off a dimensioned drawing or computed from stated numbers), `estimated` (some are estimates: only in exploration mode, `PAI_ALLOW_ESTIMATED` or Settings, and never a critical field) or `catalog` (a sample catalog part); `estimated` lists those fields.
A web part adds `fields` (`{field: {confidence, source, basis}}`: the page each number came from, or the basis of an estimate) and `sources` (`[{url, kind, distributor}]`: the shop listing, maker page, datasheet and distributor listings, all naming the same part number).
`why` is the requirement quote behind the choice, `{text, speaker, time}`, or `null`.
`reason` is the agent's own reason in one line.

### question

Mechanic asks before deciding for the user, for example when a requirement cannot be met.
`id`, `text`, `options` (`[{id, label}]`), `default_id`, and `timeout_s`.
`status` is `open`, then `answered` with `answer_id`.
Without an answer the default applies after `timeout_s` (`PAI_ASK_TIMEOUT_S`, default 20).

### agent

The orchestrator and the sub-agents it delegates to, one card per agent, sent again whenever it reports.
`id` is stable for one agent run, `role` is `orchestrator`, `cad` (writes one part's FreeCAD script), `parts`, `checks`, `pricing` or `optimizer` (one design optimizer variant, "Variant agent A"), `label` its name ("Orchestrator", "CAD agent", "Parts agent", "Analysis agent", "Pricing agent").
`model` and `model_label` (`claude-sonnet-5-5`, "Sonnet 5.5"), `effort`, `task` (the job in one line), `status` (`queued`, `running`, `done` or `error`), `rounds` (model calls so far), `input_tokens`, `output_tokens`, `cache_read_tokens`, `cost_usd` (from the published per-token prices), `billing` (`api`, or `subscription` when it ran on the local Claude Code login: then `cost_usd` is 0 and the dashboard shows "subscription") and `summary` (what it does now, or its report when done).
`queued` comes before `running` when a job waits for another job of the same fan-out to finish first.
`sent_at` is the server time of this report in epoch seconds, so a replayed backlog keeps its real timing.
`parent` is the `id` of the orchestrator run that delegated the job, `null` for the orchestrator itself and for a sub-agent started outside a run.
`started_at` and `ended_at` are server times in epoch seconds: `started_at` is `null` while queued, `ended_at` is `null` until `done` or `error`.
`tool` is the tool it runs right now (`freecad`, `cad_part`, `part_pick`, `bom_build`, `simulate_assembly`, `delegate`, …), or `null`.
`calls` are its tool calls so far, newest last and at most 30, each `{tool, ok, detail}`.
The web draws these events as a live graph in the Agents canvas tab (`?tab=agents`, `data-target="tab:agents"`); a click on a node opens its log.
The mock path sends them too: a scripted team of sub-agents on the sub-agent model runs beside the real mock tools, with fixed token counts priced like a live run.

### optimize

The design optimizer explored variants of the built drone. Sent with `status` `running` (no variants yet), `done`, and once more when a variant is built.
`id` (`opt1`, `opt2`, ...), `goals` (any of `lighter`, `cheaper`, `longer_runtime`, `stronger`), `keep` (limits to hold, keys `min_flight_time_min`, `max_weight_g`, `max_price_eur`, `min_thrust_to_weight`, `min_arm_stiffness`), `axes` (`x`, `y` and `color`, each a variant number key; the chart plots `y` against `x` and colours by `color`).
`baseline` is the current build through the same checks plus `label` (`v2`), or `null` while running. `recommended` is the Pareto variant best on the first goal, or `null`.
Each of `variants` has `id` (a letter), `label`, `reason`, `agent` (the variant agent that proposed it), `battery`, `battery_id`, `params` (`arm_length_mm`, `thickness_mm`), `frame_g` (the CadQuery frame model's mass), `weight_g`, `thrust_to_weight`, `flight_time_min`, `price_eur` (physics_calc's numbers), `arm_stiffness` (relative to now: thickness cubed over arm length cubed), `warnings`, `checks` (`id`, `label`, `pass`, `detail`: the MuJoCo gust test, the prop clearance, one per `keep` limit), `feasible` (every check passes) and `pareto` (feasible and no feasible variant is at least as good on every goal and both chart axes and better on one).
`applied` is the letter built as a version and `version` its number, else `null`.

### build_guide

The step-by-step build guide for the current bill of materials, published whole after `bom_build`.
`version` is the version the guide belongs to, `total_minutes` the sum of the steps.
`steps` is a list of `{n, title, instructions, parts, tools, minutes, items}`, numbered from 1.
`parts` are scene part names from the list below; the web explodes the model and highlights them for that step.
`items` are the bill-of-materials names of those parts, plus the parts of categories without a scene part of their own (camera, canopy, hardware) that the step names, filled in by the backend.
Together the steps cover every scene part.

### print

The print plan for every printed part, published whole by `print_prep` after `bom_build`.
`source` is `slicer` when every part was sliced by PrusaSlicer or OrcaSlicer (`slicer` names it), else `estimate`: the numbers come from the mesh (shell plus 20 % infill at the default profile, an average flow and a per-layer overhead) and no part has G-code.
`profile` is `{printer, nozzle_mm, layer_height_mm, infill_pct, walls, bed_mm}`.
`parts` is a list of `{id, name, material, qty, orientation, size_mm, volume_cm3, time_min, filament_g, filament_m, cost_eur, warnings, stl_url, gcode_url, source}` for one piece each; `size_mm` is `[x, y, z]` as oriented on the bed, `orientation` is `flat`, `upright` or `as_modeled`.
`gcode_url` is a `/files/...` download when a slicer produced it, else an empty string; a part whose slice failed keeps the estimate and adds `slicer_error`.
`warnings` is a list of `{kind, text}` with `kind` `overhang` (faces past 45 degrees that are not on the bed), `thin_wall` (a designed thickness or the thinnest extent under 0.8 mm) or `bed_size` (over a 220 × 220 × 250 mm build volume).
`totals` is `{parts, time_min, filament_g, cost_eur, warnings}` over every piece (`qty` counted).
The drone prints its CAD frame as a PETG-CF test print; a spec product prints its printed parts, the gripper its body.

With the user's 3D printer set, `printer` names it (else `null`) and the plan follows it: `profile` is that printer's bed, nozzle and `enclosure` with the maker's `source_url`, the estimate uses its typical flow, the slicer gets its bed and the filament's temperatures, and the default `orientation` is `auto`: per part, the pose (`flat`, `as_modeled`, `upright`) that fits the bed and needs the least support, reported as the pose it chose.
Each part then adds `supports` (overhangs need support in that pose) and `support_g`, `totals` adds `support_g`, `bed_size` checks that printer's bed, and `warnings` may add `material` (the printer cannot print it, for example ABS without an enclosure, or it is not among the user's filaments) and `warp` (`Medium` or `High` warping risk from the material's shrink, an open or enclosed printer and the part's length on the bed).
The drone frame is printed in the material `material_pick` chose for it.

### fem

FEM of one printed part on its real shape, from `fem_check`: gmsh meshes its STEP into quadratic tetrahedra and CalculiX solves each load case (both ship with FreeCAD).
`part_id` and `part_name` name the part (`frame` for the drone), `material` its filament, `fill` the plastic share of the section (perimeters solid, the core at `infill_pct` with `walls` perimeters) that scales the data sheet `modulus_mpa`, `strength_mpa` (layer plane) and `z_strength_mpa` (across the layers).
`cases` is a list of `{name, force_n, max_von_mises_mpa, max_across_layers_mpa, max_deflection_mm, safety, safety_in_plane, safety_across_layers, governs, hot_spot_mm}`; `safety` is the smaller of the layer-plane strength over the von Mises stress and the interlayer strength over the tension along the print direction, with the clamped and loaded nodes themselves left out of the maxima.
`governing` is the case with the lowest safety, `safety`, `max_von_mises_mpa` and `hot_spot_mm` are its numbers, `max_deflection_mm` the largest over all cases, `limit` the strength requirement (2x unless the user set one) and `result` `pass` or `fail` against it.
`loads` says in one line each where the part is held and what loads it; `glb_url` is the stress-coloured surface of the governing case (vertex colours from blue at 0 to red at `scale_mpa`, the printed strength), `nodes`, `elements` and `solver` describe the mesh, `printer` is the user's printer or `null`.
The dashboard shows it in the Simulation tab's Stress pane.

### point

`target` is a scene name.
`label` is the pointer caption.
The pointer flies to that exact name.
It does not guess from a screenshot.

### ui

Mechanic operates a dashboard control: `{id, control, say}` plus, depending on the control, `open` (panels, `true` opens and `false` closes), `value` (`explode` 0 to 100, `setting:*` true or false), `part` (`focus`) and `versions` (`panel:compare`, two version numbers).
The dashboard flies the pointer to the element with that `data-control`, presses it with `say` in the bubble, then acts; a control behind another one (a setting inside the settings panel, the build guide inside the bill of materials, a tab while the library is open) is pressed open on the way.
`run:test` and `run:rebuild` only show the button; the backend runs them right after.
With HeyClicky off (the pointer button in the chat composer, on by default) the action happens without the pointer, and `point` events are not shown either.
Only fresh events act; a replayed backlog changes nothing.

### training

`status` is `queued`, `running`, `done`, `failed`, or `offline`.
`step` and `reward` are the latest curve point, or `0` when there is none.
`curve` is `[[step, reward], ...]`.
`video_url` is a backend path such as `/files/fallback/hover.mp4`, or `null` when there is no clip.
A `done` event after an `offline` tool means the fallback file was played, not that a pod finished a job.
The browser training's `done` event carries `gains` (see the browser run below); the firmware reads its `roll` and `pitch` `{p, i}` as browser-tuned gains.

Training on the missions (`train_controller`, `agent/src/pai_agent/mission_train.py`) adds `source: "backend"`: MuJoCo in Python on the backend, the missions' own model, so no dashboard is needed.
It has the browser run's fields (`job_id` starting `mt`, `product: "drone"`, `population`, `generations`, `rollouts_total`, `generation`, `best_params`, `best_metrics`, and `gains` on `done`, in the same format) plus `missions`, the missions it trains on.
`best_params` are the exported gains here (attitude in N m/rad), and `best_metrics` on `done` holds each term's number: `hover_rms_error_cm` and the missions' own keys (`top_speed_kmh`, `turn_rate_dps`, `hold_error_cm`, `capture_s`).
`reward` is the training score, 0–100: each term's requirement ratio capped at 1.5, averaged. There is no `queued`: `running` follows every generation, then `done` or `failed`.
The chat shows one card per run; it does not touch the Isaac Lab panel.

### firmware

The firmware and wiring for the built product, from the `firmware` tool after `bom_build`.
`kind` is `betaflight` (a drone with a flight controller) or `arduino` (a servo product).
`product` is the product name, such as `drone`.
`filename` is the file name, such as `anybuild-drone-v1-betaflight.txt` or `anybuild_gripper_v1.ino`; `url` is its `/files/{session}/{filename}` path.
`content` is the whole file, so a client can offer the download without the backend.
The file is a fixed template filled from the chosen parts; only `explanation`, one or two sentences, may come from Claude.
`gains` is `{roll, pitch, yaw}`, each `{p, i, d, f}` in Betaflight units, or `null` for an Arduino sketch.
`gains_source` says where they came from, first match wins: `validated`, `isaac`, `browser`, `defaults`, or `none` (an Arduino sketch).
`validated` is the gain set train_controller validated on this build (every mission and the stress test passed with it), written exactly as validated; it stays this build's until a part or the arm changes or the mass moves by more than 5 %.
The file then names what it was validated on and the seven cascaded gains; any other source is marked as not validated in the mission tests. `gains_validated` is `true` with `validated`.
`isaac` is the `gains` field of the last live Isaac Lab training (`omniverse` with `mode: "train"`, `source: "live"`, `status: "done"`); no Isaac job emits it yet, so this source stays inactive until one does.
`browser` is the `gains` field of the last `done` browser `training` event (`source: "browser"`).
`defaults` are the Betaflight 4.4 starting values for a 1S whoop. With `isaac` or `browser`, missing terms keep the defaults.
When a training run finishes after the firmware was made and changes the gains, a new `firmware` event follows with the new source.
The dashboard shows the source next to Download firmware: Isaac Lab gains, Browser-tuned gains, or Default gains.
`wiring` is a list of `{component, connects_to, pin, wire, note}`, one row per connection of a chosen part.

### electronics

The wiring diagram and power budget of the built product, from the `electronics_plan` tool after `bom_build` (the drone story after `firmware`, every library build after its bill of materials).
`product` is the product, such as `drone` or `product`.
`ok` is `false` when any part is over its rating; `summary` is one line with parts, wires, peak current against the supply limit, headroom, average power and the runtime.
`blocks` is a list of `{id, name, role, col, row, voltage_v, rating, qty}`: `role` is `supply`, `connector`, `switch`, `regulator`, `controller`, `driver`, `inline` (an LED resistor), `load` or `sensor`; `col` and `row` place it on the diagram, the power flowing from column 0 to the right; `rating` is a short text such as `1S max (4.35 V), ESC 12 A per motor`.
`wires` is a list of `{id, from, to, from_pin, to_pin, kind, voltage_v, current_a, color, label}`: `from` and `to` are block ids, `kind` is `power`, `phase` (motor phase wires from an ESC) or `signal`; `voltage_v` and `current_a` (the peak) are `null` on signal wires.
`color` groups wires by voltage for the diagram: `3v3`, `1s` (3.6 to 4.4 V), `5v`, `high` (above 5.5 V), `phase`, `signal` or `power`. Grounds are common and not listed.
`budget` is `analysis_more.power_budget` for the supply: `{supply, supply_voltage_v, supply_limit_a, average_a, peak_a, average_w, peak_w, headroom, rails, loads, runtime_h?}`; each load is `{name, voltage_v, power_w, duty, peak_w, average_w, current_a}`. `runtime_h` is there for a battery only, with 80 % of its energy usable.
Duty cycles come from the build's stored `check_runtime` or `check_power` arguments; a controller with `sleep_power_w` adds an `asleep` row for the rest of the time. The drone's motors draw their hover power (the physics_calc model: full-throttle power times the hover share of thrust to the 1.5; physics_calc itself reads the motor's load table where the library has one) on average and their full-throttle power at the peak.
`warnings` is a list of `{part, text, severity}`, `severity` `fail` (over a rating: more cells than the controller or motor takes, a part above its voltage, a bare LED on a higher rail, a resistor above its watts, a motor or pump on a controller pin, a driver, regulator or supply above its current) or `warn` (a part well under its voltage).
`gaps` lists the ratings the catalog does not have and the default the plan used instead, such as `Regulator output limit assumed 1.0 A`.
`wiring` is the drone's `firmware` wiring table (same rows), else empty.
The dashboard draws it as an SVG in the bill-of-materials drawer under Firmware and wiring, with the budget table and the warnings.

### circuit

The circuit of the chosen parts as SparkBench designs it, from the `circuit_design` tool after `electronics_plan` (`agent/src/pai_agent/tools/circuit.py`).
SparkBench ([github.com/dennisonbertram/sparkbench](https://github.com/dennisonbertram/sparkbench), pinned in `agent/src/pai_agent/sparkbench.py`) runs headless in its own Node process through `agent/sparkbench/bridge.ts`, with no network and no key.
The tool takes `board` (`esp32` or `pico`), only when the parts have no controller; the board is then proposed by Mechanic.
Without SparkBench installed (`agent/scripts/setup_sparkbench.sh`), without Node.js, or with a controller SparkBench does not simulate (a flight controller, an Arduino, a Raspberry Pi, an ESP32-S3 or a camera board), the tool answers `ok: false` with the reason, emits nothing, and the run goes on.
`{"type": "circuit", "version": 1, "product": "gripper", "name": "Robot gripper", "board": "esp32", "board_name": "ESP32 DevKit V1", "board_proposed": false, "ok": true, "summary": "ESP32 DevKit V1 with 1 part and 4 wires: ...", "parts": [...], "nets": [...], "wires": [...], "files": {...}, "checks": [...], "tests": [...], "sim": {...}, "bom_total_usd": 23.5, "notes": [...], "gaps": [...], "source": "sparkbench@6dd9237"}`
`version` is the bench version the circuit belongs to, as in the file names (`circuit-v1-...`).
`board` is `esp32` (SparkBench's ESP32 DevKit V1) or `pico` (Raspberry Pi Pico); `board_proposed` is `true` when no controller was among the parts and Mechanic named the board.
`ok` is `true` when no check is an `error`, every test passes and the simulation ran without an error; `summary` says the same in one line.
`parts` is a list of `{ref, type, label, mpn, anybuild, pins}`: `ref` is the reference designator (`U1`), `type` SparkBench's part type (`esp32-devkit`, `custom-pca9685` for a library part), `label` the AnyBuild part's name, `anybuild` the id of the AnyBuild part it stands for (the spec part id, or the category for the drone and the gripper); a part SparkBench adds for one (an LED's resistor) carries that part's id, and what it adds on its own (a separate supply, a pull-up) and a proposed board carry `null`.
`pins` maps each pin name to its net name, `null` for a pin that goes nowhere; the board lists only its connected pins.
`nets` is a list of `{name, pins}` for the nets that join two parts or more, each pin as `REF.PIN` (a pin name may contain a dot, as in `U1.GND.1`).
`wires` is a list of `{from, to, color}`, the ends as `REF.PIN`, the colour SparkBench draws the wire in.
`files` are `/files/{session}/{name}` paths: `schematic_svg`, `breadboard_svg`, `kicad_sch`, `kicad_zip` (the KiCad project with its footprint library), `netlist` (KiCad `.net`), `spice` (`.cir`), `bom_csv`, `firmware_main` (`main.py`), `firmware_zip` (`main.py` and the driver files under their own names), `build_md` (the breadboard build guide), `simulation_log` and `sparkbench_project` (the project JSON SparkBench opens).
The files are served as downloads; a view fetches an SVG as text to show it.
`checks` is SparkBench's design check list, `{id, severity, title, detail}` with `severity` `error`, `warning` or `info`, errors first.
`tests` is a list of `{id, name, pass, detail}`: the acceptance tests SparkBench derives from the firmware it wrote (it starts, it says so, a button toggles its LED), each run in its simulator from power-on.
`sim` is the 5 s run of the firmware, every button held from 2.5 s to 3.5 s: `{status, simulated_s, error, warnings, serial_tail, outputs}`; `status` is `stopped` when the 5 s ran out, `finished` when the program ended and `error` when it crashed, with `error` the message; `warnings` are the simulator's `{severity, text}` findings while it ran (a pin above 3.3 V, a reading out of range); `outputs` is `{t_s, text}` at nine moments (LEDs, servo angles, pixels, driver channels); `serial_tail` the last lines on the serial console.
`bom_total_usd` is what SparkBench's parts list (`bom_csv`) adds up to in US dollars, from its own sample prices, the breadboard and jumper wires included; the AnyBuild bill of materials stays the one to order from.
`notes` are SparkBench's pin choices and wiring notes, each library part's notes behind its name, plus how the board gets power and whether Mechanic proposed it.
`gaps` lists, one sentence each, what differs from the real build: a part SparkBench has no model for (a motor, a power LED, a lidar), a supply, battery, resistor or power switch it leaves to USB power, a part not picked yet, and a servo behind a PCA9685 with the channel it plugs into, because SparkBench's PCA9685 has no channel pins.
Parts SparkBench builds in become its feature kinds, which its planner wires and writes the firmware for; any other part is found by its part number in SparkBench's checked parts library and gets its driver file but no code in `main.py`.
`source` is `sparkbench@` and the commit the checkout is at.
An identical request (the same parts, board and date) reuses the last result from `agent/runs/cache/circuits`, and the tool event then carries `cached: true`.

### safety

The safety and regulations check before anyone orders parts, from the `safety_check` tool (the mock stories call it right before `bom_build`).
`{"type": "safety", "product": "drone", "label": "the drone", "findings": [...], "summary": "2 safety note(s) for the drone: 1 warning, 1 info", "disclaimer": "Hints from a fixed rule set and the agent, not legal advice. ..."}`
`findings` are sorted `danger`, then `warning`, then `info`; each is `{id, severity, title, reason, rule, fix, source}`.
`rule` names the rule or source the finding rests on (for example `Delegated Regulation (EU) 2019/945` for the drone class, `EU Low Voltage Directive 2014/35/EU` for mains); `fix` is a change the agent can apply; `source` is `rule` (the fixed rule set in `agent/src/pai_agent/tools/safety.py`) or `claude` (Claude's own findings passed in the tool's `findings` argument).
The rule set covers the EU drone class by take-off mass (C0 under 250 g with registration and remote ID hints, C1, C2), lithium battery shipping (Wh, UN3480/UN3481, IATA PI 965 to 967), mains voltage, pinch points on grippers and mechanisms, tip-over for tall products, heat in closed enclosures, small parts for children and coin cells.
The chat shows one compact card per event, findings collapsed to a line each, the top one open; Mechanic says the top finding as a hint.

### stress

The stress test runs the current product in 50 randomized MuJoCo worlds (`stress_test`).
`product` is `drone` or `gripper`.
`status` is `running` while worlds finish, then `done`, or `failed` when a world raised an error or no browser flew the worlds; a `failed` event keeps the worlds finished so far, `worst` is `null`, and `explanation` names the error.
`run` counts stress tests in the session; `total`, `done`, and `survived` count worlds, so the score reads `Survived {survived}/{total}`.
`seed` is the fixed seed the worlds are drawn from, so every stress test of the same build flies the same worlds.
`weight_g` is the nominal build the worlds vary.
`worlds` lists every finished world; every world has `{i, pass, reason, mass_pct, motor_pct, margin}`.
`mass_pct` is −15…+15 (the drone, or the gripper's payload) and `motor_pct` −25…0 (motors, or the gripper servo).
`margin` is 1 for a perfect run and 0 or less for a lost world; `reason` is an empty string when the world survived.
`worst` is `null` while running; when `done` it is the lost world with the lowest margin (the survived one with the lowest margin when none was lost) plus its `trajectory` (`[[t, x, y, z], ...]`, the same shape as `sim`).
`weakest` names the factor that separates lost worlds from survived ones, or is `null` when every world survived; `explanation` is Mechanic's one sentence about it.

Drone: the worlds fly in the browser, on the MuJoCo WASM workers of the training module, with its drone episode: the controller holds its spot 1 m up for 10 s while a 1-cosine gust hits it.
With `backend` (the train loop's validation) the same worlds fly on the backend on the missions' model instead (`source: "backend"`, no `job_id` or `spec`): 5 s each, the gust as moving air, the plant with the world's mass and motor strength, the controller with the nominal build's and noisy position and velocity readings.
The first event is `queued` with `source: "browser"`, `job_id`, and `spec` (the training spec); the first dashboard tab that sees it claims the job, and every later event carries the same three fields.
No claim within `PAI_TRAIN_CLAIM_TIMEOUT_S`, no report for `PAI_TRAIN_STALL_S`, or no finish within `PAI_TRAIN_TIMEOUT_S` ends it as `failed`.
`policy` is `trained` when the last drone `training` event carries `gains` (or the tool got `gains`), else `default`, and the card says the gains are not trained yet.
`gains` are the controller gains that flew, in the `training` event's units: `kp_z`, `ki_z`, `kd_z`, `kp_xy`, `kd_xy`, `kp_att`, `kd_att`; `thrust_to_weight` is the nominal one.
Drone worlds add `gust_mps` (peak 0…6 m/s), `downdraft_pct` (the share of it blowing down), `gust_dir_deg` (where it blows to, 0 is +x), `gust_start_s` and `gust_len_s` (when it blows), `noise_cm` (sensor noise), `drift_m` (farthest from its spot) and `low_z_m` (lowest height after the gust).
`reason` is `crashed`, `drifted` (more than 0.35 m off its spot after the first second), or `sagged` (more than 0.15 m below its spot in the last half second).
`weakest` is `gust`, `motor`, `mass`, or `noise`.

Gripper: the grip test from `sim` (lift 15 cm, hold, shake at 2.5 Hz), 3.2 s.
`policy` is `design` and `gains` is empty; the event also carries `payload_g`, `object_width_mm`, `force_n` (per finger), and `safety_factor` of the nominal build.
Gripper worlds add `friction_pct` (pad friction −40…+10), `shake_x` (shake amplitude 1–2× the nominal 1.5 cm), `noise_pct` (slow servo jitter on the squeeze force, 0…15) and `slip_mm`.
`reason` is `slipped` (the object lagged the hand by more than 10 mm) or `dropped`.
`worst` also has `hand` (`[[t, z], ...]`, as in `sim`).
`weakest` is `friction`, `motor`, `mass`, `shake`, or `noise`.

A browser run (`train_in_browser`) adds `source: "browser"` and these fields to the same shape:
`job_id`; `product` (`drone` or `gripper`, from the session's product); `spec`, what the browser builds the MJCF from, with `product`, `label`, `nominal` (`true` when nothing was built yet), and `parts: [{category, name, qty, mass_g}]`;
for the drone also `mass_g`, `thrust_g` (total maximum thrust of all motors), `motors`, and `arm_length_mm`; for the gripper `payload_g` and `width_mm` (the object from the brief), `max_force_n` (finger force the servo holds, per pad), and `friction` (pads); `population` (64), `generations` (16), `rollouts_total` (1024), `generation` (finished generations);
`best_params`, the best controller gains so far (drone: `kp_z`, `ki_z`, `kd_z`, `kp_xy`, `kd_xy`, `kp_att`, `kd_att`), or `null`; `best_metrics` (drone: `rms_error_cm` after the first 2 s, `max_tilt_deg`, `survived_s`, `crashed`, `held`; gripper: `slip_mm`, `force_n`, `cycle_s`, `crashed` for a dropped part, `held` for at most 10 mm slip), or `null`; and `error` on `failed`.
The gripper trains its grasp (`squeeze` as a share of `max_force_n`, `ramp_s`, `settle_s`, `lift_s`) in the grip test above: a held grasp scores for less force, a shorter cycle, and less slip.
`step` counts finished rollouts and `reward` is the best score so far, 0–100; `curve` holds one point per generation.
`best_params` are in the trainer's own units (drone: attitude gains divided by the roll inertia, 1/s² and 1/s).
The `done` event also carries `gains`, the trained controller for other modules.
For the drone it is `{kp_z, ki_z, kd_z, kp_xy, kd_xy, kp_att, kd_att, roll: {p, i}, pitch: {p, i}}`:
`kp_z` (1/s²), `ki_z` (1/s³), `kd_z` (1/s), `kp_xy` (1/s²), and `kd_xy` (1/s) shape the commanded acceleration, `kp_att` (N m/rad) and `kd_att` (N m s/rad) are the attitude torque gains, and `roll` and `pitch` are Betaflight 4.4 rate P and I.
Those are the Betaflight defaults (roll 45/80, pitch 47/84) scaled by the trained `kd_att` against 12 1/s and clamped to 0.5–2×, a starting point for the bench rather than a measured tune; yaw, D, and feed-forward are not trained and keep the firmware defaults.
For the gripper `gains` is `{squeeze, grip_force_n, ramp_ms, settle_ms, lift_ms, cycle_ms}`, the grasp to put in the servo sketch.
`queued` asks a dashboard to run it; `running` follows each generation; `done` carries the final gains.
A local run, started with the Training pane's "Train in this browser" button while the backend is offline, never reaches the backend: it has no `job_id`, sends no claim or progress, and publishes no `training` event, so its gains do not feed the stress test or the firmware.
`failed` with `error: "no_browser"` means no dashboard claimed the job within `PAI_TRAIN_CLAIM_TIMEOUT_S` (default 20); a run that does not finish within `PAI_TRAIN_TIMEOUT_S` (default 240) fails with `error: "timeout"`, and a claimed run that reports nothing for `PAI_TRAIN_STALL_S` (default 30) fails with `error: "browser_gone"`, for example after the tab was closed or reloaded.

### trial

An independent test of the built gripper in [Robo Use](https://github.com/benchflow-ai/robouse) (`robouse_trial`): a robotics benchmark whose own MuJoCo scene and episode server judge where the object ends up, not what the policy says.
The bridge package `anybuild-robouse` (its own uv environment, Robo Use 0.6.1 with MuJoCo 3.3.0) loads the gripper exported from its CAD and writes the task from the gripper brief: put a cube of the brief's width and mass in a bowl (`goal: "bowl"`) or on a pad.
`robouse tasks check` runs first: the task counts only when its scripted reference solution (`harness: "oracle"`) scores 1 and the no-op control 0.
`harness: "claude-code"` then lets Claude Code drive the gripper through the `robo` command, only when asked, with `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` set and within a time limit; otherwise the reference solution's trial is the one shown.

`id` names the trial; the events of one trial share it, and the client keeps the latest of each.
`status` is `running`, then `done`; `recorded` when Robo Use did not run now and a trial recorded earlier stands in; `failed` when no trial ran.
`stage` while running is `export` (the gripper to MJCF), `task`, `check` or `agent`; `detail` is one line on the stage, the result or why a recorded trial stands in.
`harness` is the policy of the trial shown (`oracle` or `claude-code`), `requested_harness` the one asked for.
`task_id`, `task_title` (`Put the cube in the bowl`), `version` (the bench version it ran on) and `design` (`servo`, `pads`, `opening_mm`, `object_mass_g`, `object_width_mm`, `goal`, of the hand it ran with) say what was tested.
`verdict` is `pass` (reward 1), `fail` (reward 0), `invalid` (the no-op control scored, so the task tests nothing and the trial is not counted) or `refused` (the task generator cannot pose the brief for this hand, such as a cube wider than the jaw opens; `status` is `failed` and `error` says why).
A gripper too weak for the object fails its own reference solution: `verdict` is `fail` and `validity.valid` is `false`, which is the benchmark finding the flaw, and Claude Code is not run on it.
`reward`, `success`, `outcome` (`done`, `timeout`, ...), `steps_used` and `max_steps` (control steps of 20 ms), `wall_s` (the trial's wall time) and `metrics` (Robo Use's episode metrics, among them `max_contact_force_n`, `safety_events`, `path_length_m` and `execution_time_s`) come from the trial's `result.json`.
`validity` is `{reference, noop, valid, report}`: the two control rewards and `robouse tasks check`'s report, one line each.
`summary` is one sentence for the card and Mechanic, `analysis` what the trace shows: `held` (the object was ever held), `lift_slip_mm` (how far it slid down the fingers while the hand rose), `dropped` (`lift`, `carry` or `lowering`, or `null`), `released` and `distance_mm` (from the target's middle at the end).
`video_url` is the trial's recording copied flat into the session's files (`/files/{session}/{id}.mp4`, 960 x 720); `video_info` is `{fps, duration_s, size}`.
The video runs only while the simulator steps, so every time below is video seconds, mapped from the episode's env steps through the frames it recorded.
`steps` lists the policy's robo requests: `{index, op, action, result, ok, t_start, t_end, env_steps, hand_pos, gripper_open, holding, objects, message}`; `action` is the command line (`robo grip 1 --steps 25`), `result` Robo Use's answer in short, `objects` each object's place after it, and `message` an agent's own words before it (`null` for the reference solution).
`ee_path` is `[[t, x, y, z], ...]` of the hand's tool point and `force` `[[t, newtons], ...]` of the largest contact force, one row per control step; metres, z up, the table top at 0, y away from Robo Use's front camera.
`scene` is `{object: {name, kind, color, size_m, path}, target: {name, kind, pos, floor_z, rim_z, inner_diameter_m, size_m}}` from the episode's states; `object.path` is `[[t, x, y, z], ...]`, its place after every request.
`provenance` is `{robouse, mujoco}` and `ran_at` when the trial started.
A recorded trial adds `recorded: {matches_build, reason}`: `reason` why Robo Use did not run, `matches_build` whether the bench holds the design and brief it was recorded with (`agent/data/robouse/recorded/`, the gripper mock story's MG996R design with the 66 mm, 200 g can).
When it does not, the trial is AnyBuild's example gripper's, never this build's: the card and the pane call its verdict an example, and its `summary` and `design` name that gripper.
The client shows one chat card per trial and the trial in the Simulation tab's Robo Use pane: the verdict, the video with one mark per request on its timeline, the requests, the hand's path on the stage and the contact force, all on the video's clock.

## Scene targets

One catalog motor is instanced four times.
One catalog propeller is instanced four times.
Point at `motor_front_left` or `propeller_front_left` when the line is about the part type.

Parts:

- `frame`
- `motor_front_left`
- `motor_front_right`
- `motor_rear_left`
- `motor_rear_right`
- `propeller_front_left`
- `propeller_front_right`
- `propeller_rear_left`
- `propeller_rear_right`
- `battery`
- `flight_controller`

UI:

- `requirements`
- `metrics`
- `timeline`
- `viewport`
- `chat`

## Dashboard controls

The `control` values of `ui_control` and the `ui` event, each the `data-control` of a real on-screen element:

- `tab:model`, `tab:cad`, `tab:simulation`, `tab:omniverse` (drone only)
- `view:workbench`, `view:library`, `view:training`, `view:logbook`
- `panel:bom`, `panel:guide`, `panel:compare`, `panel:settings`
- `setting:agents`, `setting:tools`, `setting:all_metrics`, `setting:push_to_talk`, `setting:voice`
- `explode`, the slider in the corner of the Model tab
- `focus`, the 3D camera turns to `part` (a scene target, or a spec part's id or name)
- `run:test`, `run:rebuild`
- `library:{id}`, one library item

`agent/src/pai_agent/scene.py` holds the list with a description each; the orchestrator's prompt and the voice model's prompt carry it.
Closing buttons are tagged `{control}:close`, and `look:3d` is the 3D switch of the Model tab.

## Tools

`ask_user`, `parts_search`, `physics_calc`, `simulate_drone`, `simulate_mission`, `stress_test`, `cad_frame`, `cad_part`, `product_brief`, `product_spec`, `sketch_to_spec`, `reference_load`, `delegate`, `part_pick`, `assemble`, `cad_update`, `check_totals`, `check_tip_over`, `check_deflection`, `check_torque`, `check_runtime`, `check_power`, `check_thermal`, `check_rollover`, `simulate_assembly`, `catalog_search`, `grip_calc`, `simulate_grip`, `isaac_lab_train`, `isaac_lab_status`, `isaac_sim_render`, `robouse_trial`, `blender_render`, `bom_build`, `print_prep`, `build_guide`, `firmware`, `electronics_plan`, `circuit_design`, `safety_check`, `scene_object`, `ui_point_at`, `ui_draw`, `ui_control`, `mascot_say`, `train_in_browser`, `train_controller`, `optimize_design`, `optimize_apply`, `material_pick`, `fem_check`.

`material_pick` takes `part_id` (none for the drone frame), `max_temp_c`, `outdoor`, `impact`, `flex` and optionally `material` and `reason`; it chooses among the filaments the user's printer prints (every material without a printer): heat and flex rule a material out (heat deflection temperature at least 5 °C over `max_temp_c`), then outdoor UV and impact toughness rank, then stiffness and strength, then the spool price. It returns `material`, a one-sentence `reason`, `meets_needs`, `rejected` with why, and the data sheet `properties` and `source`; the part's mass follows the density and every check runs again.
`fem_check` takes `part_id` and optionally `cases` (`[{name, region, force_n}]`, newtons in the assembly frame), `fixed` (the held region), `infill_pct` and `walls`; a region is `{face: x_min ... z_max}`, `{near: [x, y, z], radius_mm}` or `{box: [x0, y0, z0, x1, y1, z1]}`. Without cases a spec part is held on its lowest face and loaded by each external load within 40 mm at twice its weight (else a 10 N press on its top); the drone frame is held at the stack, with all four motors at full thrust and a crash on one motor at 10 g. It emits the `fem` event, stores its result as a check (rerun by `cad_update`, by `cad_frame` for the drone and by `material_pick`) and judges the `strength` requirement.

`optimize_design` (drone, after a build) takes `goals`, `keep` and `count` (4 to 8, default 6). With a key, `count` variant agents on the sub-agent model run in parallel (`agent` events with `role` `optimizer`, `label` "Variant agent A" ...), each proposing one battery, arm length and plate thickness; without one, fixed strategies propose them. A proposal that repeats the current build or another variant is replaced by the next strategy. Every variant runs the same checks and the result is the `optimize` event; `optimize_apply` takes `id` and `variant` (default the latest run and its recommendation) and builds it as `POST /api/optimize/apply` does.

`ui_control` takes `control` (see Dashboard controls) and, as the control needs, `open`, `value`, `part`, `versions` and `say` (the bubble, a default otherwise).
It checks the control against the build (no bill of materials yet, fewer than two versions, Omniverse for a non-drone product) and answers an error the model can act on; `run:test` and `run:rebuild` wait for the run and return its result.

### Any product

`delegate` (orchestrator only, with delegation on) hands a bounded job to a sub-agent: `agent` is `parts` (with `part_pick`), `checks` (with `assemble`, the checks and `simulate_assembly`) or `pricing` (with `bom_build` and `part_pick`), and `task` says what to do.
The sub-agent runs its own short loop on the sub-agent model and returns `report`, `tool_calls`, `tokens` and `cost_usd`.
With delegation on, the orchestrator itself does not get `part_pick`, the checks or `simulate_assembly`; several `cad_part` calls in one turn run side by side, each script written by its own CAD agent.

`product_spec` starts a build for any product that is not the drone or the gripper.
The spec has `name`, `function`, `quote` (the request), optional `assemblies`, `requirements` and `parts`; `agent/src/pai_agent/spec.py` validates it and answers every problem at once, so Claude fixes the spec and calls again.
Coordinates are millimetres, Z up, the product stands on Z = 0 centred on X = Y = 0, and -Y is the front.
A part has `id`, `name`, `kind` (`printed`, `bought` or `external`), `qty` and optional `assembly`, `size_mm`, `position_mm` and `rotation_deg` (degrees about X, then Y, then Z).
`position_mm` is the centre of the part's bounding box in the assembly for every kind; a printed part with it is moved there and rotated about its own centre, one without it stays where its script built it.
A printed part needs `material`, a `description` of its shape and where it sits, `size_mm` (the envelope its build is checked against) and `params` (mm, they become sliders).
A bought part has `category` and `query` for the catalog; with `size_mm` and `position_mm` (its centre) it shows as a block and counts for the centre of mass.
An external part is a load that is not ordered, such as the phone on a stand: `mass_g`, `position_mm` and `size_mm`.
A requirement has `text`, `check` and a limit: `mass` (max g, product without loads), `strength` (min x, the FEM safety factor of the printed parts, optional `part_id`), `cost` (max eur), `size` (max mm, largest side), `tip_over` (min deg, or min N pushed at the top), `deflection` (max mm, optional `part_id`), `torque` (min x), `runtime` (min with `unit` `min`, `h` or `days`), `stability` (max deg after the push), `drop` (max g), `power` (min x supply headroom over the peak current), `thermal` (max `deg_c` inside the case), `rollover` (min `g` lateral, or min `deg` side slope) or `printable` (no limit).
At most six printed parts and sixteen parts.
A spec that keeps the name or a part id revises the product on the bench: a printed part with the same description and material keeps its script and is rebuilt from it when its params changed, a part that is still bought keeps its pick, and the result lists `kept`, `rebuilt_with_new_params`, `to_build` and `to_pick`.

`sketch_to_spec` with `sketch` (the file name, the newest when left out) and optional `note` sends the photo to Claude vision on the orchestrator model at medium effort, with one forced tool `propose_spec` whose `spec` is the `product_spec` schema.
`spec.py` validates the answer; its problems go back in the same conversation, up to two retries. A photo without a product answers `ok: false` with what was seen, so Mechanic asks instead of building.
It returns `spec`, `read`, `unreadable`, `summary` and `source` and does not start the build: the orchestrator calls `product_spec` with `spec`.
Without a key the recorded reading of the sample (`agent/data/sketches/phone-stand.json`) answers after 1.5 s, whatever the photo, and the mock builds the phone stand from it.

`cad_part` takes `part_id` for a spec part: the spec gives name, description, material and params, and the script writer also sees the product, the frame and the other parts.
The build is checked against the part's envelope (its largest side between 0.4x and 2.5x), against walls under 0.2 mm and against anything over 2 m; a failure goes back to Claude like a FreeCAD error.
After three failed scripts a plain block of the envelope stands in, marked `fallback: true` and failing `printable`, so a live build never ends without geometry.
Each built part joins the assembly at once.

`part_pick` with `part_id` and `query` searches every catalog (`agent/data/catalogs/generic.json` with fans, motors, servos, pumps, controllers, sensors, lights, batteries and hardware, plus the gripper and drone catalogs); `select_id` binds a part, `estimate` `{name, mass_g, unit_price_eur, ...}` records an honest estimate.
Live shop prices plug in through `pai_agent.pricing.register_provider`: a provider gets the picked part and returns `{unit_price_eur, shop, url}` or `None`, and the first answer is marked `live`.

`reference_load` without `id` lists the library. With `id` and no live key it loads that item onto the bench the way an offline `POST /api/library/{id}/open` does. With a live key it returns the reference's spec and parts (`request`) and does not replay the saved run; the orchestrator builds it with the live tools, the same as opening it from the library.
A reference is a folder `agent/data/references/{id}/` with `reference.json` (`id`, `name`, `summary`, `spec`, `scripts` per printed part `{file, generated}`, `picks` per bought part `{select_id}` or `{estimate}` with an optional `reason`, and `checks` `[{tool, args}]`) and one FreeCAD script per printed part.
After a reference is loaded, the first chat request to Claude carries the build (spec, parts, picks, checks and requirement results), so Claude changes it with `cad_update`, `part_pick` or a revised `product_spec`.

`assemble` merges the printed parts, the bought blocks and the loads, with optional `placements` `{part_id: {position_mm, rotation_deg}}`, and returns mass, cost, size, bounding box, centre of mass, the footprint polygon and warnings (a part that floats, a part without position).

The checks judge every requirement of their kind and store their arguments, so `cad_update` (new `params` for a built part) and a `part_pick` swap rerun them all:
`check_totals` (mass, cost, size), `check_tip_over` (tip angle about the weakest footprint edge, atan of the distance from the centre of mass to that edge over its height, and the push at `push_height_mm` that tips it), `check_deflection` (`part_id`, `span_mm`, `width_mm`, `thickness_mm`, `load_n`, `support` cantilever or simple; Euler-Bernoulli with 85 % of the modulus and 60 % of the strength for printed plastic, stress safety 2x), `check_torque` (`actuator_part_id` and `required_torque_nm`, or `lever_mm` with `force_n` or `load_mass_g`; usable torque is 70 % of stall for a servo, 80 % for a stepper, 50 % for a DC motor), `check_runtime` (`battery_part_id` and `loads` `[{part_id or name, power_w, duty}]`, 80 % of the battery energy), `check_power` (`supply_part_id` and `loads` `[{part_id or name, power_w or current_a, voltage_v, duty, peak_factor}]`; other voltages through an 85 % regulator, headroom is the supply limit over the peak current, a battery also judges runtime), `check_thermal` (`enclosure_part_id`, `power_w` or `heat_part_ids`, optional `bbox_mm`, `wall_mm`, `vents_mm2`, `ambient_c`, `component_limit_c`; h = 5 W/m2K on the outer area through the wall plus air exchange through vents and every picked part with `airflow_m3h`), `check_rollover` (`track_mm` and `wheelbase_mm` or those parameters of a built part, the assembly's centre of mass height, `speed_mps` and `turn_radius_m`; static stability factor T / 2h in g), and `simulate_assembly` (the MuJoCo push or drop above).

`cad_part` builds any part from `name`, `description`, `params` (mm, they become the CAD sliders), `material` (`PLA`, `PETG`, `ABS`, `ASA`, `NYLON`, `TPU`, `ALUMINIUM`, `STEEL`), and optionally `script` or `template` (`gripper`).
Without a script Claude writes FreeCAD Python for the description; when FreeCAD reports an error, the script and the error go back to Claude for a fix, up to three attempts.
The script sees `Part`, `App`, `Vector`, `math` and `P` (the params) and sets `shape` or `parts = {name: solid}`, optionally `colors`, `materials` and `reference` (shown, not printed).
It is checked statically (only `FreeCAD`, `Part` and `math` imports, no file access, no dunder attributes), then runs in `freecadcmd` in a fresh temp directory with a scrubbed environment and a 60 s timeout; on macOS `sandbox-exec` also denies network access and writes outside that directory.
The result has `mass_g` (printed bodies, from each body's material density), `volume_mm3`, `bbox_mm`, per-body `parts` and the `attempts`.
Without `ANTHROPIC_API_KEY` only templates and passed scripts build.

`product_brief` picks `drone` or `gripper`; for the gripper it takes `object_mass_g`, `object_width_mm`, `max_weight_g`, `budget_eur` and `quote` and emits the requirements `payload`, `opening`, `weight`, `budget` and `printable`.
`catalog_search` reads `agent/data/catalogs/gripper.json` (`servo`, `pads`, `hardware`, `driver`).
`grip_calc` gives the finger force `0.7 × stall torque / (2 × lever)`, where the lever runs from the gear axis to the pad tip: the fingers swing on their gears, so the pads tilt and touch the object with their tips (`lever_mm`, and `closing_deg` for how far each finger swings shut).
The holding force is `μ × 0.7 × stall torque / (lever − μ × offset)`, where the offset runs across from the gear axis to the object's face: the object's weight drags the tips further shut.
The safety factor is the holding force against the object weight; 2× is the requirement.
`simulate_grip` runs the MuJoCo grip test above.
`robouse_trial` takes `harness` (`oracle`, the default, or `claude-code`), `goal` (`bowl` or `pad`) and `timeout_s` (Claude Code's limit, 60 to 900, default 600) and emits `trial`; it needs a gripper built by `cad_part` from its template.
`PAI_ROBOUSE_BIN` names the `anybuild-robouse` command (`off` turns Robo Use off); without it the bridge's own environment (`cd anybuild-robouse && uv sync`) or the command on `PATH` runs, and when there is none, or the export, the task or a trial fails, the recorded trial stands in.

`train_in_browser` queues a browser training job and waits until a dashboard tab finishes it; the result carries `best_params`, `best_metrics`, `best_score`, and `curve`.

`train_controller` is the drone's train loop after `simulate_mission` (the hardware check) passes. It flies the hardware check first when this build has none (the position hold when no mission was asked for); a failed one returns `result: "fail"`, `stage: "hardware"` without training.
Then it trains the seven gains on those missions plus a hover (`population` default 8, `generations` default 5, stopped after `PAI_TRAIN_BACKEND_S`, default 120 s; `time_limit_s: 0` means no limit), flies every mission again with them and runs the backend stress test with them.
It returns `result` (`pass` needs every mission and 90 % of the stress worlds), `stage: "trained"`, `training` (`rollouts`, `generations`, `score`, `start_score`, `seconds`, `stopped_early`), `gains`, `missions` (`[{mission, unit, limit, reference: {value, result}, trained: {value, result}, summary, why}]`), `stress` (`{survived, total, pass, needed, weakest, explanation}`) and `next`.
On a fail it adds `loop` (failed loops so far), `why` and `next_action`: `parts` (swap a part or change a dimension, the hardware check, then train again) or, after two failed loops, `ask` (ask the user).
In mock mode a prompt containing "train" runs it after a short Mechanic line, and the `training` step goes `running`, then `done` or `failed`.

`cad_frame` arguments are `arm_length_mm` (center to motor shaft), `thickness_mm`, and `motor_spacing_mm` (bolt-circle diameter of the motor screws).
The 1103 mount is 6.6 mm; with a motor chosen, the pads take its own `mount_diameter_mm` and the result's `notes` say so when the argument differed.
FreeCAD and CadQuery both build the whole drone around the frame from the chosen parts: motor bells at their diameter and height with the stator from the motor code, propellers at their diameter and blade count, the pack at its size, the flight controller scaled to its `mount_mm`. The GLB's `drone` node carries `extras` with the sizes it was built with.
`simulate_mission` takes `missions`, a list of `{mission, limit, quote, proposed}` (`mission` alone takes the brief's limit or Mechanic's proposal); see the `mission` event. It needs every drone part chosen and flies one mission at a time.
With a propeller chosen, an arm whose neighbouring motors stand closer than the propeller diameter plus 4 mm is an error that names the minimum arm.
The open FreeCAD window builds first when its RPC answers; on an error or a step over 12 seconds, `freecadcmd` builds headless.
CadQuery writes the same STL, STEP, and GLB when FreeCAD is missing or the script fails: the frame plate as STL and STEP, the whole drone from simple parametric parts as `drone.step` and the GLB.
`blender_render` runs `blender -b -P` on the current drone GLB, or on the frame STL after a CadQuery fallback.
`build_guide` is drone only, comes after `bom_build`, and takes `steps` as in the `build_guide` event, without `items`; a step number out of order, an unknown part, or a scene part no step installs is an error that names it.
A step may add `bom_parts`, categories from the bill of materials that have no scene part (`camera`, `canopy`, `hardware`); they show up in `items`.
`print_prep` comes after `bom_build`; `orientation` (`flat` by default, `auto` by default with a printer set, `upright`, `as_modeled`) applies to every part and `orientations` sets it per part id. It runs a slicer found on `PATH` or in `/Applications` (`PAI_SLICER` names an executable, `off` skips it) and emits one `print` event.

### Scene objects

`scene_object` puts a NVIDIA SimReady object into the scene, as context, as a size to design around, or as a payload or a target: `query` searches the offline catalogue (see [Objects](#objects)) and places the best match, with the next matches as `candidates`; `id` places one exact object; `role`, `position_mm`, `rotation_deg` and `collision` (`auto`, `hull` or `decompose`) are as in the [object](#object) event; `remove` with `id` takes it out.
The first use of an object downloads its package from Hugging Face into `~/.cache/anybuild/simready` (`PAI_SIMREADY_CACHE`, outside the repository; `agent/src/pai_agent/simready/fetch.py`).
The license is read first and anything but CC-BY-4.0 is refused, the bill of materials is checked against the packaging file's SHA-256 and every file against the bill of materials, and only what a conversion reads is fetched, not the MDL sources or the texture previews.
A cached object comes back in milliseconds without the network; `PAI_SIMREADY_MIRROR` reads packages from a local folder laid out like the dataset instead, and `HF_TOKEN` raises Hugging Face's rate limit.
A first use downloads at most `PAI_SIMREADY_MAX_MB` (default 300, about nine in ten objects): `query` then places the best match that fits and lists the larger ones it skipped in `warnings`, and an `id` over the limit is refused with smaller matches as `candidates`.
`agent/src/pai_agent/simready/convert.py` reads the USD with SimReady's MuJoCo physics variant selected, bakes every mesh into the object's frame (Z up, metres, whatever the file's units and up axis) and writes the MJCF body, then the GLB through Blender, the one `blender_render` uses.
CoACD runs in its own process for at most `PAI_SIMREADY_DECOMPOSE_S` seconds (default 180); after that the object keeps its hulls and the event warns.
CoACD and Blender run one at a time in a backend, Blender on two threads, so a second object waits instead of competing for the machine.
Conversions are cached per package content and converter code, and `PAI_CACHE=0` converts again.
The tool needs the optional `simready` extra (`cd agent && uv sync --extra simready` for usd-core, coacd, trimesh and huggingface_hub); without it the tool answers with that command and the search still works.

## Mock story

Without a key, the first drone prompt plays v1 through those tools, with the limits from that prompt (`limits_from_text`: a price in euros, minutes of flight time, a maximum weight in grams).
The story arrives at the reference micro build from Mediocre Nerd's "Build a Micro FPV Drone for $59" video: Twiglet 2" carbon frame, 1103 15000KV motors, Gemfan 2020 four-blade props, Caddx Ant camera, BetaFPV Matrix 1S 5in1 V2 AIO, canopy with battery holder, M1.4 bolts and a 1S pack (`agent/data/parts.json`, prices are samples).
For "Build a micro drone under 120 euros with at least 8 minutes of flight time, under 50 g." the requirements are under 120 €, at least 8 minutes and under 50 g from the prompt, plus hover and frame as STL and STEP proposed by Mechanic.
It tries the FunFly 4S first: the MuJoCo gust pushes it to the floor, the swap to the Tattu R-Line 1S 550 passes.
A 34 mm arm lets the 51 mm propellers touch, so the frame becomes the Twiglet's 42.5 mm.
v1 is 48.3 g, 8.2 min, 117.38 €.
Each build writes a `print` plan for the frame (an estimate without a slicer) and a `build_guide` from the same step template with the parts it chose: frame, motors, flight controller, wiring, camera and canopy, battery, motor test, propellers.
A request that names a job flies mission tests after the hover test (`missions_from_text`): fast or racing words fly the speed run and the turn, agile the turn, precise or steady the hold, hunt, catch or chase the chase with the speed run and the turn; a number in km/h, °/s, cm or seconds to catch becomes that mission's limit. "a fly hunter drone, incredibly fast, small and light, under 100 euros" flies the speed run, the turn and the chase against Mechanic's proposed limits. A later version flies the same missions again.
A typed change with a new limit ("Make it fly 10 minutes.") revises that requirement, keeps the others, and swaps to the BetaFPV LAVA II 1S 680, the other pack from the video.
v2 is 49.5 g, 10.1 min, 117.60 €, with its difference to v1.
A later prompt without a new limit does not rebuild; Mechanic asks for a number.
A prompt with the word "stress" ("stress test it") runs `stress_test` on the current build instead; without a build Mechanic asks for the drone first.
Once a build has finished, "robust" asks for it too ("how robust is it?").
Reset starts the story over.
A prompt that asks for a gripper (`gripper`, `claw`, `end effector`) plays the gripper story instead.
Mechanic turns the request into checks, tries the 2.49 € SG90 first: 0.9 N per finger is a safety of 0.9×, and in MuJoCo the can slides out when the arm lifts.
The swap to the MG996R gives 4.5 N per finger, a safety of 4.8×, and passes with no measurable slip.
An object the MG996R cannot hold at twice its weight, such as a 400 g cube 40 mm wide, steps up to the DS3218.
FreeCAD builds the gripper headless from the library template with the servo pocket sized for the MG996R (58 g PLA), Blender renders it, and the bill of materials comes to 18.65 € and 128 g.
Once the gripper is built, "Test it in Robo Use" (or "an independent test") runs `robouse_trial` on it; naming Claude Code asks for `harness: "claude-code"`, which still needs its credentials. Before any gripper, Mechanic asks for one first.
The drone and gripper stories call `firmware` right after `bom_build`: the drone gets a Betaflight CLI file, the gripper an Arduino sketch.
Both call `safety_check` right before `bom_build`: the drone gets the EU class C0 note (under 250 g, register the operator, no remote ID) and the lithium battery shipping note, the gripper the pinch-point warning with a gear cover and a firmware travel limit as the fix.
A prompt that asks for a lamp on mains (`lamp` with `230 V`, `mains` or `wall socket`) plays the safety story: Mechanic writes a 230 V desk lamp spec, `safety_check` flags mains voltage inside printed PETG, Mechanic asks whether to switch to a USB-C 5 V supply (the default), revises the spec and runs the check again without the mains finding. The run stops before FreeCAD; with a key Claude builds it.
The drone story calls `electronics_plan` right after `firmware`.
A prompt that asks for a phone stand (`phone`, `tablet` with `stand`, `holder`, `dock` or `mount`) plays the generic story: Mechanic writes the spec, FreeCAD builds the base plate and the back rest from the phone stand reference build (`agent/data/references/phone-stand/`), the rubber feet come from the catalog, and the assembly with the 200 g phone tips at 0.35 N, under the 0.75 N tap it must take; the MuJoCo push knocks it over.
Mechanic deepens the base from 60 to 110 mm with `cad_update`, every check runs again and passes (0.81 N, the push only rocks it), then Blender renders it and the bill of materials comes to 3.32 € and 116 g.
Once the drone is built, a prompt that asks for it lighter, cheaper, stronger or longer-running ("make the drone lighter but keep 8 minutes") runs `optimize_design` with goals and limits read from the sentence (`8 minutes` keeps the flight time, `under 50 g` the weight; without a number the flight-time requirement holds); before any build it builds v1 first.
Six variants come back, each with its checks; "take variant C" or a click on its point builds it as the next version.
With the user's 3D printer set, both stories add the printer beats (`agent/src/pai_agent/mock_printer.py`): `material_pick` for each printed part, then `fem_check` on its real shape.
The phone stand's back rest (a charging phone warms it to about 40 °C) and base pick from the printer's filaments, and the back rest is checked with the phone set down and a 5 N press on its top edge.
The drone's frame is printed: PETG on a printer with PLA and PETG (PLA softens at 55 °C next to 60 °C motors), and the 2 mm plate fails the crash on one motor at 1.7x against 2x; Mechanic thickens it to 2.5 mm with `cad_frame`, the FEM runs again and passes at 2.6x, and the bill of materials prices the frame as filament.
Without a printer the stories play as above.

## Omniverse results

`omniverse` events update the fourth canvas tab.
`mode` is `test` or `train`; `status` is `running`, `done`, or `recorded`; `source` is `live` or `recorded`.
`requested` holds the user's parameters, while `parameters` holds the actual run or fixed fixture conditions.
`metrics` maps English metric keys to finite numeric values, and `curve` holds `[iteration, mean_reward]` pairs.
`video_url` and `json_url` point to completed artifacts, or are null while running.
`stage`, when running, is `export`, `upload`, `execute`, or `download`.
`detail` explains progress, the result or fallback reason; `passed` is present only for a live product test.
`product_tested: false` identifies reference training and illustrative replays.
A recorded result is never evidence that the requested product or conditions were simulated.
`assembly_mass_g` excludes payload; `total_mass_g` includes it.
`gains` is optional on a live `done` training: the trained controller as `{roll, pitch, yaw}`, each `{p, i, d, f}` in Betaflight 4.4 units, which the firmware prefers over the browser-tuned gains; no Isaac job emits it yet.
Recorded fixture masses stay fixed and are identified separately from the displayed build version.
The tools `product_usd`, `isaac_test`, and `isaac_train` are documented in [Omniverse experiments](omniverse.md).

