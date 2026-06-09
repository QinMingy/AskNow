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
{"type":"processing_error","detail":"..."}
```

Partial segments may be replaced by later revisions. Final segments are stable
and must not be rewritten by clients. Legacy sliding-window processors promote
stable partials to final segments; the default FunASR incremental processor
commits each newly decoded text fragment directly.

For WebSocket clients, `stop` waits for the active processing window before
emitting `session_stopped`, up to the configured stop timeout. This allows the
final transcript event to arrive before the socket closes.

## Browser microphone format

The Phase 5C frontend sends:

```text
mime_type: audio/pcm;format=s16le
channels: 1
sample rate: 16000 Hz
sample width: 16-bit
transport chunk: 200 ms
```

Every binary frame contains little-endian raw PCM16 samples. The backend
validates the session format and keeps a separate FunASR streaming cache for
each session.

The browser sends one transport chunk at a time and waits for a `buffer_status`
acknowledgement. During backpressure, new microphone audio remains in the
browser queue instead of being discarded. The backend aggregates short
transport chunks into roughly 600 ms inference batches. Uploaded audio and
video URLs continue to use faster-whisper; only the live microphone path uses
FunASR Paraformer Streaming.

Relevant environment variables:

```text
STREAM_PROCESSOR=funasr
FUNASR_STREAM_MODEL=paraformer-zh-streaming
FUNASR_DEVICE=cuda
STREAM_PROCESS_INTERVAL_MS=600
```
