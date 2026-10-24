# Physical AI Agent

Lokales Werk für die Drohnen-Demo.
Der Agent in `agent/` entscheidet die Schritte, das Dashboard in `web/` zeigt sie.
Der Vertrag zwischen beiden steht in `docs/events.md`.

## Start

Backend, ein Befehl, danach `http://127.0.0.1:8100`:

```bash
cd agent && uv run physical-ai-agent
```

`uv` holt Python 3.12 und die Abhängigkeiten beim ersten Lauf.
Das Dashboard ist die Vite-App in `web/` und soll auf `http://127.0.0.1:5180` hören:

```bash
cd web && npm install && npm run dev
```

Wenn das Script den Port nicht selbst setzt:

```bash
cd web && npm run dev -- --port 5180 --host 127.0.0.1
```

## Mock

Ohne `ANTHROPIC_API_KEY` spielt der Mock die ganze Geschichte durch dieselben Werkzeuge, die Claude benutzt.
Das Kickoff baut v1: Vorgaben aus Jamie, Warnung vor dem FunFly 4S, ein Lauf, den die Böe in MuJoCo auf den Boden drückt, Tausch auf den Lava 1S 550, Rahmen in FreeCAD, Render in Blender, Stückliste, Aufgaben, Version an das Meeting.
Das Review baut v2: Bolzen fragt bei Widersprüchen nach, löst „den Motor von letzter Woche“ über Jamie auf, tauscht Motor und Akku und schreibt die Differenz als Notiz zurück.
Ein weiterer Prompt in derselben Sitzung baut nicht neu.
`POST /api/reset` fängt von vorn an.
`PAI_FORCE_MOCK=1` erzwingt den Mock auch dann, wenn ein Key gesetzt ist.

Beide Läufe starten über den Jamie-Webhook, sobald ein Meeting endet:

```bash
curl -s -X POST http://127.0.0.1:8100/api/webhooks/jamie \
  -H 'content-type: application/json' \
  --data @agent/data/webhooks/meeting-ended.json
curl -s -X POST http://127.0.0.1:8100/api/webhooks/jamie \
  -H 'content-type: application/json' \
  --data @agent/data/webhooks/review-ended.json
```

`meeting.started` setzt ein Meeting auf der Zeitleiste auf live und baut nichts.
Ohne Webhook startet und beendet der Knopf neben dem nächsten Review in der Zeitleiste dasselbe.
Andere Ereignisse antworten mit `status: ignored` und starten nichts.

## Jamie

Jamie ist das Rückgrat: Jede Version hängt an dem Meeting, aus dem sie kommt, und jedes Teil an dem Satz, der es begründet.
`jamie_templates` legt die Vorlagen `Hardware-Anforderungen` und `Drohnen-Review` selbst an.
`jamie_requirements` liest zuerst die Felder der Vorlage `Hardware-Anforderungen`, jedes mit Zitat, Person und Uhrzeit, dann die Liste am Meeting, dann Sätze im Transkript.
Beim Wählen eines Teils kommen Warnungen aus früheren Meetings mit, etwa Leas Werkstattnotiz zum FunFly.
`jamie_meeting` liest ein Review: geänderte Vorgaben, Widersprüche zu früheren Meetings und Beschwerden über Teile, „letzte Woche“ aufgelöst auf das Meeting 4 bis 10 Tage davor.
`version_commit` schreibt die Differenz als Notiz zurück und taggt das Meeting mit `drohne` und `drohne-v{n}`.
`jamie_create_tasks` legt pro Teil eine Aufgabe mit Person und Fälligkeit an; „bestellt“ in der Stückliste hakt sie bei Jamie ab.

Mit `JAMIE_MCP_TOKEN` gehen die Aufrufe live an `https://mcp.meetjamie.ai/mcp` (Streamable HTTP, Bearer-Token).
Ohne Token, oder wenn ein Live-Aufruf scheitert, laufen dieselben Schritte über die Beispiel-Meetings in `agent/data/meetings/` und die Outbox `jamie_outbox.json` der Sitzung.
Die Oberfläche sieht in beiden Fällen gleich aus; die Jamie-Karten im Chat sagen „lokale Outbox“, wenn nichts live ging.

## Rahmen und Render

`cad_frame` sucht `freecadcmd` zuerst unter `/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd`.
Das Skript `agent/freecad/frame_build.py` schreibt STL, STEP, GLB und `frame.FCStd`.
Fehlt FreeCAD oder scheitert das Skript, baut CadQuery dieselben Dateien.
`POST /api/cad/params` rechnet mit einem Maß neu, `POST /api/cad/open` öffnet das Teil in der FreeCAD-App.
Dateien liegen unter `/files/{sitzung}/`.

Läuft die FreeCAD-Oberfläche mit dem Add-on [freecad-mcp](https://github.com/neka-nat/freecad-mcp) und seinem RPC-Server auf `127.0.0.1:9875`, baut `cad_frame` den Rahmen sichtbar im offenen Fenster: Nabe, vier Arme mit Motorauflagen, Bohrungen, Schritt für Schritt, dann Speichern, STL- und STEP-Export und ein Bild der Ansicht (`view_png_url`).
Der Chat zeigt jeden Schritt als „FreeCAD: Arm 2 von 4“.
Antwortet das Fenster nicht oder hängt ein Schritt länger als 12 Sekunden, baut derselbe Lauf headless mit `freecadcmd` weiter, danach mit CadQuery.
`FREECAD_GUI=launch` öffnet FreeCAD selbst, wenn das Fenster fehlt, `FREECAD_GUI=off` bleibt immer headless.

Das Add-on wird von hier nicht installiert. Einmalig, FreeCAD 1.1:

```bash
git clone https://github.com/neka-nat/freecad-mcp.git
mkdir -p "$HOME/Library/Application Support/FreeCAD/v1-1/Mod"
cp -R freecad-mcp/addon/FreeCADMCP "$HOME/Library/Application Support/FreeCAD/v1-1/Mod/FreeCADMCP"
```

Danach in FreeCAD die Workbench `MCP Addon` öffnen und `Toggle Auto Start` wählen; der RPC-Server startet dann mit jeder FreeCAD-Oberfläche und bleibt auf localhost.

`blender_render` sucht Blender zuerst unter `/Applications/Blender.app/Contents/MacOS/Blender` und rendert die ganze Drohne headless im Studio: das echte Rahmen-STL, dazu Motoren, Propeller, Flugregler und der gewählte Akku in echter Größe, auf einer Hohlkehle mit Softboxen (EEVEE, 1600 × 900, eine Datei pro Version):

```bash
blender -b -P agent/blender/studio.py -- frame.stl studio-v1.png assembly.json
```

`assembly.json` nennt `arm_mm`, `thickness_mm`, `prop_mm` und `battery_mm` (Länge, Breite, Höhe); ohne die Datei gelten die Maße von v1.

Ohne Blender bleibt das Werkzeug `offline` und das Ereignis `render` zeigt `agent/runs/fallback/render.png`.

## Stimme

Im Chat hält man die Leertaste oder den Mikrofonknopf und spricht mit Bolzen, auch um seine Rückfragen zu beantworten („fünfzehn“, „ja, passt“).
Mit `RESON8_API_KEY` hört [Reson8](https://docs.reson8.dev) in Echtzeit zu: Das Backend holt pro Aufnahme ein kurzlebiges Token (`POST /api/voice/token`), der Browser streamt 16-kHz-PCM an `wss://api.reson8.dev/v1/speech-to-text/realtime`.
Der Schlüssel verlässt das Backend nie.
Ohne Schlüssel nimmt der Browser seine eigene Spracherkennung, und wo es die nicht gibt, bleibt Tippen.
Bolzen spricht seine Sätze mit der Sprachausgabe des Browsers, mit `ELEVENLABS_API_KEY` über ElevenLabs.
Der Lautsprecher oben im Chat schaltet ihn stumm; `?mute` startet stumm.

## Umgebung

Lege Geheimnisse in `agent/.env` oder in die Shell.
Die Datei wird nicht committet.
Vorhandene Variablen gewinnen gegen die Datei.

| Variable | Bedeutung |
| --- | --- |
| `ANTHROPIC_API_KEY` | Leer lassen für den Mock. Nie ins Repo schreiben. |
| `ANTHROPIC_MODEL` | Standard `claude-sonnet-5-5`. |
| `PAI_FORCE_MOCK` | `1` erzwingt den Mock. |
| `DEMO_PACE_S` | Pause zwischen den Schlägen. Standard `0`. |
| `PORT` | Backend-Port. Standard `8100`. |
| `JAMIE_MCP_TOKEN` | OAuth-Token für den Jamie-MCP-Server. Leer lassen für die lokalen Meetings und die Outbox. |
| `JAMIE_MCP_URL` | Standard `https://mcp.meetjamie.ai/mcp`. |
| `JAMIE_WEBHOOK_SECRET` | Gesetzt braucht der Webhook diesen Wert in `X-Jamie-Secret` oder `?secret=`. Setzen, sobald ein Tunnel auf das Backend zeigt. |
| `RESON8_API_KEY` | Reson8 für die Spracheingabe. Leer lassen für die Spracherkennung des Browsers. |
| `RESON8_LANGUAGE` | Standard `de`. |
| `ELEVENLABS_API_KEY` | Bolzens Stimme über ElevenLabs. Leer lassen für die Stimme des Browsers. |
| `ELEVENLABS_VOICE_ID` | Optional, eine Stimme mit Deutsch. |
| `FREECAD_GUI` | `auto` (Standard) baut im offenen FreeCAD-Fenster, `launch` öffnet es vorher, `off` bleibt headless. |
| `FREECAD_MCP_URL` | Standard `http://127.0.0.1:9875`. |
| `PAI_ASK_TIMEOUT_S` | Wie lange Bolzen auf eine Antwort wartet, bevor der Vorschlag gilt. Standard `20`. |
| `RUNPOD_SSH_HOST` | Leer lassen, dann bleibt Isaac offline und der Fallback läuft. |
| `RUNPOD_SSH_PORT` | Standard `22`. |
| `RUNPOD_SSH_USER` | Standard `root`. |
| `RUNPOD_SSH_KEY` | Pfad zum privaten Schlüssel. |

## RunPod

Isaac Sim und Isaac Lab laufen auf einem RTX-4090-Pod, nicht auf dem Mac.
Die Installations- und Smoke-Schritte stehen in `runpod/setup.sh`.
Das Script startet nur mit `RUN_ON_POD=1` und wird von hier nicht ausgeführt.
Ohne Host spielt `isaac_lab_train` die Kurve aus `agent/runs/fallback/training.json`.
Eine echte Aufnahme ersetzt diese Datei und, wenn vorhanden, `agent/runs/fallback/hover.mp4`.

## Kurzer Check

```bash
cd agent && uv run python scripts/smoke_sse.py
```

Der Check startet einen eigenen Server auf Port 8101 (`SMOKE_PORT`), zwingt den Mock an und liest Kickoff und Review einmal über SSE durch.

## Demo-Aufnahme

`?demo` im Dashboard spielt einen echten Mock-Lauf ab, damit jede Zahl die des Backends ist.
Nach Änderungen an Geschichte, Katalog oder Physik neu aufnehmen:

```bash
cd agent && uv run python scripts/record_demo.py
```

Das schreibt `web/src/events/recording.json` und kopiert Rahmen und Renders nach `web/public/demo/run/`.
