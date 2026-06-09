# Phase 5A Plan: Streaming Session Foundation

## Goal

Build the transport and lifecycle foundation needed before connecting browser
microphone capture or incremental Whisper inference.

This phase deliberately does not transcribe incoming chunks. It validates the
session protocol, bounded buffering, backpressure signals, ordering rules, and
cleanup behavior independently from GPU inference.

## Architecture

```text
client
  -> create stream session over HTTP
  -> connect WebSocket
  -> send audio_chunk metadata JSON
  -> send matching binary audio frame
  -> bounded in-memory audio queue
  -> buffer status and backpressure events
```

## Completed

- [x] Define a stream session model separate from batch tasks
- [x] Add stream session creation, status, stop, and cancel APIs
- [x] Add WebSocket connection and control events
- [x] Accept binary audio chunks without Base64 encoding
- [x] Enforce monotonically increasing chunk sequences
- [x] Add a bounded audio queue
- [x] Reject chunks when the queue is full
- [x] Report normal, warning, degraded, and full backpressure levels
- [x] Add disconnect and backend-shutdown lifecycle handling
- [x] Add automated protocol and buffer tests

## Next Step: Phase 5B

- [ ] Add a stream processing worker that consumes queued chunks
- [ ] Extract a shared GPU scheduler for batch and stream processing
- [ ] Normalize browser audio chunks into a stable PCM format
- [ ] Implement sliding-window incremental transcription
- [ ] Define partial and final transcript revision events
- [ ] Add transcript stability and finalization rules

## Configuration

```powershell
$env:STREAM_BUFFER_MAX_MS="30000"
$env:STREAM_CHUNK_MAX_BYTES="5242880"
$env:STREAM_BACKPRESSURE_WARNING_MS="5000"
$env:STREAM_BACKPRESSURE_DEGRADED_MS="15000"
$env:STREAM_SESSION_RETENTION_SECONDS="3600"
```
