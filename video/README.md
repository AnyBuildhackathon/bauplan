# AnyBuild demo film

Sources for the 2-minute submission video of AnyBuild.
Clips, voice files and renders stay out of git; the rendered films are uploaded to the team's Google Drive folder as new versioned files (`AnyBuild-demo-v3-16x9.mp4`, never overwritten).

## Story

The film follows two references that were studied shot by shot before production.
The arc comes from NVIDIA's GTC Berlin 2026 agent demo: one request, the agent plans, real tools work one after another, the scale-out moment, the result.
The demo style comes from the Teamble launch film: word-by-word headlines with one accent word, cuts on the music's bar grid every 2-4 seconds, real UI in floating windows that fly in tilted in 3D, and a kicker that names each step.

| Time | Shot | Voice |
|---|---|---|
| 0:00 | "Every product starts as a conversation." | Narrator |
| 0:07 | AnyBuild logo, "Designed. Tested. Priced." | Narrator |
| 0:15 | Mechanic: "You talk. I build." | Mechanic |
| 0:18 | It listens: a Jamie meeting ends, requirements arrive with quotes, an old warning resurfaces | Narrator |
| 0:32 | It plans: Claude Opus splits the work across Sonnet sub-agents | Narrator |
| 0:40 | It tests: MuJoCo gust test, run 1 sinks, run 2 holds | Narrator, Mechanic |
| 0:50 | It builds: FreeCAD frame, Blender render | Narrator |
| 0:59 | The review changes the plan, Mechanic asks about the contradiction, version 2 | Narrator, Mechanic |
| 1:16 | It learns: 1,024 MuJoCo simulations train the controller in the browser | Narrator |
| 1:28 | It ships: priced bill of materials with shop links | Narrator |
| 1:36 | Not just drones: Claude builds a phone stand from scratch, live, then the product library | Narrator |
| 1:58 | Under the hood, then the end card | Narrator |

## Footage

Every product shot is a screen recording of the real app at 1920x1080, made with Playwright:

- `tools/capture.mjs` records the drone story on a backend in mock mode, started by the real Jamie webhook payloads in `agent/data/webhooks/`.
- `tools/capture-live.mjs` records a live build on a backend with real API keys: the phone stand is designed, tested and priced by Claude on camera.

## Build

```bash
node video/tools/capture.mjs <work>/../v2/capm                 # drone story (mock backend on API, web on WEB)
node video/tools/capture-live.mjs <work>/live "<prompt>"       # live Claude build
node video/v3/cards.mjs <work>                                 # type cards and kickers as PNG
python3 video/v3/build.py <work>                               # ffmpeg cut, voice and music mix (audio.wav, fallback film)
RAW=1 python3 video/v3/build.py <work>                         # zoomed app clips for HyperFrames
node video/v3/hf.mjs <work>                                    # HyperFrames composition in <work>/hf
npx hyperframes@0.8.168 render <work>/hf -o AnyBuild-demo-v3-16x9.mp4 --video-frame-format png
```

`<work>` holds `png/`, `vo/` (one ElevenLabs file per line: copy `v3/lines.json` and `v3/kickers.json` into `<work>`, then `python3 video/v3/vo.py <work>`), `live/`, `kickers.json`, and `../brand` and `../music` next to it.

## Voices and music

- Narrator: ElevenLabs "Sarah", model `eleven_multilingual_v2`.
- Mechanic: ElevenLabs "Roger"; the app's own Gemini Live voice only runs inside a live microphone conversation.
- Music: "The Complex" Kevin MacLeod (incompetech.com), licensed under Creative Commons: By Attribution 4.0 License, http://creativecommons.org/licenses/by/4.0/
