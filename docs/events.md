# Event contract

The backend listens on `http://127.0.0.1:8100`.
The web app listens on `http://127.0.0.1:5180`.
This file is the only copy of the wire format.

## HTTP

`POST /api/prompt` with `{"text": "..."}` starts or continues the one local session; `"voice": true` marks the text as a spoken turn.
The response is `{"ok": true, "mode": "mock"|"claude", "status": "started"|"already_running"|"answered"|"ui"}`.
`mode` is `mock` when `ANTHROPIC_API_KEY` is empty or `PAI_FORCE_MOCK` is `1`.

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

State-changing calls without a typed body (`/api/reset`, `/api/webhooks/jamie`, `/api/cad/params`, `/api/cad/open`, `/api/versions/{n}/restore`) need `Content-Type: application/json`, else HTTP 415, so a web page cannot fire them as a plain cross-site form post.

A prompt that only asks to see or operate something in the dashboard ("show me the CAD", "open the library", "pull it apart", "compare v1 and v2", "focus on the battery", "mute") is answered with `status: "ui"` and `controls`: it becomes `ui_control` calls at once, also while a build runs, and never reaches the orchestrator.
`agent/src/pai_agent/app_control.py` matches these short commands; anything that changes the design goes to the orchestrator, which has the same tool.
"Rebuild" with a planned or live review on the timeline ends that review, like its End button; a test or a rebuild requested during a build answers `already_running`.

`POST /api/control` with `{"control": "run:test"}` or `{"control": "run:rebuild"}` is a person pressing Run test (Simulation tab) or Rebuild and recheck (CAD tab): the product's MuJoCo test, or the CAD built again from the current numbers with the numbers and the test rerun.
It answers `{"ok": true, "status": "started"}`, or `ok: false` with `error` while a build runs or before anything is built.

`POST /api/webhooks/jamie` accepts a JSON body with `event` (or `type`), `meeting_id`, and `title`.
`meeting.started` marks that meeting `live` on the timeline and builds nothing.
`meeting.ended` (also `meeting_ended` or `meeting ended`) starts a build from that meeting.
A kickoff starts a fresh session and builds v1.
A review rebuilds from the current version and writes the difference back to Jamie; without a v1 it builds the kickoff first.
An unknown meeting id takes the next timeline slot of its kind, a review when the title contains "Review"; without an id the title alone picks that slot.
A meeting that already has its version answers `status: already_built` and builds nothing, so a retried webhook is harmless; reset first to build it again.
With `JAMIE_WEBHOOK_SECRET` set, the webhook needs that value in `X-Jamie-Secret` or `?secret=`, else HTTP 401.
Any other event returns `{"ok": true, "status": "ignored"}`.
Sample bodies are `agent/data/webhooks/meeting-ended.json` (kickoff) and `agent/data/webhooks/review-ended.json`.

`POST /api/answer` with `{"id": "...", "answer_id": "..."}` answers the open `question`.
It is HTTP 409 when no such question is open.
A `POST /api/prompt` while a question is open answers it when the text names an option's number ("fifteen", "15", "fünfzehn") or agrees ("yes", "ok", "agreed", "ja", "passt"), and returns `status: answered`.

`POST /api/tasks/{id}` with `{"done": true}` ticks an order task as ordered and mirrors it to Jamie (`update_tasks`), then emits `tasks`.

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

`GET /api/voice` returns `{"stt": "reson8"|"browser", "tts": "elevenlabs"|"none", "realtime_url": "...", "turns_url": "...", "language": "en", "phrases": [...], "custom_model_id": null, "tts_sample_rate": 24000, "narrator": true}`.
`turns_url` is Reson8's Turns endpoint for hands-free listening, `realtime_url` its Realtime endpoint for push-to-talk.
`phrases` bias Reson8 toward our vocabulary (the `phrases` query parameter); a `custom_model_id` from `RESON8_CUSTOM_MODEL_ID` replaces them.
`narrator` is `true` when `ANTHROPIC_API_KEY` is set: the backend then writes Mechanic's spoken lines as `say` events and the client does not read `mascot` lines aloud.
Without ElevenLabs (`"tts": "none"`) Mechanic is silent and his text is the caption; the system voice is never used.
The recorded demo has no backend: its `mascot` events and open `question` events carry an optional `voice` URL (`/demo/voice/<hash>.mp3`), a pre-rendered ElevenLabs clip of the `say` text or of the last sentence of the question, which the client plays when the event arrives.
`POST /api/voice/token` returns `{"access_token": "...", "expires_in": 600}`, a short-lived Reson8 token for the browser's WebSocket (subprotocols `["bearer", token]`), or HTTP 503 without `RESON8_API_KEY`.
`POST /api/voice/speak` with `{"text": "...", "previous_text": "..."}` streams ElevenLabs speech for one phrase as raw 16-bit little-endian mono PCM (`audio/pcm`, sample rate in `X-Sample-Rate`, 24000), or HTTP 503 without `ELEVENLABS_API_KEY`.
`previous_text` is the phrase spoken just before, so one reply keeps a continuous intonation.
`POST /api/voice/warm` opens the backend's Claude and ElevenLabs connections ahead of a reply; the client calls it when a spoken turn starts, and repeated calls within 20 seconds do nothing.

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

### Versions

`GET /api/versions` answers `{"ok": true, "versions": [...]}`, every version of the session in the `version` event shape without `type`.
`POST /api/versions/{n}/restore` makes version `n` current: Mechanic rebuilds it through the same tools as any build (a product from the spec, part scripts, picks and checks saved with it; the drone by re-picking its catalog parts, the frame with its parameters, the hover test, the render and the bill of materials) and commits the result as a new version with `trigger` `restore` and `restored_from` `n`, so history only grows.
It answers like `POST /api/prompt` with `restoring: n`; HTTP 404 for an unknown `n`, 409 while Mechanic is building.
Versions live in the session; a reset clears them.

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
`agent/scripts/seed_community.py` rebuilds the seeds in mock mode, writes their real numbers into `entry.json`, and exports the same feed to `web/public/community/feed.json` for the recorded demo.

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
`bom` is the bill of materials, `versions` the Jamie versions in the `version` event shape, `files` the studio renders and CAD files (STEP, STL) the entry keeps.

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
The defaults come from `PAI_ORCHESTRATOR_MODEL` (else `ANTHROPIC_MODEL`), `PAI_ORCHESTRATOR_EFFORT`, `PAI_SUBAGENT_MODEL`, `PAI_SUBAGENT_EFFORT` and `PAI_DELEGATION`.

### Learning mode

`POST /api/explain` with `{"kind": "...", "id": "...", "chat": false}` explains one decision of the current build (`agent/src/pai_agent/explain.py`).
`kind` is `swap` (`id` a part category: the part before and after, the numbers on each side and the runs around it), `part` (a category or spec part id), `requirement` (a requirement id), `sim` (a run number) or `param` (a CAD parameter, `arm_length_mm` or `{part_id}.{param}`).
It answers `{"ok": true, "key", "kind", "target_id", "title", "text", "formula", "numbers": [{"label", "value", "unit"}], "source": "claude"|"template", "model": "claude-haiku-5-5"|null}`; HTTP 404 when the decision does not exist yet, such as a requirement whose check has not run.
The facts and the formula line come from the build state and the published events (the same formulas as `analysis.py` and `tools/physics.py`), so their numbers are computed.
With `ANTHROPIC_API_KEY` Claude Haiku (`ANTHROPIC_VOICE_MODEL`) writes `text` from the facts and the formula only; a reply with a number that is not in them, a 6 s timeout or no key gives the template text and `source: "template"`.
Answers are cached in memory by `key` (kind, id and a hash of the facts), so a repeated call is instant and a rebuild with new numbers gets a new explanation.
Every answer is also published as an `explain` event; `chat` is copied into it.

`POST /api/training/{job_id}/claim` with `{"client": "..."}` lets one dashboard tab take a queued browser training job; it returns the job's `spec`, `population`, and `generations`.
It is HTTP 409 when another client already holds the job, and 404 for a job of an earlier session.
`POST /api/training/{job_id}/progress` with `{"client", "status": "running"|"done"|"failed", "step", "generation", "best_score", "best_params", "best_metrics", "gains", "error"}` from the claiming client publishes a `training` event (`gains` is kept only with `status: "done"`); other clients get HTTP 409.
`POST /api/stress/{job_id}/claim` with `{"client": "..."}` lets one dashboard tab take a queued drone stress test; it returns `{"ok", "job_id", "product", "spec", "gains", "seed", "worlds"}`, where `worlds` are the 50 seeded worlds `{i, mass_scale, motor_scale, gust_mps, gust_dir_deg, gust_start_s, gust_len_s, downdraft_share, noise_m}`.
It is HTTP 409 when another client holds the job or it is over, and 404 for a job of an earlier session.
`POST /api/stress/{job_id}/progress` with `{"client", "status": "running"|"done"|"failed", "results": [{i, metrics, trajectory}], "error"}` from the claiming client hands finished worlds to the backend, which scores them and publishes the `stress` events; `metrics` are the drone episode's `crashed`, `drift_m`, `low_z_m`, and `tail_z_m`, and `trajectory` is `[[t, x, y, z], ...]` at 20 Hz.
`GET /api/training/browser` returns `{"ok": true, "job": {...}}` with the latest browser job of the session in the `training` event shape without `type`, or `job: null`.

`GET /api/health` returns `{"ok": true, "mode": "mock"|"claude", "busy": bool, "access": "open"|"required"}`; `busy` is true while a run is in flight, which the end-to-end tests and agent/scripts/profile_build.py wait on.
The dashboard calls it on start: when the backend answers it opens in live mode with an empty bench (after the access code, when `access` is `required`); without a backend it shows "Live backend offline, try again shortly" and retries.
Only the hidden `?demo` URL parameter plays the recording.

### Access

With `ANYBUILD_ACCESS_CODE` set on the backend, every route except `GET /api/health` and `POST /api/access` (including `GET /api/events`, the voice routes and `/files/`) needs a session, else HTTP 401 with `{"detail": "...", "access": "required"}`.
`POST /api/access` with `{"code": "..."}` (`Content-Type: application/json`) returns `{"ok": true, "token": "...", "expires_at": <unix seconds>}` and sets the same token as an `anybuild_session` cookie (`HttpOnly; Secure; SameSite=None`), valid for 24 hours.
A wrong code is HTTP 401; ten wrong codes from one IP in 15 minutes (or 200 from all IPs) are HTTP 429 until the window passes.
Clients send the token as `Authorization: Bearer <token>`, as the cookie, or as `?access_token=<token>` on URLs the browser loads itself (EventSource, images, models, videos).
`GET /api/access` is HTTP 200 while the session is valid, and always 200 without an access code.
`POST /api/webhooks/jamie` also accepts Jamie's own calls without a session when `JAMIE_WEBHOOK_SECRET` is set; signed-in users skip that secret.

With an access code, these calls are rate limited per session and, at three times the limit, per IP, in a sliding hour: builds (`POST /api/prompt`, `POST /api/sketch`, `POST /api/library/{id}/open`, `POST /api/versions/{n}/restore`, `POST /api/control`, `POST /api/webhooks/jamie`; `ANYBUILD_LIMIT_BUILDS`, default 20), `POST /api/voice/speak` (`ANYBUILD_LIMIT_SPEECH`, 300), `POST /api/voice/token` (`ANYBUILD_LIMIT_STT`, 60), `POST /api/cad/params` (`ANYBUILD_LIMIT_CAD`, 120), and `POST /api/explain` (`ANYBUILD_LIMIT_EXPLAIN`, 120).
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

No fields.
The first event of every stream and of every server reset: drop all session state.

### say

Mechanic's spoken line, live only: it is never kept in the backlog, so a reconnect does not replay it.
`id` names the line, `kind` is `reply` (the fast answer to a prompt) or `update` (a build milestone).
While the line is written, events carry `delta` (the next piece of text) and `done: false`.
The last event has `done: true` and the whole `text`; `cancelled: true` means a newer prompt replaced the reply mid-way.
Every finished line, reply or update, is also published as an agent `chat` event with `voice: true`, so the conversation stays readable in the chat.
Updates follow `sim`, `cad`, `version` and failed `step` events of a running build, never slider changes, and wait until the reply is finished.

### explain

One decision explained, the `POST /api/explain` answer without `ok`, plus `chat`.
`chat: true` means a live event asked for it (learning mode on: a part swap after its new numbers, a requirement turning `met: false`, a failed `sim`, a changed CAD parameter), so the client shows it as a chat card; otherwise it is the answer to a "Why?" click and only shows there.
The client keeps the latest event per `key`.

### replayed

No fields, and only on this connection: everything before it was backlog from earlier, everything after it is live.
Apply the backlog without animations.

### step

`id` is `meeting`, `teile`, `cad`, `render`, `simulation`, `training`, or `stueckliste`.
The mock story does not use `training`; a "train it" prompt does.
`status` is `pending`, `running`, `done`, or `failed`.
`label` is `Meeting`, `Parts`, `CAD`, `Render`, `Simulation`, `Training`, or `BOM`.

A step can be `done` while a tool on that step is `offline`.
In the mock story, render is done after Blender and Isaac Sim have both been asked.
Training is done when the fallback curve has been played.
The tool pill still shows `offline`.

### chat

`role` is `user` or `agent`.
`text` is the utterance.
`voice: true` marks a spoken line: a user turn heard by Reson8 or the browser, or a line Mechanic said aloud (a `say` reply or update).

### tool

`name` is the tool name from the list below.
`status` is `connected`, `running`, `ok`, `error`, or `offline`.
`detail` is a short English line.
The final event of a call (any status but `running`) carries `ms`, the tool's wall time in milliseconds.
`timed_out: true` marks a tool stopped by its time limit (agent/src/pai_agent/timeouts.py); `status` is then `error` (Blender: `offline` with the recorded still) and `detail` names the tool and the limit, the same line the agent says in the chat.
`cached: true` marks a FreeCAD part reused from agent/runs/cache/ because the script, parameters and material were identical.
A `cad` event's `source` is `cadquery` when FreeCAD was missing or stuck and CadQuery built the part's envelope as a plain block.

### requirement

For the drone, `id` is `budget`, `flight_time`, `weight`, `hover`, or `printable`.
`budget`, `flight_time`, and `weight` come from the Jamie template `Hardware-Anforderungen` when that template is on the meeting.
`hover` and `printable` stay extra lines from the transcript.
Without the template, the requirements array is used, and only then sentences in the transcript.
`text` is the requirement.
`source_quote` is the sentence it came from; `speaker`, `time`, and `meeting_title` say who said it, when, and where.
`changed_from` is the earlier text when a later meeting changed it, else `null`.
`met` is `true`, `false`, or `null`.
`null` means the build does not know yet.
For a product built from a spec, `id` is the spec requirement id, the quote is the user's request, and `detail` is the number its check found against the limit, such as `0.81 N, min. 0.75 N`; `detail` is absent or `null` before the check ran.

### metrics

`weight_g`, `thrust_to_weight`, `flight_time_min`, `price_eur`.
Numbers are already rounded.
`price_eur` is a total to verify, not a checkout: catalog samples, or live shop prices once `bom_build` found them.
After `bom_build` finds live prices, a second `metrics` event carries the live total in `price_eur`; the other numbers repeat.

For a product other than the drone the event carries `cards` instead of the drone numbers, and the panel shows those.
Each card is `{key, label, value, unit, digits, limit, ok, pending}`: `limit` is the line under the number (such as `min. 2 ×`), `ok` says whether it meets its requirement, and `pending: true` means its check has not run yet.
A product built from a spec sends `weight_g` and `price_eur` (product mass without external loads, and cost) and four cards: Mass, Cost, and the next two requirements with a number (tip-over, deflection, torque safety, runtime, push test tilt, drop load, size, power headroom, thermal or roll-over).
The gripper sends `weight_g`, `price_eur`, `grip_force_n`, `safety_factor`, and the cards Grip safety, Finger force, Weight and Price.

### product

`id` is `drone`, `gripper`, or the slug of a product spec such as `phone-stand`; `label` is the display name.
`kind` is `generic` for a product built from a spec.
Sent by `product_brief` and `product_spec`; a revised spec that keeps the name or any part id keeps the same `id` (only the `label` changes), and its `requirements` lists the requirement ids it still has, so the client drops the others.
When the product changes, the client drops the other product's requirements, numbers, parts, runs, CAD, renders and bill of materials.
Without this event a fresh bench has no product; the first drone event (drone metrics, a drone part, a hover run, the frame CAD, a version) makes it the drone.

### sketch

The photo of a hand sketch a build started from: `id` (`sketch-1`), `url` (under `/files/`, never the image data), `status` and `note` (what the user wrote with it).
`reading` comes first, when the photo is stored; `sketch_to_spec` then publishes `read` with `summary` (one sentence), `read` (`[{label, value, unit, confidence}]`, confidence `high`, `medium` or `low`), `unreadable` (strings), `product` (the spec id) and `source` (`claude` or `recorded`), or `failed` with `error` and `unreadable`.
The client shows the latest sketch in the Model tab; a `reset` drops it, and so does a `product` event for another product than the sketch's.

### remix

`{"type": "remix", "id": "quiet-desk-fan", "title": "Quiet USB desk fan", "author": "maker.kai"}` says the bench holds a remix of that community entry.
Sent once when `POST /api/community/{id}/remix` starts; the client shows a "Remixed from" link back to the original until the next reset, and publishing the build links the new entry to it.

### sim

`run` is `1` for the heavy pack and `2` after the swap in the mock story.
`result` is `pass` or `fail`.
`summary` is one English sentence.
`trajectory` is `[[t, x, y, z], ...]` in seconds and meters.
The test climbs to 0.5 m; from 1.6 s to 1.9 s a downdraft of 35 % of the weight pushes on it.
It passes when the drone never drops below 0.2 m after the gust and holds 0.35 m or more over the last half second.

`kind` is `grip` for the gripper test (absent for the drone).
Then `trajectory` z is how far the object has risen, `hand` is `[[t, z], ...]` for the hand, and the event also carries `object_width_mm`, `payload_g`, `force_n` (per finger) and `slip_mm`.
The pads squeeze with the finger force, the hand lifts 15 cm from 0.4 s to 1.4 s, holds, and shakes ±1.5 cm at 2.5 Hz from 2.0 s to 2.8 s.
It passes when the object never lags the hand by more than 10 mm.

`kind` is `rigid` for the MuJoCo test of a whole assembled product (`simulate_assembly`).
The assembly is one rigid body: the convex hull of all its bodies collides with the floor, its mass and centre of mass come from the CAD masses, the picked parts and the external loads.
`mode` is `push` or `drop`.
`poses` is `[[t, x, y, z, qw, qx, qy, qz], ...]` every 0.02 s for the body frame (metres, z up), `tilt` is `[[t, degrees], ...]`, and `trajectory` holds the same positions as `[t, x, y, z]`.
`glb_url` is the assembly model; the body frame is the assembly frame shifted down by `floor_mm`, so the model is drawn at `z - floor_mm`.
`bbox_mm` and `size_mm` describe the assembly.
A push carries `force_n`, `push_point_mm` (body frame, mm), `push_dir` (plan view unit vector), `push_window_s` (`[0.5, 0.8]`) and `limit_deg`; it passes when the final tilt stays within `limit_deg`.
A drop falls from `drop_height_mm` with a 5° tilt and reports the peak load in g in `summary`.

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
`glb_url` and `stl_url` are `assembly.glb` (all bodies, bought parts and loads as blocks) and `assembly.stl` (printed bodies), `step_url` is `null` (each part has its own STEP), `script_url` is `assembly-scripts.py` with every part's script, and `part` sums the printed parts.

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
With `ANTHROPIC_API_KEY` set, `bom_build` first sends the catalog list with `prices: "searching"`, then a second `bom` with the live lines; the second replaces the first.
Without the key every line stays on the catalog and `prices` is `catalog`.
`prices` is `live` when at least one line has a live price, else `catalog`.
Each item also has `price_source` (`live`, or `catalog` for the drone and gripper; a spec product keeps `sample` or `estimated` when no live price is found), `currency`, and `availability` (`in_stock`, `out_of_stock`, or `unknown`).
A `live` item's `unit_price_eur`, `shop`, and `url` come from a web search (Claude with the server-side web search tool, EU shops first); it adds `price` and `currency` as the shop shows them, `pack_qty` when the shop sells a multipack, `catalog_price_eur`, and `checked_at` (ISO time).
A line falls back to the catalog when the search fails, finds nothing, or returns a price more than four times off the catalog sample; printed parts (shop `printed`, or a `url` that is not an http link) are never searched.
Live results are cached in memory for 15 minutes (failed searches for one minute), so a rebuild only searches the changed parts, and later `metrics` keep using the cached live prices in `price_eur`.
Older recordings have no `prices` or `price_source`; read them as `catalog`.
`stl_path` is the STL path relative to the repository root, or an empty string before CAD.
After `print_prep` the list ends with one filament line (`category: "filament"`, shop `printed`, `weight_g` 0, `unit_price_eur` 0) naming the material and grams of the print plan; it never changes `total_eur`, because printed parts already carry their filament cost and the drone's printed frame is an optional test print next to the bought carbon frame.

### mascot

`state` is `ruhig`, `denkt`, `erklaert`, `freut_sich`, or `besorgt`.
`say` is the short line in the speech bubble.

### jamie

`action` is `meeting_ended`, `upsert_template`, `requirements`, `search`, `get_meeting`, `create_tasks`, `update_tasks`, `create_tag`, `add_tag_to_meetings`, or `note`.
`status` is `ok` or `error`.
`detail` is a short English line; it ends in `· local outbox` when no live call was made. A leftover German phrase is shown in English by the dashboard.
With `JAMIE_MCP_TOKEN` set, writes go to `https://mcp.meetjamie.ai/mcp` and are also logged to the session's `jamie_outbox.json`.
Without the token, or when a live call fails, they only land in that outbox.
A live call times out after 5 seconds; after a failure the server is skipped for 60 seconds, so a dead network costs one timeout, not one per call.
Jamie documents no note tool, so `note` uses one when the server lists it and is otherwise written as a task on the meeting.

### meeting

One meeting on the Jamie timeline.
`id`, `title`, `date` (`YYYY-MM-DD`), and `time` (`HH:MM`).
`kind` is `kickoff`, `review`, or `archive`; archive meetings hold earlier warnings and are not timeline stations.
`status` is `done`, `live`, or `next`.
`version` is the drone version built from this meeting, or `null`.
`tags` are the Jamie tags AnyBuild put on it, such as `drohne` and `drohne-v1`.
`replaces` is set when a live Jamie meeting took over a planned station; drop the station with that id.
The whole timeline is published at startup and after reset.

### version

A finished build, attached to the meeting it came from.
`n`, `meeting_id`, `meeting_title`, `weight_g`, `thrust_to_weight`, `flight_time_min`, `price_eur` (the same numbers as the last `metrics`), and `sim` (`pass`, `fail`, or `null`).
`parts` maps each category to the part name.
`diff` lists what changed against the previous version: `{key, label, before, after, unit}`.
Number rows have a `unit`; part rows have `key` `part:{category}`, names in `before` and `after`, and an empty `unit`.
`summary` is one line such as `48.4 g · 10.4 min · 117.60 €`.
Every rebuild is a version: the drone's come from `version_commit`, every other product commits one after its `bom_build`.
Each version is published once, with the fields below.
`trigger` is `meeting`, `chat`, `library`, `check_failed` (a chat rebuild that makes a requirement pass that the last version failed) or `restore`; older recordings have none, read them as `meeting`.
`product` is `drone`, `gripper` or `generic`; `label` names the trigger in one line (the meeting title, the chat request, `Restored v1`).
For a non-drone product `meeting_id` is empty, `meeting_title` is the label, `weight_g` and `price_eur` are set, `thrust_to_weight` and `flight_time_min` are `null`, and `cards` are its metric cards as the last `metrics` event had them.
`requirements` is `[{id, text, met, detail}]` at commit time, `params` the CAD parameters (`arm_length_mm` for the drone frame, `{part_id}.{param}` for a product), and `nodes` maps a product's part ids to the body names in its GLB.
`files` is `{glb_url, render_url}`: a copy of the model made for this version (`/files/{session}/v{n}-frame.glb`, `v{n}-assembly.glb`, `v{n}-part-….glb`) and its studio render; either is `null` when there was none.
`restored_from` is the version a restore rebuilt, else `null`; `at` is the local commit time.
The diff also covers changed CAD parameters (key `param:{name}`) and requirements that flipped (key `req:{id}`, `before` and `after` are `pass` or `fail`).

### part

A part was chosen.
`category`, `id`, `name`, `mass_g`, `size_mm` (`[length, width, height]` for batteries, else `null`), and `diameter_mm` (propellers).
`why` is the Jamie sentence behind the choice, `{text, speaker, time, meeting_id, meeting_title}`, or `null`.
`reason` is the agent's own reason in one line.
`warnings` are sentences from earlier meetings that warn about this part, each a quote plus `note` (usually the meeting date).
`considered: true` marks a candidate that was weighed but not chosen; it only brings its warnings.

### question

Mechanic asks before building, for example when two meetings disagree.
`id`, `text`, `options` (`[{id, label}]`), `default_id`, and `timeout_s`.
`status` is `open`, then `answered` with `answer_id`.
Without an answer the default applies after `timeout_s` (`PAI_ASK_TIMEOUT_S`, default 20).

### agent

The orchestrator and the sub-agents it delegates to, one card per agent, sent again whenever it reports.
`id` is stable for one agent run, `role` is `orchestrator`, `cad` (writes one part's FreeCAD script), `parts`, `checks`, `pricing` or `optimizer` (one design optimizer variant, "Variant agent A"), `label` its name ("Orchestrator", "CAD agent", "Parts agent", "Analysis agent", "Pricing agent").
`model` and `model_label` (`claude-sonnet-5-5`, "Sonnet 5.5"), `effort`, `task` (the job in one line), `status` (`queued`, `running`, `done` or `error`), `rounds` (model calls so far), `input_tokens`, `output_tokens`, `cache_read_tokens`, `cost_usd` (from the published per-token prices) and `summary` (what it does now, or its report when done).
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

### tasks

The order tasks, one per part, published whole after every change.
`meeting_id` is the meeting they hang on, `live` is `true` only when every task was created in Jamie, not in the outbox.
Each item is `{id, title, assignee, due, done, part_category}`; `due` reads like `27 Oct`.
A rebuild keeps the tasks of unchanged parts with their `done` state and closes the tasks of replaced parts.

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

### point

`target` is a scene name.
`label` is the pointer caption.
The pointer flies to that exact name.
It does not guess from a screenshot.

### ui

Mechanic operates a dashboard control: `{id, control, say}` plus, depending on the control, `open` (panels, `true` opens and `false` closes), `value` (`explode` 0 to 100, `setting:*` true or false), `part` (`focus`) and `versions` (`panel:compare`, two version numbers).
The dashboard flies the pointer to the element with that `data-control`, presses it with `say` in the bubble, then acts; a control behind another one (a setting inside the settings panel, the build guide inside the bill of materials, a tab while the library is open) is pressed open on the way.
`run:test` and `run:rebuild` only show the button; the backend runs them right after.
`run:review` points at the timeline's End button while a "rebuild" ends that review.
With HeyClicky off (the pointer button in the chat composer, on by default) the action happens without the pointer, and `point` events are not shown either.
Only fresh events act; a replayed backlog changes nothing.

### training

`status` is `queued`, `running`, `done`, `failed`, or `offline`.
`step` and `reward` are the latest curve point, or `0` when there is none.
`curve` is `[[step, reward], ...]`.
`video_url` is a backend path such as `/files/fallback/hover.mp4`, or `null` when there is no clip.
A `done` event after an `offline` tool means the fallback file was played, not that a pod finished a job.
The browser training's `done` event carries `gains` (see the browser run below); the firmware reads its `roll` and `pitch` `{p, i}` as browser-tuned gains.

### firmware

The firmware and wiring for the built product, from the `firmware` tool after `bom_build`.
`kind` is `betaflight` (a drone with a flight controller) or `arduino` (a servo product).
`product` is the product name, such as `drone`.
`filename` is the file name, such as `anybuild-drone-v1-betaflight.txt` or `anybuild_gripper_v1.ino`; `url` is its `/files/{session}/{filename}` path.
`content` is the whole file, so a client can offer the download without the backend.
The file is a fixed template filled from the chosen parts; only `explanation`, one or two sentences, may come from Claude.
`gains` is `{roll, pitch, yaw}`, each `{p, i, d, f}` in Betaflight units, or `null` for an Arduino sketch.
`gains_source` says where they came from, first match wins: `isaac`, `browser`, `defaults`, or `none` (an Arduino sketch).
`isaac` is the `gains` field of the last live Isaac Lab training (`omniverse` with `mode: "train"`, `source: "live"`, `status: "done"`); no Isaac job emits it yet, so this source stays inactive until one does.
`browser` is the `gains` field of the last `done` browser `training` event (`source: "browser"`).
`defaults` are the Betaflight 4.4 starting values for a 1S whoop. With `isaac` or `browser`, missing terms keep the defaults.
When a training run finishes after the firmware was made and changes the gains, a new `firmware` event follows with the new source.
The dashboard shows the source next to Download firmware: Isaac Lab gains, Browser-tuned gains, or Default gains.
`wiring` is a list of `{component, connects_to, pin, wire, note}`, one row per connection of a chosen part.

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
`weakest` names the factor that separates lost worlds from survived ones, or is `null` when every world survived; `explanation` is Bolzen's one sentence about it.

Drone: the worlds fly in the browser, on the MuJoCo WASM workers of the training module, with its drone episode: the controller holds its spot 1 m up for 10 s while a 1-cosine gust hits it.
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
A local run, started with the Training pane's "Train in this browser" button in the static demo or without a backend, never reaches the backend: it has no `job_id`, sends no claim or progress, and publishes no `training` event, so its gains do not feed the stress test or the firmware.
`failed` with `error: "no_browser"` means no dashboard claimed the job within `PAI_TRAIN_CLAIM_TIMEOUT_S` (default 20); a run that does not finish within `PAI_TRAIN_TIMEOUT_S` (default 240) fails with `error: "timeout"`, and a claimed run that reports nothing for `PAI_TRAIN_STALL_S` (default 30) fails with `error: "browser_gone"`, for example after the tab was closed or reloaded.

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
- `setting:agents`, `setting:tools`, `setting:jamie`, `setting:all_metrics`, `setting:push_to_talk`, `setting:voice`
- `explode`, the slider in the corner of the Model tab
- `focus`, the 3D camera turns to `part` (a scene target, or a spec part's id or name)
- `run:test`, `run:rebuild`
- `library:{id}`, one library item

`agent/src/pai_agent/scene.py` holds the list with a description each; the orchestrator's prompt and the voice model's prompt carry it.
Closing buttons are tagged `{control}:close`, and `look:3d` is the 3D switch of the Model tab.

## Tools

`jamie_templates`, `jamie_requirements`, `jamie_search`, `jamie_meeting`, `requirements_accept`, `ask_user`, `parts_search`, `physics_calc`, `simulate_drone`, `stress_test`, `cad_frame`, `cad_part`, `product_brief`, `product_spec`, `sketch_to_spec`, `reference_load`, `delegate`, `part_pick`, `assemble`, `cad_update`, `check_totals`, `check_tip_over`, `check_deflection`, `check_torque`, `check_runtime`, `check_power`, `check_thermal`, `check_rollover`, `simulate_assembly`, `catalog_search`, `grip_calc`, `simulate_grip`, `isaac_lab_train`, `isaac_lab_status`, `isaac_sim_render`, `blender_render`, `bom_build`, `print_prep`, `build_guide`, `firmware`, `jamie_create_tasks`, `version_commit`, `ui_point_at`, `ui_draw`, `ui_control`, `mascot_say`, `train_in_browser`, `optimize_design`, `optimize_apply`.

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
A requirement has `text`, `check` and a limit: `mass` (max g, product without loads), `cost` (max eur), `size` (max mm, largest side), `tip_over` (min deg, or min N pushed at the top), `deflection` (max mm, optional `part_id`), `torque` (min x), `runtime` (min with `unit` `min`, `h` or `days`), `stability` (max deg after the push), `drop` (max g), `power` (min x supply headroom over the peak current), `thermal` (max `deg_c` inside the case), `rollover` (min `g` lateral, or min `deg` side slope) or `printable` (no limit).
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

`reference_load` without `id` lists the library, with `id` loads one item onto the bench the way `POST /api/library/{id}/open` does, so a chat request such as "start from the phone stand" works too.
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
`grip_calc` gives the finger force `0.7 × stall torque / (2 × lever)`, where the lever runs from the gear axis to the pad centre, the holding force `2 × μ × F`, and the safety factor against the object weight; 2× is the requirement.
`simulate_grip` runs the MuJoCo grip test above.

`train_in_browser` queues a browser training job and waits until a dashboard tab finishes it; the result carries `best_params`, `best_metrics`, `best_score`, and `curve`.
In mock mode a prompt containing "train" runs it after a short Bolzen line, and the `training` step goes `running`, then `done` or `failed`.

`cad_frame` arguments are `arm_length_mm` (center to motor shaft), `thickness_mm`, and `motor_spacing_mm` (bolt-circle diameter of the motor screws).
The 1103 mount is 6.6 mm.
With a propeller chosen, an arm whose neighbouring motors stand closer than the propeller diameter plus 4 mm is an error that names the minimum arm.
The open FreeCAD window builds first when its RPC answers; on an error or a step over 12 seconds, `freecadcmd` builds headless.
CadQuery writes the same STL, STEP, and GLB when FreeCAD is missing or the script fails.
`blender_render` runs `blender -b -P` on the current drone GLB, or on the frame STL after a CadQuery fallback.
`jamie_requirements` reads the `Hardware-Anforderungen` fields first.
`build_guide` is drone only, comes after `bom_build`, and takes `steps` as in the `build_guide` event, without `items`; a step number out of order, an unknown part, or a scene part no step installs is an error that names it.
A step may add `bom_parts`, categories from the bill of materials that have no scene part (`camera`, `canopy`, `hardware`); they show up in `items`.
`print_prep` comes after `bom_build`; `orientation` (`flat` by default, `upright`, `as_modeled`) applies to every part and `orientations` sets it per part id. It runs a slicer found on `PATH` or in `/Applications` (`PAI_SLICER` names an executable, `off` skips it) and emits one `print` event.

## Mock story

Without a key, the kickoff (webhook or first prompt) plays v1 through those tools.
The story arrives at the reference micro build from Mediocre Nerd's "Build a Micro FPV Drone for $59" video: Twiglet 2" carbon frame, 1103 15000KV motors, Gemfan 2020 four-blade props, Caddx Ant camera, BetaFPV Matrix 1S 5in1 V2 AIO, canopy with battery holder, M1.4 bolts and a 1S pack (`agent/data/parts.json`, prices are samples).
The agent reads the kickoff (under 120 €, at least 8 minutes, under 50 g, hover, frame as STL and STEP), finds the 1103 15000KV from last week's flight test and Lea's warning about the FunFly 4S.
It tries the FunFly anyway: the MuJoCo gust pushes it to the floor, the swap to the Tattu R-Line 1S 550 passes.
A 34 mm arm lets the 51 mm propellers touch, so the frame becomes the Twiglet's 42.5 mm.
v1 is 47.2 g, 8.5 min, 117.38 €.
Each build writes a `print` plan for the frame (an estimate without a slicer) and a `build_guide` from the same step template with the parts it chose: frame, motors, flight controller, wiring, camera and canopy, battery, motor test, propellers.
The review "Review 1" asks for 10 minutes.
Mechanic asks which flight time counts and swaps to the BetaFPV LAVA II 1S 680, the other pack from the video.
v2 is 48.4 g, 10.4 min, 117.60 €, and the difference goes back to the review as a note.
A later prompt in the same session does not rebuild.
A prompt with the word "stress" ("stress test it") runs `stress_test` on the current build instead; without a build Mechanic asks for the kickoff first.
Once a build has finished, "robust" asks for it too ("how robust is it?"); a prompt that ends a review still runs the review first.
Reset starts the story over.
A prompt that asks for a gripper (`gripper`, `claw`, `end effector`) plays the gripper story instead.
Mechanic turns the request into checks, tries the 2.49 € SG90 first: 1.1 N per finger is a safety of 0.9×, and in MuJoCo the can slides out when the arm lifts.
The swap to the MG996R gives 6.0 N per finger and passes with 0.4 mm slip.
FreeCAD builds the gripper headless from the library template with the servo pocket sized for the MG996R (58 g PLA), Blender renders it, and the bill of materials comes to 18.65 € and 128 g.
The drone and gripper stories call `firmware` right after `bom_build`: the drone gets a Betaflight CLI file, the gripper an Arduino sketch.
A prompt that asks for a phone stand (`phone`, `tablet` with `stand`, `holder`, `dock` or `mount`) plays the generic story: Mechanic writes the spec, FreeCAD builds the base plate and the back rest from the phone stand reference build (`agent/data/references/phone-stand/`), the rubber feet come from the catalog, and the assembly with the 200 g phone tips at 0.35 N, under the 0.75 N tap it must take; the MuJoCo push knocks it over.
Mechanic deepens the base from 60 to 110 mm with `cad_update`, every check runs again and passes (0.81 N, the push only rocks it), then Blender renders it and the bill of materials comes to 3.32 € and 116 g.
Once the drone is built, a prompt that asks for it lighter, cheaper, stronger or longer-running ("make the drone lighter but keep 8 minutes") runs `optimize_design` with goals and limits read from the sentence (`8 minutes` keeps the flight time, `under 50 g` the weight; without a number the flight-time requirement holds); before any build it builds v1 first.
Six variants come back, each with its checks; "take variant C" or a click on its point builds it as the next version.
The dashboard's `?demo` replays exactly the drone run from `web/src/events/recording.json`, written by `agent/scripts/record_demo.py`.

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

