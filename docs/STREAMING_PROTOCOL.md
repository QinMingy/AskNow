# Streaming Session Protocol

## Create a session

```http
POST /api/stream/sessions
Content-Type: application/json

{
  "mime_type": "audio/webm;codecs=opus",
  "sample_rate": 48000,
  "channels": 1,
  "chunk_duration_ms": 1000
}
```

The response contains the session ID, status URL, and WebSocket URL.

## WebSocket audio chunk framing

Connect to:

```text
/api/stream/sessions/{session_id}/ws
```

For every audio chunk, send exactly two WebSocket frames:

1. A JSON metadata frame.
2. The matching binary audio payload.

```json
{"type":"audio_chunk","sequence":1,"duration_ms":1000}
```

The next WebSocket frame must contain the binary audio bytes. Sequences must
increase monotonically. The server rejects duplicate or older sequences.

## Server events

```json
{"type":"session_ready","session":{}}
{"type":"buffer_status","session":{}}
{"type":"backpressure","level":"warning","queued_ms":6000,"message":"..."}
{"type":"error","code":"chunk_rejected","detail":"..."}
{"type":"session_stopped","session":{}}
```

Backpressure levels:

- `normal`: the queue is below the warning threshold.
- `warning`: processing is falling behind.
- `degraded`: a future processor should reduce work or fidelity.
- `full`: the configured maximum buffered duration has been reached.

When a new chunk would exceed the maximum queue duration, the server rejects
that chunk and emits a `full` backpressure event rather than growing memory
without limit. Individual binary chunks also have a configurable byte limit.

## Control events

```json
{"type":"ping"}
{"type":"stop"}
```

`stop` closes the session cleanly. Closing the WebSocket without stopping
leaves the session available for reconnection.

Phase 5A established transport and buffering. Phase 5B adds the optional
processor and transcript events described below.

## Phase 5B processing events

When a stream processor is configured, the server consumes queued chunks in a
background worker and pushes events without requiring client polling:

```json
{"type":"processing_status","state":"processing"}
{"type":"buffer_status","session":{"queued_ms":0,"processed_ms":2000}}
{"type":"transcript_partial","revision":1,"segments":[]}
{"type":"transcript_final","revision":2,"segments":[]}
{"type":"transcript_revision","revision":3,"replace_all":true,"segments":[]}
{"type":"refinement_status","state":"processing"}
{"type":"processing_error","detail":"..."}
{"type":"refinement_error","detail":"..."}
```

Partial segments may be replaced by later revisions. Final segments are stable
within the live pass. A `transcript_revision` event is an explicit second-pass
replacement of the complete transcript; clients must replace all existing
segments when `replace_all` is true. Legacy sliding-window processors promote
stable partials to final segments; the default FunASR incremental processor
commits each newly decoded text fragment directly.

For WebSocket clients, `stop` waits for the active processing window before
emitting `session_stopped`, up to the configured stop timeout. This allows the
final transcript event to arrive before the socket closes.

## Browser microphone format

The Phase 5D frontend sends:

```text
mime_type: audio/pcm;format=s16le
channels: 1
sample rate: 16000 Hz
sample width: 16-bit
transport chunk: 200 ms
```

Every binary frame contains little-endian raw PCM16 samples. Modern browsers
collect and resample audio in an AudioWorklet using a windowed-sinc resampler;
ScriptProcessorNode remains only as a compatibility fallback. The frontend
also reports local input level, silence, and clipping without uploading extra
audio. The backend
validates the session format and keeps a separate FunASR streaming cache for
each session.

The browser sends one transport chunk at a time and waits for a `buffer_status`
acknowledgement. During backpressure, new microphone audio remains in the
browser queue instead of being discarded. The backend aggregates short
transport chunks into roughly 600 ms inference batches. Uploaded audio and
video URLs continue to use faster-whisper; only the live microphone path uses
FunASR Paraformer Streaming.

## Live speaker strategy

A single browser microphone sends one mixed mono channel. The live path must
not invent `Speaker A/B` identities from that mixed signal. FunASR live
segments therefore use `Speaker pending`, which the frontend presents as
`发言者待识别`.

The frontend groups adjacent FunASR fragments into stable display turns and
updates only the active turn. Existing subtitle nodes are preserved, so older
lines do not replay animations or force the user's scroll position to jump.

When recording stops, the backend assembles the complete PCM recording and
runs a higher-accuracy offline transcription plus the configured diarizer.
The resulting `transcript_revision` event replaces the live fragments with
revised text, timestamps, and `Speaker A/B` labels. If refinement fails, the
original live transcript remains available and a `refinement_error` is emitted.

The backend starts loading the FunASR model during FastAPI startup. If audio
arrives before warm-up completes, capture continues and the client receives a
`processing_status` event with `state: "initializing"` until inference begins.
`GET /health` also exposes `live_asr_ready` so clients can distinguish model
warm-up from microphone capture latency.

Relevant environment variables:

```text
STREAM_PROCESSOR=funasr
FUNASR_STREAM_MODEL=paraformer-zh-streaming
FUNASR_DEVICE=cuda
FUNASR_OFFLINE_ONLY=false
FUNASR_HOTWORDS=AskNow 人机共生 课堂助手
STREAM_PROCESS_INTERVAL_MS=600
STREAM_REFINEMENT_ENABLED=true
STREAM_REFINEMENT_TIMEOUT_SECONDS=600
```

The backend always prefers a complete local ModelScope cache directory. If it
is missing and `FUNASR_OFFLINE_ONLY=false` (the default), the backend logs
`funasr.model.download.start`, downloads the model once, then logs the final
local path and elapsed time before loading it. Set `FUNASR_OFFLINE_ONLY=true`
when deployment must fail instead of downloading.

`FUNASR_HOTWORDS` is optional. Set it to space-separated course terminology,
names, or acronyms to improve recognition of domain-specific words during the
live FunASR pass.

`STREAM_REFINEMENT_ENABLED=true` enables the stop-time second pass. The current
refiner reuses the project's higher-accuracy faster-whisper and Pyannote
pipeline while the live path remains FunASR-only. Set it to `false` when the
lowest possible stop latency is more important than corrected text and speaker
labels.

The WebSocket remains open while refinement runs, up to
`STREAM_REFINEMENT_TIMEOUT_SECONDS`. This timeout is separate from the normal
stream stop timeout because offline ASR and diarization can take longer for a
long classroom recording.

## Volcengine Doubao live provider

Set `STREAM_PROCESSOR=volcengine` to replace local FunASR with Volcengine's
native streaming big-model ASR. AskNow keeps its browser-facing WebSocket
protocol unchanged and maintains one upstream Volcengine WebSocket per live
session. Server-confirmed utterances are deduplicated before being committed to
the subtitle list.

See `docs/VOLCENGINE_STREAM_ASR_GUIDE.md` for credentials and configuration.
