# Mechanic's realtime voice

The voice agent is Gemini Live only: it listens, transcribes, speaks and handles interruptions.
Claude remains the engineering brain: Gemini calls the existing orchestrator to build, change and test products, then speaks about the returned measurements.
Gemini's own input and output transcription feeds chat, the logbook and the conversation note offered by **Send to Jamie**.
Reson8 is not part of the voice conversation; it only powers push-to-talk dictation.

## Configuration

For Vertex AI, enable the Vertex AI API on a billed Google Cloud project and sign in with `gcloud auth login`.
Set these variables on the backend process:

```bash
export GEMINI_LIVE_PROVIDER=vertex
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=us-central1
cd agent && uv run physical-ai-agent
```

The backend obtains a bearer token with `gcloud auth print-access-token --quiet` for every new session.
Gcloud refreshes its user credential as needed; an Application Default Credentials file is not required.
Neither the token nor a permanent API key reaches the browser.
The Vertex default is `gemini-3.8-live` in `us-central1`, the newest Live model the project lists, using the energetic, confident prebuilt voice `Fenrir`.
On 2026-10-24 a Vertex session with it connected and answered with native spoken audio in `Fenrir`.
Set `GEMINI_LIVE_MODEL` to override the model (for example `gemini-live-2.5-flash-native-audio`) and `GEMINI_LIVE_VOICE` to pick another prebuilt voice.

AI Studio is an alternative:

```bash
export GEMINI_LIVE_PROVIDER=studio
# Supply GEMINI_API_KEY securely to the backend process.
cd agent && uv run physical-ai-agent
```

The AI Studio default is `gemini-3.8-live`, selected from the authenticated models list on 2026-10-24.
AI Studio prepaid credits and Google Cloud credits are separate; an exhausted AI Studio key cannot use Cloud credits through the AI Studio endpoint.
When `GOOGLE_CLOUD_PROJECT` is set, Vertex is selected by default; otherwise the backend uses AI Studio.
Gemini Live is Mechanic's only speaking voice; there is no other voice engine and no voice setting.
Availability reports configured credentials, not an assurance of remaining quota or project access.
Mechanic speaks only inside a voice conversation the person started, to answer them, plus at most one short line when a build it started finishes; build progress stays text in the chat.
One button turns the voice agent on and off: press **Talk** in the chat input, and Mechanic greets you right away ("Hey, I'm Mechanic. What should we build today?") and then listens hands-free; the button turns into **End**, a status line says the conversation is live, and pressing **End** stops it.
The greeting is a text turn the gateway sends right after setup (`GREETING` in `gemini_live.py`), so it never shows up as something the person said; its first audio played about 2.2 s after the click on 2026-10-24.
The conversation belongs to the page, not to one input, so it keeps running when the start screen gives way to the workbench.
Push-to-talk (Settings) is an opt-in for the current page that only dictates a prompt; Mechanic answers it in text, and every load starts with the Talk button again.

## Audio and transcripts

One microphone capture produces 16 kHz, mono, signed 16-bit PCM chunks.
The browser sends each chunk only to the backend Gemini gateway.
Gemini's automatic voice detection controls conversation and barge-in.
Gemini's 24 kHz PCM response plays through Web Audio, and its level drives the mascot's lip-sync.
The header mute button silences playback while preserving transcription.

Gemini's input transcription records the person's turn, shown live in the chat input while they speak, and its output transcription records Mechanic's spoken reply.
Neither starts a second engineering prompt; only Gemini's `engineer` tool call does.
Both sides enter the existing `chat` SSE stream and logbook archive.
The backend also appends completed turns to the session's `voice_conversation.jsonl` file.
The logbook lets the user choose a timeline meeting and send the displayed conversation through the existing Jamie adapter, which retains its offline outbox fallback.

If Gemini is not configured, fails, times out, or closes the session, the voice conversation ends with a notice and nothing else listens or speaks; Mechanic answers typed messages in text.
An engineering task already started by Claude continues if the voice connection ends or Gemini cancels its pending tool response.

## WebSocket protocol

Connect to `WS /api/voice/live` on the backend.
The gateway checks the browser origin and the existing AnyBuild access token, supplied as `?access_token=...` for a gated deployment.
It permits one voice session per shared product session, and the newest one wins: a new Talk from any page ends the previous session and closes its upstream socket first.
`POST /api/reset` (a new chat) ends the voice session too.
A browser that sends no audio for 30 seconds is treated as gone and its session is released.
The upstream connection uses authentication headers, never a credential in its URL.

Browser messages:

| Message | Meaning |
| --- | --- |
| Binary frame | At most 64,000 bytes of raw 16 kHz mono PCM. Text frames are ignored. |

Gateway messages:

| Type | Fields and behavior |
| --- | --- |
| `ready` | `model`, `provider`, `voice`; microphone capture can begin. |
| `input` | `text`; accumulated Gemini input transcript, shown in the chat input while the person speaks. |
| `audio` | Base64 `data`, `sample_rate: 24000`; enqueue native PCM for playback. |
| `interrupted` | Stop queued and playing audio immediately. |
| `turn_complete` | The model finished the current response. |
| `ended` | `reason`: `replaced` (a newer Talk took over) or `reset` (a new chat began); the conversation ends without an error. |
| `error` | Generic English `message`; the conversation ends and Mechanic answers in text. Upstream error details and credentials are never forwarded. |

Gemini can invoke three server-owned tools:

- `engineer(request)` starts the existing Claude orchestrator and returns the completed action, current product snapshot and recent engineering results.
- `control_app(control, value?)` opens the Model, CAD or Simulation tab, the workbench/library/training/logbook view, the BOM, adjusts explosion from 0 to 100, or starts a test.
- `product_state()` reads actual metrics, simulation results, checks, build status and any open engineering question.

`POST /api/voice/note` accepts `{"meeting_id":"...","text":"..."}` and uses the existing Jamie note writer.
The meeting must exist on the timeline, and note text is limited to 24,000 characters.

## Validation and latency

Backend gateway, authentication, tool routing, voice and transcript tests:

```bash
cd agent && uv run --with pytest pytest tests/test_gemini_live.py tests/test_app_control.py tests/test_access.py -q
cd web && npm run build
```

Three short live trials on 2026-10-24 streamed the same English utterance through `WS /api/voice/live` at microphone pace.
The input was 16 kHz PCM, with leading and trailing silence trimmed at -40 dB.
Timing started after the final speech sample was sent and ended when the first native-audio chunk reached the client.
This includes network transit and Gemini's automatic endpoint detection; browser audio scheduling adds approximately 20 ms.

| Trial | End of speech to first audio chunk |
| --- | --- |
| 1 | 1,186 ms |
| 2 | 1,163 ms |
| 3 | 1,119 ms |

These measurements used the earlier default, Vertex `gemini-live-2.5-flash-native-audio`, `us-central1`, with `Charon`.
They measure a short conversational response, not a CAD build or simulation duration.

Provider documentation: [Vertex native audio guide](https://cloud.google.com/blog/topics/developers-practitioners/how-to-use-gemini-live-api-native-audio-in-vertex-ai), [Live WebSocket protocol](https://ai.google.dev/api/live), [gcloud access token command](https://cloud.google.com/sdk/gcloud/reference/auth/print-access-token).
