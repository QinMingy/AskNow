# Asynchronous Transcription Task API

## Create a file task

```http
POST /api/tasks/transcribe
Content-Type: multipart/form-data
```

## Create a video URL task

```http
POST /api/tasks/transcribe-url
Content-Type: application/json

{"url":"https://example.com/video","browser":null}
```

Both endpoints return HTTP `202`:

```json
{
  "task_id": "abc123",
  "status_url": "/api/tasks/abc123",
  "result_url": "/api/tasks/abc123/result"
}
```

Poll the status URL until the stage is `completed`, `failed`, or `cancelled`.
Then retrieve the result URL. A result request made before completion returns
HTTP `409`.

Cancellation is cooperative:

```http
POST /api/tasks/abc123/cancel
```

A queued task can be cancelled immediately. A running model inference stops at
the next safe cancellation checkpoint. The backend never terminates a GPU
kernel or worker thread forcibly.
