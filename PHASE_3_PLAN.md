# Phase 3 Plan: Real Speaker Diarization

## Goal

Replace simulated Speaker A/B labels with local GPU speaker diarization while
preserving faster-whisper as the transcription engine.

## Architecture

```text
audio -> faster-whisper transcript segments
      -> pyannote community-1 speaker turns
      -> maximum-overlap alignment
      -> transcript segments with normalized Speaker A/B labels
```

The diarization provider is replaceable. `pyannote` is the real provider and
`mock` remains available only as an explicit UI-development fallback.

## TODO

- [x] Install GPU PyTorch and torchaudio
- [x] Install `pyannote.audio`
- [x] Add a replaceable `Diarizer` interface
- [x] Add pyannote and mock providers
- [x] Align speaker turns with Whisper timestamps
- [x] Add diarization configuration
- [x] Add environment diagnostics
- [x] Add unit tests
- [x] Document Hugging Face authorization and Token usage
- [ ] Set `HUGGINGFACE_API_KEY` locally
- [ ] Download gated model on first transcription
- [ ] Validate with a real multi-speaker recording

## Acceptance Criteria

- Whisper continues to produce transcript text and timestamps.
- Pyannote assigns real speaker labels using the local GPU.
- Missing authorization produces a clear error and never silently uses fake
  labels.
- The provider can be changed without modifying the transcription API.
