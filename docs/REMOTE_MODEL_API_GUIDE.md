# Remote Model API Provider Guide

The application backend can remain lightweight and call separately deployed
GPU model services. The browser API and frontend do not change.

## API-only cloud configuration

Install only the cloud dependencies:

```powershell
pip install -r backend/requirements-cloud.txt
```

Configure all heavyweight model calls as remote:

```powershell
$env:MODEL_API_BASE_URL="https://models.example.com"
$env:MODEL_API_KEY="..."

$env:TRANSCRIPTION_PROVIDER="api"
$env:DIARIZATION_PROVIDER="api"
$env:STREAM_PROCESSOR="api"
```

The API keys stay in the backend environment and are never sent to the
browser. Each provider can use a different service and key.

## Mixed deployments

Providers are independent. For example, keep live FunASR local but move
offline transcription and diarization to APIs:

```powershell
$env:TRANSCRIPTION_PROVIDER="api"
$env:DIARIZATION_PROVIDER="api"
$env:STREAM_PROCESSOR="funasr"
```

Use `DIARIZATION_PROVIDER=passthrough` when the transcription API already
returns final speaker labels.

## Required remote contracts

All endpoints use an optional `Authorization: Bearer <key>` header.

### Offline transcription

```http
POST {TRANSCRIPTION_API_BASE_URL}/v1/audio/transcriptions
Content-Type: multipart/form-data

file=<audio bytes>
```

Response:

```json
{
  "language": "zh",
  "duration": 12.4,
  "segments": [
    {
      "id": 1,
      "start": 0.0,
      "end": 2.1,
      "speaker": "Unknown",
      "text": "这里是字幕。"
    }
  ]
}
```

### Speaker diarization

```http
POST {DIARIZATION_API_BASE_URL}/v1/audio/diarizations
Content-Type: multipart/form-data

file=<audio bytes>
segments=<JSON string containing transcript segments>
```

Response:

```json
{"segments": [{"id": 1, "start": 0.0, "end": 2.1, "speaker": "Speaker A", "text": "这里是字幕。"}]}
```

### Live streaming ASR

The application sends each acknowledged PCM16 inference batch:

```http
POST {STREAM_API_BASE_URL}/v1/audio/stream-transcriptions
Content-Type: multipart/form-data

file=<raw PCM16 bytes>
session_id=<stable remote session id>
mime_type=audio/pcm;format=s16le
sample_rate=16000
channels=1
window_start_ms=0
is_final=false
```

Response:

```json
{"segments": [{"id": 1, "start": 0.0, "end": 0.6, "speaker": "Speaker pending", "text": "实时字幕"}]}
```

The remote streaming service is responsible for retaining model cache by
`session_id`.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `MODEL_API_BASE_URL` | empty | Shared fallback URL for all model APIs |
| `MODEL_API_KEY` | empty | Shared fallback bearer token |
| `TRANSCRIPTION_PROVIDER` | `local` | `local` or `api` |
| `TRANSCRIPTION_API_BASE_URL` | empty | Offline ASR service |
| `TRANSCRIPTION_API_KEY` | empty | Offline ASR bearer token |
| `TRANSCRIPTION_API_TIMEOUT_SECONDS` | `600` | Offline ASR timeout |
| `DIARIZATION_PROVIDER` | `pyannote` | `pyannote`, `api`, or `passthrough` |
| `DIARIZATION_API_BASE_URL` | empty | Diarization service |
| `DIARIZATION_API_KEY` | empty | Diarization bearer token |
| `DIARIZATION_API_TIMEOUT_SECONDS` | `600` | Diarization timeout |
| `STREAM_PROCESSOR` | `funasr` | `funasr`, `api`, or `off` |
| `STREAM_API_BASE_URL` | empty | Live ASR service |
| `STREAM_API_KEY` | empty | Live ASR bearer token |
| `STREAM_API_TIMEOUT_SECONDS` | `120` | Per-batch live ASR timeout |
