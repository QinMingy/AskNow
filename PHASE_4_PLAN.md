# Phase 4 Plan: Asynchronous Task Infrastructure

## Goal

Prepare the recorded-audio workflow for long-running processing and the future
real-time microphone phase. Transcription requests now return immediately with
a task ID while the frontend observes real processing stages.

## Architecture

```text
upload or video URL
  -> in-memory task record
  -> worker pool for upload/download preparation
  -> bounded GPU slot
  -> faster-whisper transcription progress
  -> pyannote diarization progress
  -> result retrieval
```

The task model is intentionally independent from HTTP polling. A future
WebSocket or Server-Sent Events transport can publish the same task stages
without changing the transcription pipeline.

## Task Stages

- `queued`
- `uploading`
- `downloading`
- `waiting_for_gpu`
- `transcribing`
- `diarizing`
- `completed`
- `failed`
- `cancelled`

## API

- `POST /api/tasks/transcribe`
- `POST /api/tasks/transcribe-url`
- `GET /api/tasks/{task_id}`
- `GET /api/tasks/{task_id}/result`
- `POST /api/tasks/{task_id}/cancel`

Legacy synchronous transcription endpoints remain available for compatibility.

## Completed

- [x] Add in-memory task records and retention
- [x] Add background worker pool
- [x] Bound concurrent GPU tasks
- [x] Add task progress callbacks to Whisper and diarization stages
- [x] Add cooperative cancellation between inference steps
- [x] Add task status, result, and cancellation APIs
- [x] Keep legacy synchronous APIs
- [x] Add frontend polling and real stage progress
- [x] Add frontend cancellation control
- [x] Add task state and GPU concurrency tests

## Before Real-Time Microphone Streaming

- [x] Define a streaming session schema separate from batch task records
- [x] Add WebSocket transport for audio chunks and server events
- [x] Add bounded audio chunk buffers and backpressure
- [ ] Add incremental transcript revision rules
- [ ] Decide how diarization updates revise recent speaker labels

## Operational Notes

Tasks are currently stored in memory and expire after one hour by default.
Restarting the backend clears all tasks. This is appropriate for the local
demo; persistent queues can be added later without changing the API contract.

Configuration:

```powershell
$env:TASK_WORKER_COUNT="4"
$env:GPU_TASK_CONCURRENCY="1"
$env:TASK_RETENTION_SECONDS="3600"
```
