# Phase 6 Plan: Cloud API Model Providers

## Goal

Allow every heavyweight local-model boundary to use a remote HTTP model
service while preserving the existing browser UI and application API.

## Completed

- [x] Add `local` / `api` provider choice for offline transcription
- [x] Add `pyannote` / `api` / `passthrough` choice for speaker diarization
- [x] Add `funasr` / `api` choice for live streaming ASR
- [x] Reuse selected providers during stop-time transcript refinement
- [x] Add bearer-token support and configurable API timeouts
- [x] Keep unified transcript and speaker schemas across providers
- [x] Skip unused heavyweight dependency checks in API-only mode
- [x] Add lightweight cloud requirements without local model runtimes
- [x] Add contract tests for remote model requests

## Next

- [ ] Add provider readiness checks to `/health`
- [ ] Add retry, circuit breaker, and per-provider concurrency limits
- [ ] Add optional signed requests and secret-manager integration
- [ ] Provide reference model-service deployments for ASR and diarization
- [ ] Add cloud object-storage handoff for very large recordings
