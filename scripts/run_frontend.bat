@echo off
setlocal
title Classroom Assistant Frontend

set "ROOT=%~dp0.."
set "FRONTEND_DIR=%ROOT%\frontend"
set "CONDA_EXE=%USERPROFILE%\miniforge3\Scripts\conda.exe"
set "CONDA_ENV=whisperproject"

cd /d "%FRONTEND_DIR%"
echo Frontend: http://127.0.0.1:5173
echo Press Ctrl+C to stop this service.
echo.
"%CONDA_EXE%" run --no-capture-output -n "%CONDA_ENV%" python -m http.server 5173 --bind 127.0.0.1

endlocal
