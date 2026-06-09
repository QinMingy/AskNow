# Phase 5B Plan: Incremental Stream Processing

## Goal

Consume buffered stream audio in background workers and publish revisable
partial transcripts plus stable final transcripts over the existing WebSocket
session.

## Architecture

```text
audio chunks
  -> bounded session queue
  -> stream worker
  -> shared GPU scheduler
  -> sliding audio window
  -> stream processor
  -> transcript revision tracker
  -> partial/final WebSocket events
```

Batch tasks and stream workers share the same GPU scheduler. With the default
concurrency of one, recorded-audio transcription and incremental streaming
cannot accidentally run GPU inference at the same time.

## Completed

- [x] Extract a shared GPU scheduler
- [x] Add background stream-consumption workers
- [x] Maintain a bounded sliding audio history window
- [x] Add a replaceable stream processor interface
- [x] Add a faster-whisper stream processor
- [x] Skip pyannote during incremental inference to reduce latency
- [x] Publish processing and post-consumption buffer events
- [x] Publish partial and final transcript events
- [x] Finalize segments after a time delay or stable repeated revisions
- [x] Finalize remaining partial segments when a session stops
- [x] Wait for the active processing window before closing a WebSocket session
- [x] Add worker, revision, GPU scheduler, and WebSocket push tests

## Current Limitation

The Whisper processor concatenates incoming encoded chunks into the current
sliding window. Before enabling the browser microphone UI, Phase 5C must verify
the chosen browser codec and normalize it into a reliably decodable format.

## Next Step: Phase 5C

- [ ] Add browser microphone capture and device permission states
- [ ] Verify MediaRecorder codec support
- [x] Normalize incoming browser audio to stable PCM/WAV windows
- [x] Render partial and final subtitles differently
- [x] Display latency and backpressure states
- [x] Define graceful stop behavior while the final GPU window is processing

## Configuration

```powershell
$env:STREAM_PROCESSOR="whisper"
$env:STREAM_WINDOW_MS="20000"
$env:STREAM_FINALIZE_DELAY_MS="8000"
$env:STREAM_STABLE_REVISIONS="2"
$env:STREAM_WORKER_COUNT="2"
$env:STREAM_STOP_TIMEOUT_SECONDS="30"
```
