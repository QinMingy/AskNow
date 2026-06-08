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

"%CONDA_EXE%" run -n "%CONDA_ENV%" python -c "import faster_whisper, requests, yt_dlp" >nul 2>nul
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
