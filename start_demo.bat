@echo off
setlocal

set "ROOT=%~dp0"
set "CONDA_EXE=%USERPROFILE%\miniforge3\Scripts\conda.exe"
set "CONDA_ENV=whisperproject"
set "BACKEND_DIR=%ROOT%backend"
set "FRONTEND_DIR=%ROOT%frontend"
set "BACKEND_RUNNER=%ROOT%scripts\run_backend.bat"
set "FRONTEND_RUNNER=%ROOT%scripts\run_frontend.bat"

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

echo [1/2] Starting backend at http://127.0.0.1:8010
start "Classroom Assistant Backend" cmd /k call "%BACKEND_RUNNER%"

echo [2/2] Starting frontend at http://127.0.0.1:5173
start "Classroom Assistant Frontend" cmd /k call "%FRONTEND_RUNNER%"

echo.
echo Demo is starting in two terminal windows.
echo Frontend: http://127.0.0.1:5173
echo Backend:  http://127.0.0.1:8010
echo.
echo To stop both services, run stop_demo.bat.
endlocal
