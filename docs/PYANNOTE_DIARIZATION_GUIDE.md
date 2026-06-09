# Pyannote Speaker Diarization Guide

This project uses two separate local model stages:

```text
audio
  -> faster-whisper: speech-to-text and timestamps
  -> pyannote/speaker-diarization-community-1: speaker time ranges
  -> overlap alignment: transcript segments with Speaker A/B labels
```

Adding pyannote does not replace or disable Whisper.

## Hugging Face access

The model is gated. Before the first run:

1. Sign in to Hugging Face.
2. Accept the conditions for:
   - `https://huggingface.co/pyannote/speaker-diarization-community-1`
3. Create a User Access Token at `https://huggingface.co/settings/tokens`.
4. A read token is sufficient. Do not grant write access.

Set the token as an environment variable:

```powershell
$env:HUGGINGFACE_API_KEY="hf_your_read_token"
.\start_demo.bat
```

The first transcription downloads the gated model into the Hugging Face cache.
Later runs use the local cache unless the model needs updating.

## Pyannote 4 GPU environment

The project uses pyannote.audio 4.x and its newer `token=` authentication API.
Pyannote 4 also requires a recent CUDA PyTorch stack and FFmpeg for TorchCodec:

```powershell
& "$env:USERPROFILE\miniforge3\Scripts\conda.exe" install `
  -n whisperproject -y -c conda-forge "ffmpeg<8"
```

The pinned Python requirements use CUDA 12.8 builds of PyTorch and torchaudio.
If the environment was upgraded from pyannote.audio 3.x, remove the obsolete
`speechbrain` package because pyannote.audio 4.x no longer uses it:

```powershell
& "$env:USERPROFILE\miniforge3\envs\whisperproject\python.exe" `
  -m pip uninstall -y speechbrain
```

Before diarization, the backend decodes uploaded or downloaded media into an
in-memory `16kHz` mono waveform. This avoids TorchCodec random-access sample
count errors on compressed M4A/MP3 files and prevents Windows temporary files
from remaining locked after inference.

## Configuration

Real speaker diarization is the default:

```powershell
$env:DIARIZATION_PROVIDER="pyannote"
$env:DIARIZATION_MODEL="pyannote/speaker-diarization-community-1"
$env:DIARIZATION_DEVICE="cuda"
$env:HUGGINGFACE_API_KEY="hf_your_read_token"
```

To explicitly use simulated Speaker A/B labels for UI development:

```powershell
$env:DIARIZATION_PROVIDER="mock"
```

The backend does not silently switch from pyannote to mock mode. If the token,
model authorization, network, or GPU environment is unavailable, it returns a
clear error instead of presenting simulated labels as real speakers.

## Environment verification

```powershell
& "$env:USERPROFILE\miniforge3\Scripts\conda.exe" run --no-capture-output `
  -n whisperproject python scripts\check_environment.py
```

The environment should report `torch CUDA`, `pyannote.audio`, and the existing
faster-whisper CUDA libraries as available. The Hugging Face token is reported separately
because it is a user secret and is not stored in the repository.
