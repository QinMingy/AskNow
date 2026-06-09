# Backend Logging Guide

The backend writes key runtime events to the backend terminal. Every line
contains a process ID and request ID:

```text
2026-06-09 11:30:00 | INFO | app.transcriber | process=12345 | request=a1b2c3d4 | whisper.inference.start model=small extension=.wav bytes=1048576
```

## Logged stages

- HTTP request completion, status code, and elapsed time
- Transcriber, diarizer, and assistant provider creation
- Video source selection and yt-dlp download
- FunASR local-cache selection or explicit model download start/completion/failure
- faster-whisper model loading and inference
- pyannote model loading and inference
- Speaker alignment totals
- LiteLLM and OpenAI-compatible model inference
- Rule-based and LLM assistance completion
- Exceptions at each pipeline stage

Logs include model names, provider names, durations, segment counts, speaker
counts, file sizes, and URL hosts. They do not include API keys, Hugging Face
tokens, complete transcript text, or full video URLs.

At the default `INFO` level, the backend suppresses high-frequency audio-chunk
and 600 ms streaming-inference logs, duplicate Uvicorn access logs, and noisy
third-party model-loading internals. Set `LOG_LEVEL=DEBUG` when those details
are needed for diagnosis.

Third-party libraries default to `WARNING`. Override this independently:

```powershell
$env:THIRD_PARTY_LOG_LEVEL="INFO"
```

## Log level

The default level is `INFO`. Set `LOG_LEVEL` before starting the demo:

```powershell
$env:LOG_LEVEL="DEBUG"
.\start_demo.bat
```

Useful production-like setting:

```powershell
$env:LOG_LEVEL="WARNING"
```

Clients can send an `X-Request-ID` header. If omitted, the backend generates a
short request ID and returns it in the response header.
