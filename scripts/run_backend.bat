@echo off
setlocal
title Classroom Assistant Backend

set "ROOT=%~dp0.."
set "BACKEND_DIR=%ROOT%\backend"
set "CONDA_EXE=%USERPROFILE%\miniforge3\Scripts\conda.exe"
set "CONDA_ENV=whisperproject"
set "ENV_PYTHON=%USERPROFILE%\miniforge3\envs\%CONDA_ENV%\python.exe"

cd /d "%BACKEND_DIR%"
echo Backend: http://127.0.0.1:8010
echo Press Ctrl+C to stop this service.
echo.

"%ENV_PYTHON%" -c "from app.config import get_settings; s=get_settings(); print('[INFO] DeepSeek/assist API key is not set. Transcription will work, but LiteLLM assist is not ready.' if not s.assist_api_key else ''); print('[WARNING] A Hugging Face token is not set. Pyannote cannot download its gated model.' if s.diarization_provider.lower() == 'pyannote' and not s.huggingface_token else '')"

"%ENV_PYTHON%" -c "import faster_whisper, requests, yt_dlp, torch, torchaudio, pyannote.audio" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Backend dependencies are incomplete.
  pause
  exit /b 1
)

"%ENV_PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8010

endlocal
