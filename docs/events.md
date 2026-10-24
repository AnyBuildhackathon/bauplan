# Event contract

The backend listens on `http://127.0.0.1:8100`.
The web app listens on `http://127.0.0.1:5180`.
This file is the only copy of the wire format.

## HTTP

`POST /api/prompt` with `{"text": "..."}` starts or continues the one local session.
The response is `{"ok": true, "mode": "mock"|"claude", "status": "started"|"already_running"}`.
`mode` is `mock` when `ANTHROPIC_API_KEY` is empty or `PAI_FORCE_MOCK` is `1`.

`GET /api/events` is a Server-Sent Events stream.
Each event is one `data: ` line of JSON, followed by a blank line.
Comments of the form `: keepalive` are not events.
A client that connects late receives the events already published, then the live ones.

`POST /api/reset` clears the session, the chat memory, and the event buffer, then publishes a `reset` event, a fresh tool snapshot, pending steps, and the timeline.
Every stream starts with a `reset` event, so a client that reconnects replays onto an empty state.

State-changing calls without a typed body (`/api/reset`, `/api/webhooks/jamie`, `/api/cad/params`, `/api/cad/open`) need `Content-Type: application/json`, else HTTP 415, so a web page cannot fire them as a plain cross-site form post.

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
For the gripper, `grip_calc` then runs again, so a longer finger shows up as a lower finger force.

`POST /api/cad/open` opens the current part in the FreeCAD app.
The response is `{"ok": true, "path": "frame.FCStd"}` when the app launches, or `{"ok": false, "detail": "..."}` when there is no part or no FreeCAD app.
It prefers `frame.FCStd`, then STEP, then STL.

`GET /api/voice` returns `{"stt": "reson8"|"browser", "tts": "elevenlabs"|"browser", "realtime_url": "...", "language": "en"}`.
`POST /api/voice/token` returns `{"access_token": "...", "expires_in": 600}`, a short-lived Reson8 token for the browser's WebSocket (subprotocols `["bearer", token]`), or HTTP 503 without `RESON8_API_KEY`.
`POST /api/voice/speak` with `{"text": "..."}` returns `audio/mpeg` from ElevenLabs, or HTTP 503 without `ELEVENLABS_API_KEY`.

`GET /api/health` returns `{"ok": true, "mode": "mock"|"claude"}`.

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

### replayed

No fields, and only on this connection: everything before it was backlog from earlier, everything after it is live.
Apply the backlog without animations.

### step

`id` is `meeting`, `teile`, `cad`, `render`, `simulation`, `training`, or `stueckliste`.
The mock story does not use `training`.
`status` is `pending`, `running`, `done`, or `failed`.
`label` is `Meeting`, `Parts`, `CAD`, `Render`, `Simulation`, `Training`, or `BOM`.

A step can be `done` while a tool on that step is `offline`.
In the mock story, render is done after Blender and Isaac Sim have both been asked.
Training is done when the fallback curve has been played.
The tool pill still shows `offline`.

### chat

`role` is `user` or `agent`.
`text` is the utterance.

### tool

`name` is the tool name from the list below.
`status` is `connected`, `running`, `ok`, `error`, or `offline`.
`detail` is a short English line.

### requirement

`id` is `budget`, `flight_time`, `weight`, `hover`, or `printable`.
`budget`, `flight_time`, and `weight` come from the Jamie template `Hardware-Anforderungen` when that template is on the meeting.
`hover` and `printable` stay extra lines from the transcript.
Without the template, the requirements array is used, and only then sentences in the transcript.
`text` is the requirement.
`source_quote` is the sentence it came from; `speaker`, `time`, and `meeting_title` say who said it, when, and where.
`changed_from` is the earlier text when a later meeting changed it, else `null`.
`met` is `true`, `false`, or `null`.
`null` means the build does not know yet.

### metrics

`weight_g`, `thrust_to_weight`, `flight_time_min`, `price_eur`.
Numbers are already rounded.
`price_eur` is a sample total to verify, not a live checkout.
After `bom_build` finds live prices, a second `metrics` event carries the live total in `price_eur`; the other numbers repeat.

For a product other than the drone the event carries `cards` instead of the drone numbers, and the panel shows those.
Each card is `{key, label, value, unit, digits, limit, ok}`: `limit` is the line under the number (such as `min. 2 ×`), `ok` says whether it meets its requirement.
The gripper sends `weight_g`, `price_eur`, `grip_force_n`, `safety_factor`, and the cards Grip safety, Finger force, Weight and Price.

### product

`id` is `drone` or `gripper`, `label` is the display name.
Sent by `product_brief`.
When the product changes, the client drops the other product's requirements, numbers, parts, runs, CAD, renders and bill of materials.
Without this event the session is the drone.

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

### cad

`source` is `freecad` or `cadquery`.
`tree` is `[{id, label, children}]`. The mock frame is `Frame` with `Hub`, `Arms`, and `Motor pads`.
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

`items` is a list of `{name, qty, unit_price_eur, weight_g, shop, url}`.
`weight_g` is the mass of one piece, not the line.
`url` may be an empty string for the printed frame.
`total_eur` is the sum of `unit_price_eur * qty`.
`prices` is `catalog`, `searching`, or `live`.
With `ANTHROPIC_API_KEY` set (and `PAI_LIVE_PRICES` not `0`), `bom_build` first sends the catalog list with `prices: "searching"`, then a second `bom` with the live lines; the second replaces the first.
Without the key every line stays on the catalog and `prices` is `catalog`.
`prices` is `live` when at least one line has a live price, else `catalog`.
Each item also has `price_source` (`live` or `catalog`), `currency`, and `availability` (`in_stock`, `out_of_stock`, or `unknown`).
A `live` item's `unit_price_eur`, `shop`, and `url` come from a web search (Claude with the server-side web search tool, EU shops first); it adds `price` and `currency` as the shop shows them, `pack_qty` when the shop sells a multipack, `catalog_price_eur`, and `checked_at` (ISO time).
A line falls back to the catalog when the search fails, finds nothing, or returns a price more than four times off the catalog sample; the printed frame is never searched.
Results are cached in memory for `PAI_PRICE_CACHE_S` seconds (default 900), so a rebuild only searches the changed parts.
Older recordings have no `prices` or `price_source`; read them as `catalog`.
`stl_path` is the STL path relative to the repository root, or an empty string before CAD.

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
`summary` is one line such as `49.3 g · 15.6 min · 72.36 €`.

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

### tasks

The order tasks, one per part, published whole after every change.
`meeting_id` is the meeting they hang on, `live` is `true` only when every task was created in Jamie, not in the outbox.
Each item is `{id, title, assignee, due, done, part_category}`; `due` reads like `27 Oct`.
A rebuild keeps the tasks of unchanged parts with their `done` state and closes the tasks of replaced parts.

### point

`target` is a scene name.
`label` is the pointer caption.
The pointer flies to that exact name.
It does not guess from a screenshot.

### training

`status` is `queued`, `running`, `done`, `failed`, or `offline`.
`step` and `reward` are the latest curve point, or `0` when there is none.
`curve` is `[[step, reward], ...]`.
`video_url` is a backend path such as `/files/fallback/hover.mp4`, or `null` when there is no clip.
A `done` event after an `offline` tool means the fallback file was played, not that a pod finished a job.

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

## Tools

`jamie_templates`, `jamie_requirements`, `jamie_search`, `jamie_meeting`, `requirements_accept`, `ask_user`, `parts_search`, `physics_calc`, `simulate_drone`, `cad_frame`, `cad_part`, `product_brief`, `catalog_search`, `grip_calc`, `simulate_grip`, `isaac_lab_train`, `isaac_lab_status`, `isaac_sim_render`, `blender_render`, `bom_build`, `jamie_create_tasks`, `version_commit`, `ui_point_at`, `ui_draw`, `mascot_say`.

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

`cad_frame` arguments are `arm_length_mm` (center to motor shaft), `thickness_mm`, and `motor_spacing_mm` (bolt-circle diameter of the motor screws).
The 1102 mount is 6.6 mm.
With a propeller chosen, an arm whose neighbouring motors stand closer than the propeller diameter plus 4 mm is an error that names the minimum arm.
The open FreeCAD window builds first when its RPC answers; on an error or a step over 12 seconds, `freecadcmd` builds headless.
CadQuery writes the same STL, STEP, and GLB when FreeCAD is missing or the script fails.
`blender_render` runs `blender -b -P` on the current STL.
`jamie_requirements` reads the `Hardware-Anforderungen` fields first.

## Mock story

Without a key, the kickoff (webhook or first prompt) plays v1 through those tools.
The agent reads the kickoff, finds the 22000KV from last week's flight test and Lea's warning about the FunFly 4S.
It tries the FunFly anyway: the MuJoCo gust pushes it to the floor, the swap to the Lava 1S 550 passes.
A 28 mm arm lets the 40 mm propellers touch, so the frame becomes 36 mm.
v1 is 36.7 g, 11.7 min, 68.95 €.
The review "Review 1" asks for 15 minutes and says last week's motor was too loud.
Mechanic asks which flight time counts, resolves "last week's motor" to the 22000KV from the flight test, swaps to the quieter 18000KV and a 1S 1100 mAh pack.
v2 is 49.3 g, 15.6 min, 72.36 €, and the difference goes back to the review as a note.
A later prompt in the same session does not rebuild.
Reset starts the story over.
A prompt that asks for a gripper (`gripper`, `claw`, `end effector`) plays the gripper story instead.
Mechanic turns the request into checks, tries the 2.49 € SG90 first: 1.1 N per finger is a safety of 0.9×, and in MuJoCo the can slides out when the arm lifts.
The swap to the MG996R gives 6.0 N per finger and passes with 0.4 mm slip.
FreeCAD builds the gripper headless from the library template with the servo pocket sized for the MG996R (58 g PLA), Blender renders it, and the bill of materials comes to 18.65 € and 128 g.
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
Recorded fixture masses stay fixed and are identified separately from the displayed build version.
The tools `product_usd`, `isaac_test`, and `isaac_train` are documented in [Omniverse experiments](omniverse.md).

