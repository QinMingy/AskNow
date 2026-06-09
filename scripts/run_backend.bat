@echo off
setlocal

set "ROOT=%~dp0.."
set "BACKEND_DIR=%ROOT%\backend"
set "CONDA_EXE=%USERPROFILE%\miniforge3\Scripts\conda.exe"
set "CONDA_ENV=whisperproject"

cd /d "%BACKEND_DIR%"
echo Backend: http://127.0.0.1:8010
echo Press Ctrl+C to stop this service.
echo.

if not defined DEEPSEEK_API_KEY if not defined ASSIST_API_KEY (
  echo [INFO] DEEPSEEK_API_KEY is not set. Transcription will work, but the default LiteLLM assist provider will not be ready.
  echo.
)

if not defined HF_TOKEN if not defined HUGGINGFACE_ACCESS_TOKEN (
  echo [WARNING] HF_TOKEN is not set. The default pyannote speaker diarization provider cannot download its gated model.
  echo           Accept both pyannote model conditions and set HF_TOKEN, or explicitly set DIARIZATION_PROVIDER=mock.
  echo.
)

"%CONDA_EXE%" run -n "%CONDA_ENV%" python -c "import faster_whisper, requests, yt_dlp, torch, torchaudio, pyannote.audio" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Backend dependencies are incomplete.
  echo Repairing dependencies from requirements.txt...
  "%CONDA_EXE%" run --no-capture-output -n "%CONDA_ENV%" python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] Dependency repair failed.
    pause
    exit /b 1
  )
)

"%CONDA_EXE%" run --no-capture-output -n "%CONDA_ENV%" python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8010

endlocal
