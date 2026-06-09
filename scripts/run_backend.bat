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

if not defined DEEPSEEK_API_KEY if not defined ASSIST_API_KEY (
  echo [INFO] DEEPSEEK_API_KEY is not set. Transcription will work, but the default LiteLLM assist provider will not be ready.
  echo.
)

if not defined HUGGINGFACE_API_KEY if not defined HF_TOKEN if not defined HUGGINGFACE_ACCESS_TOKEN (
  echo [WARNING] A Hugging Face token is not set. The default pyannote speaker diarization provider cannot download its gated model.
  echo           Accept both pyannote model conditions and set HUGGINGFACE_API_KEY, or explicitly set DIARIZATION_PROVIDER=mock.
  echo.
)

"%ENV_PYTHON%" -c "import faster_whisper, requests, yt_dlp, torch, torchaudio, pyannote.audio" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Backend dependencies are incomplete.
  pause
  exit /b 1
)

"%ENV_PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8010

endlocal
