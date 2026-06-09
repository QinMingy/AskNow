@echo off
setlocal

set "ROOT=%~dp0"
set "CONDA_EXE=%USERPROFILE%\miniforge3\Scripts\conda.exe"
set "CONDA_ENV=whisperproject"
set "ENV_PYTHON=%USERPROFILE%\miniforge3\envs\%CONDA_ENV%\python.exe"
set "BACKEND_DIR=%ROOT%backend"
set "FRONTEND_DIR=%ROOT%frontend"

echo [Classroom Assistant] Starting demo...

if not exist "%CONDA_EXE%" (
  echo [ERROR] Miniforge was not found:
  echo         %CONDA_EXE%
  echo.
  echo Install Miniforge and create the whisperproject environment first.
  pause
  exit /b 1
)

"%CONDA_EXE%" run -n "%CONDA_ENV%" python -V >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Conda environment "%CONDA_ENV%" was not found or is not usable.
  pause
  exit /b 1
)

if not exist "%ENV_PYTHON%" (
  echo [ERROR] Conda environment Python was not found:
  echo         %ENV_PYTHON%
  pause
  exit /b 1
)

if not exist "%BACKEND_DIR%\app\main.py" (
  echo [ERROR] Backend app was not found.
  pause
  exit /b 1
)

if not exist "%FRONTEND_DIR%\index.html" (
  echo [ERROR] Frontend index.html was not found.
  pause
  exit /b 1
)

echo Checking backend dependencies...
"%ENV_PYTHON%" -c "import faster_whisper, funasr, requests, yt_dlp, torch, torchaudio, pyannote.audio, uvicorn" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Backend dependencies are incomplete.
  echo Run the environment installation command before starting the demo.
  pause
  exit /b 1
)

echo Checking FunASR model configuration...
pushd "%BACKEND_DIR%"
"%ENV_PYTHON%" -c "from app.config import get_settings; from app.stream_processing import resolve_funasr_model_path; s=get_settings(); print(resolve_funasr_model_path(s.funasr_stream_model, offline_only=s.funasr_offline_only))" >nul 2>nul
set "FUNASR_CHECK=%ERRORLEVEL%"
popd
if not "%FUNASR_CHECK%"=="0" (
  echo [ERROR] The configured FunASR model path is incomplete.
  echo         Set FUNASR_STREAM_MODEL to a complete local model directory,
  echo         or use the default model alias with automatic download enabled.
  pause
  exit /b 1
)

if not defined DEEPSEEK_API_KEY if not defined ASSIST_API_KEY (
  echo [INFO] DEEPSEEK_API_KEY is not set. Transcription will work, but the default LiteLLM assist provider will not be ready.
)

if not defined HUGGINGFACE_API_KEY if not defined HF_TOKEN if not defined HUGGINGFACE_ACCESS_TOKEN (
  echo [WARNING] A Hugging Face token is not set. Pyannote cannot download its gated model.
)

echo [1/2] Starting backend at http://127.0.0.1:8010
start "Classroom Assistant Backend" /D "%BACKEND_DIR%" "%ENV_PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8010

echo [2/2] Starting frontend at http://127.0.0.1:5173
start "Classroom Assistant Frontend" /D "%FRONTEND_DIR%" "%ENV_PYTHON%" -m http.server 5173 --bind 127.0.0.1

echo.
echo Demo is starting in two terminal windows.
echo Frontend: http://127.0.0.1:5173
echo Backend:  http://127.0.0.1:8010
echo.
echo To stop both services, run stop_demo.bat.
endlocal
