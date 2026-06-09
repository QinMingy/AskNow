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

Phase 5A stores chunks only in memory. It does not yet run Whisper or emit
transcript events.
