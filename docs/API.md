# API reference

This is the index of every HTTP endpoint and every Server-Sent Event of the AnyBuild backend.
The full request and response shapes are specified once, in [events.md](events.md); each row below links to its section there.
The list was checked against the routes in `agent/src/pai_agent/app.py`, `agent/src/pai_agent/tools/browser_train.py` and `agent/src/pai_agent/tools/stress.py`, and against the event types the web client accepts (`EVENT_TYPES` in `web/src/events/types.ts`), on 2026-10-24.

The backend listens on `http://127.0.0.1:8100` (`PORT`).
It has no OpenAPI page; FastAPI's generated docs are turned off on purpose for the public deployment.

## Conventions

- All request and response bodies are JSON unless noted.
- State-changing calls without a typed body need `Content-Type: application/json`, else HTTP 415.
- One bench runs at a time: a build request while a build runs answers `status: already_running`, or HTTP 409 where noted.
- Long work never blocks the HTTP call: it answers `status: started` at once, and progress arrives on the event stream.
- **Auth:** with `ANYBUILD_ACCESS_CODE` set, every route except `GET /api/health` and `POST /api/access` needs a session token (bearer header, `anybuild_session` cookie, or `?access_token=` on URLs the browser loads itself), else HTTP 401.
  Without an access code, everything is open for local work.
- **Rate limits** (only with an access code) are per session and, at three times the limit, per IP, in a sliding hour; over the limit the answer is HTTP 429 with `Retry-After`.
  The limit class of each route is in the last column: `build` (`ANYBUILD_LIMIT_BUILDS`, 20), `speech` (300), `stt` (60), `cad` (120), `explain` (120).

## HTTP endpoints

### Session and build

| Method | Path | Purpose | Limit | Spec |
| --- | --- | --- | --- | --- |
| `GET` | `/api/health` | Status: `mode` (`claude` or `mock`), `provider` (`api`, `subscription` or `mock`), `busy`, `run` (the [run](events.md#run) status), `access` (`open` or `required`). Always public. | | [Learning mode](events.md#learning-mode) |
| `GET` | `/api/status` | Independent partner availability and NVIDIA SSH/GPU connection, including the last Isaac run. Requires the normal access session. | | [Partner status](events.md#partner-status-and-director-mode) |
| `GET` | `/api/bench` | Saved live and mock benchmark results: `{ok, runs}`; missing runs are omitted. | | [Bench](events.md#http) |
| `POST` | `/api/prompt` | Send a typed or spoken (`voice: true`) message; starts or continues a build, answers an open question, or operates the dashboard (`status: ui`). | build | [HTTP](events.md#http) |
| `POST` | `/api/sketch` | Start a new product from a photo of a hand sketch (PNG, JPEG or WebP up to 8 MB, base64 or data URL). | build | [HTTP](events.md#http) |
| `GET` | `/api/sketch/sample` | The sample phone stand sketch (PNG). | | [HTTP](events.md#http) |
| `POST` | `/api/reset` | Clear the session, chat memory and event buffer; publishes `reset`. | | [HTTP](events.md#http) |
| `GET` | `/api/events` | The Server-Sent Events stream, see [below](#server-sent-events). | | [HTTP](events.md#http) |
| `POST` | `/api/answer` | Answer Mechanic's open `question` with `{id, answer_id}`; 409 when none is open. | | [HTTP](events.md#http) |
| `POST` | `/api/run/pause` | Pause the build that runs now; it holds before its next tool call or model round, never inside one. 409 when nothing runs. | | [Pause and stop](events.md#pause-and-stop) |
| `POST` | `/api/run/resume` | Carry on a paused build from where it holds. 409 when nothing is paused. | | [Pause and stop](events.md#pause-and-stop) |
| `POST` | `/api/run/stop` | End the build at its next checkpoint and keep everything built so far; the next message continues from there. 409 when nothing runs. | | [Pause and stop](events.md#pause-and-stop) |
| `POST` | `/api/control` | Press Run test (`run:test`) or Rebuild and recheck (`run:rebuild`). | build | [HTTP](events.md#http) |

### CAD and files

| Method | Path | Purpose | Limit | Spec |
| --- | --- | --- | --- | --- |
| `POST` | `/api/cad/params` | Recompute the current part or product with new parameter values, without a model call; 400 out of limits, 409 while building. | cad | [HTTP](events.md#http) |
| `POST` | `/api/cad/open` | Open the current model in the FreeCAD app (FCStd, then STEP, then STL). | | [HTTP](events.md#http) |
| `GET` | `/files/{bucket}/{name}` | One generated file (STL, STEP, GLB, FCStd, PNG, MP4, script) of the session, or `fallback` for recorded assets. | | [Access](events.md#access) |
| `GET` | `/api/artifacts/frame.stl` | Alias: the current session STL. | | [Access](events.md#access) |
| `GET` | `/api/artifacts/fallback-training.mp4` | Alias: the offline training clip. | | [Access](events.md#access) |
| `GET` | `/api/artifacts/training.mp4` | Alias: a training video copied back from the GPU host. | | [Access](events.md#access) |

### Library, versions, history and export

| Method | Path | Purpose | Limit | Spec |
| --- | --- | --- | --- | --- |
| `GET` | `/api/library` | Code references (drone, gripper), registry reference builds and saved projects. | | [Library](events.md#library) |
| `POST` | `/api/library/{item_id}/open` | Start a fresh bench from a library item. | build | [Library](events.md#library) |
| `GET` | `/api/library/{item_id}/thumbnail` | The item's studio render (PNG). | | [Library](events.md#library) |
| `POST` | `/api/library` | Save the current product build as a project. | | [Library](events.md#library) |
| `GET` | `/api/versions` | Every version of the session. | | [Versions](events.md#versions) |
| `POST` | `/api/versions/{n}/restore` | Rebuild version `n` and commit it as a new version. | build | [Versions](events.md#versions) |
| `GET` | `/api/history` | Saved chats, newest first, and the `current` chat id. | | [Chat history](events.md#chat-history) |
| `GET` | `/api/history/{id}` | One saved chat with its chat lines. | | [Chat history](events.md#chat-history) |
| `POST` | `/api/history/{id}/open` | Reopen a saved chat on the bench: its messages, product and Claude memory; 409 while building. | | [Chat history](events.md#chat-history) |
| `GET` | `/api/export/bom.csv` | The bill of materials as CSV (UTF-8 with BOM, Excel friendly). | | [Export](events.md#export) |
| `GET` | `/api/export/bundle.zip` | CAD files, FreeCAD scripts, BOM, build guide, firmware, render and a README in one ZIP. | | [Export](events.md#export) |
| `GET` | `/api/export/order` | The order list grouped by shop, plus the print list with filament mass and cost. | | [Export](events.md#export) |

### Community

| Method | Path | Purpose | Limit | Spec |
| --- | --- | --- | --- | --- |
| `GET` | `/api/community?sort=new\|popular&q=` | The feed of published projects. | | [Community](events.md#community) |
| `GET` | `/api/community/{entry_id}` | One entry. | | [Community](events.md#community) |
| `POST` | `/api/community` | Publish the current build with title, description and author. | | [Community](events.md#community) |
| `POST` | `/api/community/{entry_id}/remix` | Open an entry on a fresh bench and keep working on it. | | [Community](events.md#community) |
| `GET` | `/api/community/{entry_id}/thumbnail` | The entry's render (PNG). | | [Community](events.md#community) |
| `GET` | `/api/community/{entry_id}/files/{name}` | One of the entry's renders or CAD files. | | [Community](events.md#community) |

### Voice

| Method | Path | Purpose | Limit | Spec |
| --- | --- | --- | --- | --- |
| `GET` | `/api/voice` | Capabilities: `gemini_live` availability (Mechanic's only voice), STT (`reson8` or `browser`), Reson8 endpoints, language, phrase list. | | [HTTP](events.md#http) |
| `POST` | `/api/voice/token` | A short-lived Reson8 token for the browser's WebSocket; 503 without `RESON8_API_KEY`. | stt | [HTTP](events.md#http) |
| `WS` | `/api/voice/live` | Server-proxied Gemini Live audio and engineering tool calls; Vertex OAuth or AI Studio, with credentials kept on the backend. | One active session; the newest replaces it | [Realtime voice](GEMINI_LIVE.md#websocket-protocol) |

### Learning mode, settings and training jobs

| Method | Path | Purpose | Limit | Spec |
| --- | --- | --- | --- | --- |
| `POST` | `/api/explain` | Explain one decision (`swap`, `part`, `requirement`, `sim`, `param`) with computed facts and a formula. | explain | [Learning mode](events.md#learning-mode) |
| `GET` | `/api/settings` | Where Claude runs (API key or local subscription), orchestrator and sub-agent models, effort levels and delegation. | | [Settings](events.md#settings) |
| `POST` | `/api/settings` | Change any of those for the next request. | | [Settings](events.md#settings) |
| `GET` | `/api/training/browser` | The latest browser training job. | | [Learning mode](events.md#learning-mode) |
| `POST` | `/api/training/{job_id}/claim` | One dashboard tab claims a queued browser training job. | | [Learning mode](events.md#learning-mode) |
| `POST` | `/api/training/{job_id}/progress` | The claiming tab reports generations and the best controller. | | [Learning mode](events.md#learning-mode) |
| `POST` | `/api/stress/{job_id}/claim` | One dashboard tab claims a queued stress test and gets the 50 seeded worlds. | | [Learning mode](events.md#learning-mode) |
| `POST` | `/api/stress/{job_id}/progress` | The claiming tab hands finished worlds back for scoring. | | [Learning mode](events.md#learning-mode) |

### Access

| Method | Path | Purpose | Limit | Spec |
| --- | --- | --- | --- | --- |
| `POST` | `/api/access` | Exchange the access code for a 24-hour session token and cookie; ten wrong codes per IP in 15 minutes are blocked. | | [Access](events.md#access) |
| `GET` | `/api/access` | 200 while the session is valid, always 200 without an access code. | | [Access](events.md#access) |

## Server-Sent Events

`GET /api/events` emits one `data: {json}` line per event, followed by a blank line, plus `: keepalive` comments every 15 seconds.
Each event has a `type`; every stream begins with `reset`, then the backlog, then `replayed`, then live events.

| Type | Meaning | Spec |
| --- | --- | --- |
| `reset` | Drop all client state; first event of every stream and every server reset. | [reset](events.md#reset) |
| `replayed` | Everything before it on this connection was backlog. | [replayed](events.md#replayed) |
| `step` | A workflow step changed status (`meeting` spec, `teile` parts, `cad`, `render`, `simulation`, `training`, `stueckliste` bill of materials). | [step](events.md#step) |
| `chat` | A user or agent utterance. | [chat](events.md#chat) |
| `tool` | A tool's connection or run status (`connected`, `running`, `ok`, `error`, `offline`). | [tool](events.md#tool) |
| `agent` | The orchestrator or a sub-agent: role, model, effort, job, status, tokens and cost. | [agent](events.md#agent) |
| `product` | Which product the bench holds (`drone`, `gripper` or a spec slug). | [product](events.md#product) |
| `sketch` | The hand sketch a build started from and what Claude read off it. | [sketch](events.md#sketch) |
| `remix` | The bench holds a remix of a community entry. | [remix](events.md#remix) |
| `requirement` | One requirement with its quote, limit, measured value and pass or fail. | [requirement](events.md#requirement) |
| `metrics` | The key numbers: weight, thrust-to-weight, flight time, price. | [metrics](events.md#metrics) |
| `part` | A bought part was chosen or considered, with its quote and warnings. | [part](events.md#part) |
| `question` | Mechanic asks the room a multiple-choice question. | [question](events.md#question) |
| `cad` | New CAD files, the parameter ranges and the assembly tree. | [cad](events.md#cad) |
| `render` | A Blender studio render. | [render](events.md#render) |
| `sim` | A MuJoCo run with its trajectory and pass or fail. | [sim](events.md#sim) |
| `training` | Controller training progress from the browser (1,024 MuJoCo simulations) or Isaac Lab. | [training](events.md#training) |
| `stress` | The 50-world stress test and its robustness score. | [stress](events.md#stress) |
| `omniverse` | An Isaac Sim test or Isaac Lab training result, live or clearly recorded. | [Omniverse results](events.md#omniverse-results) |
| `safety` | Advisory safety findings with severity, source rule, reason, fix and disclaimer. | [safety](events.md#safety) |
| `bom` | The full bill of materials with prices, price sources and weights. | [bom](events.md#bom) |
| `print` | Per-part print time, filament, cost, orientation, warnings and G-code when sliced; otherwise labelled estimates. | [print](events.md#print) |
| `build_guide` | The step-by-step build guide for the current bill of materials. | [build_guide](events.md#build_guide) |
| `firmware` | Betaflight CLI or Arduino sketch and the wiring table. | [firmware](events.md#firmware) |
| `version` | A finished build with its trigger, numbers and difference to the last version. | [version](events.md#version) |
| `mascot` | Mechanic's expression and speech bubble. | [mascot](events.md#mascot) |
| `point` | The 3D pointer flies to a scene part. | [point](events.md#point) |
| `draw` | A halo, arrow, circle or note on a scene part. | [draw](events.md#draw) |
| `ui` | Mechanic operates a dashboard control in front of the audience. | [ui](events.md#ui) |
| `explain` | One decision explained in learning mode. | [explain](events.md#explain) |
| `run` | The build on the bench is `running`, `pausing`, `paused`, `stopping` or `idle`. | [run](events.md#run) |

Scene target names, dashboard control names and the per-tool event details are in [events.md](events.md#scene-targets).
