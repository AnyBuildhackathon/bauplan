# Mechanic's realtime voice

Gemini Live handles speech-to-speech conversation and interruptions.
Claude remains the engineering brain: Gemini calls the existing orchestrator to build, change and test products, then speaks about the returned measurements.
Reson8 independently transcribes the same microphone stream with the existing engineering phrase list.
Its transcript feeds chat, the logbook and the conversation note offered by **Send to Jamie**.

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
Press **Talk** in the chat input to start the conversation; the button turns into **End**, a status line says the conversation is live, and pressing **End** stops it.
Push-to-talk (Settings) only dictates a prompt; Mechanic answers it in text.

## Audio and transcripts

One microphone capture produces 16 kHz, mono, signed 16-bit PCM chunks.
The browser sends each chunk to both the backend Gemini gateway and Reson8 Turns.
Gemini's automatic voice detection controls conversation and barge-in.
Gemini's 24 kHz PCM response plays through Web Audio, and its level drives the mascot's lip-sync.
The header mute button silences playback while preserving transcription.

Reson8's final turn text is recorded without sending another engineering prompt.
Gemini's output transcription records Mechanic's spoken reply.
When Reson8 is unavailable or disconnects, Gemini's input transcription becomes the transcript source and the UI displays a notice.
Both sides enter the existing `chat` SSE stream and logbook archive.
The backend also appends completed turns to the session's `voice_conversation.jsonl` file.
The logbook lets the user choose a timeline meeting and send the displayed conversation through the existing Jamie adapter, which retains its offline outbox fallback.

If Gemini is not configured, fails, times out, or closes the session, Mechanic does not switch to another voice: the microphone keeps dictating through Reson8 or the browser, and Mechanic answers in text captions.
An engineering task already started by Claude continues if the voice connection ends or Gemini cancels its pending tool response.

## WebSocket protocol

Connect to `WS /api/voice/live` on the backend.
The gateway checks the browser origin and the existing AnyBuild access token, supplied as `?access_token=...` for a gated deployment.
It permits one voice session per shared product session.
The upstream connection uses authentication headers, never a credential in its URL.

Browser messages:

| Message | Meaning |
| --- | --- |
| Binary frame | At most 64,000 bytes of raw 16 kHz mono PCM. |
| `{"type":"transcriber","source":"reson8"}` | Reson8 is providing the user transcript. |
| `{"type":"transcriber","source":"gemini"}` | Resume the Gemini input-transcription fallback. |
| `{"type":"transcript","text":"Make it lighter"}` | Completed Reson8 user turn; log it without starting a second build. |

Gateway messages:

| Type | Fields and behavior |
| --- | --- |
| `ready` | `model`, `provider`, `voice`; microphone capture can begin. |
| `input` | `text`; accumulated Gemini input transcript, displayed when Reson8 is unavailable. |
| `audio` | Base64 `data`, `sample_rate: 24000`; enqueue native PCM for playback. |
| `interrupted` | Stop queued and playing audio immediately. |
| `turn_complete` | The model finished the current response. |
| `error` | Generic English `message`; switch to the legacy voice loop. Upstream error details and credentials are never forwarded. |

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
