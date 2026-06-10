# Volcengine Doubao Streaming ASR Provider

AskNow can use Volcengine's native big-model streaming speech recognition
WebSocket API for live microphone subtitles. Uploaded audio and video
transcription remain independent and continue to use the configured
`TRANSCRIPTION_PROVIDER`.

Official protocol documentation:

- <https://www.volcengine.com/docs/6561/1354869?lang=zh>

## Required credentials

Create or open a speech-recognition application in the Volcengine console and
obtain:

- App ID
- Access Token
- Resource ID for the activated streaming big-model service

These values stay in the backend environment and are never sent to the browser.

## Configuration

```powershell
$env:STREAM_PROCESSOR="volcengine"
$env:VOLCENGINE_APP_ID="your-app-id"
$env:VOLCENGINE_ACCESS_TOKEN="your-access-token"
$env:VOLCENGINE_RESOURCE_ID="volc.bigasr.sauc.duration"

cd C:\Users\qinmy\Documents\WhisperProject
.\start_demo.bat
```

The same values can be written to the repository-root `.env` file without the
PowerShell `$env:` prefix. Existing system or terminal variables take
precedence over `.env`.

The default resource ID is `volc.bigasr.sauc.duration`. If the Volcengine
console shows a different resource ID for the activated billing mode, use the
console value.

For an API-only cloud deployment:

```powershell
$env:TRANSCRIPTION_PROVIDER="api"
$env:DIARIZATION_PROVIDER="api"
$env:STREAM_PROCESSOR="volcengine"
$env:STREAM_REFINEMENT_ENABLED="false"
```

Install `backend/requirements-cloud.txt`; no local FunASR model is required.

## Optional settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `VOLCENGINE_STREAM_ENDPOINT` | `wss://openspeech.bytedance.com/api/v3/sauc/bigmodel` | Native WebSocket endpoint |
| `VOLCENGINE_LANGUAGE` | `zh-CN` | Recognition language |
| `VOLCENGINE_RECEIVE_TIMEOUT_SECONDS` | `0.15` | Non-final response collection window |
| `VOLCENGINE_FINAL_TIMEOUT_SECONDS` | `5` | Final response wait time |
| `VOLCENGINE_VAD_END_WINDOW_MS` | `800` | Silence window before an utterance becomes final |

## Runtime behavior

- The browser continues to send 16 kHz mono PCM16 chunks to AskNow.
- AskNow opens one upstream Volcengine WebSocket for each live session.
- The initial request enables punctuation, inverse text normalization, VAD,
  and utterance-level results.
- Only server-confirmed utterances are committed to the subtitle list. Repeated
  upstream revisions are deduplicated.
- Stopping the microphone sends the final audio packet and closes the upstream
  connection.
- Speaker labels remain `Speaker pending` during the live pass because a
  single mixed microphone channel cannot reliably identify participants.

If `STREAM_REFINEMENT_ENABLED=true`, AskNow still runs the configured offline
transcription and diarization pipeline after recording stops. Disable it when
the cloud deployment should not invoke an additional offline model.
