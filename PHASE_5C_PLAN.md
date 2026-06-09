# Phase 5C Plan: Browser Microphone and Live Subtitle UI

## Goal

Connect a real browser microphone to the streaming backend and render
incremental subtitles while preserving the local-first product experience.

## Audio Strategy

The project does not require a system FFmpeg installation for browser capture.
The frontend uses the Web Audio API to collect mono floating-point samples and
encodes each chunk as an independently decodable PCM WAV file.

The backend validates each WAV chunk and rebuilds the current sliding window as
one normalized PCM WAV file before faster-whisper inference.

This avoids MediaRecorder container-fragment problems where later WebM chunks
may not contain the headers needed for independent decoding.

## Completed

- [x] Add a real-time microphone input mode
- [x] Request and release browser microphone permissions
- [x] Capture mono audio through the Web Audio API
- [x] Encode independently decodable PCM WAV chunks in the browser
- [x] Normalize and combine WAV chunks on the backend
- [x] Send audio chunk metadata and binary payloads over WebSocket
- [x] Render revisable partial subtitles differently from final subtitles
- [x] Display processing, revision, elapsed time, and backpressure states
- [x] Pause outgoing audio when server backpressure is degraded or full
- [x] Send remaining tail audio when recording stops
- [x] Wait for final transcript confirmation before closing
- [x] Reuse live subtitles as understanding-assistant context

## Current Limitations

- ScriptProcessorNode is broadly supported but deprecated. A future iteration
  should move sample collection into an AudioWorklet.
- Incremental speaker diarization is not enabled. Live subtitles use
  `Unknown` until a later speaker revision stage.
- Browsers may apply echo cancellation and noise suppression differently.

## Next Step

- [ ] Replace ScriptProcessorNode with an AudioWorklet
- [ ] Add microphone device selection
- [ ] Add incremental speaker revision events
- [ ] Add reconnect and short-network-interruption recovery
- [ ] Tune window size and chunk duration with real classroom recordings
