# Phase 5D Plan: Browser Audio Quality and Capture Stability

## Goal

Improve live Chinese subtitle accuracy before further model tuning by making
browser microphone capture observable, configurable, and less dependent on the
UI main thread.

## Completed

- [x] Prefer AudioWorklet for microphone sample collection
- [x] Keep ScriptProcessorNode as a compatibility fallback
- [x] Move 200 ms chunking and resampling into the audio rendering thread
- [x] Replace averaging downsampling with windowed-sinc resampling
- [x] Add microphone device selection
- [x] Add echo cancellation, noise suppression, and automatic gain controls
- [x] Add local RMS, peak, silence, low-volume, and clipping feedback
- [x] Flush remaining AudioWorklet samples when recording stops
- [x] Preserve the existing PCM16 WebSocket protocol

## Next

- [ ] Add short-disconnect WebSocket reconnection and acknowledged-chunk replay
- [ ] Calibrate quality thresholds with real classroom microphones
- [ ] Compare browser processing options against a fixed Chinese evaluation set
- [ ] Add periodic offline subtitle and speaker revisions during long sessions
