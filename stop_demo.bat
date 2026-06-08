@echo off
setlocal

echo [Classroom Assistant] Stopping demo services...

call :kill_port 8010
call :kill_port 8000
call :kill_port 5173

echo.
echo Done. If a terminal window remains open, it is safe to close it.
endlocal
exit /b 0

:kill_port
set "PORT=%~1"
set "FOUND="

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
  set "FOUND=1"
  echo Stopping process %%P on port %PORT%...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Stop-Process -Id %%P -Force -ErrorAction Stop" >nul 2>nul
  if errorlevel 1 (
    taskkill /F /T /PID %%P >nul 2>nul
  )
  if errorlevel 1 (
    echo   Could not stop PID %%P. It may already be closed or require administrator permission.
  ) else (
    echo   Stopped PID %%P.
  )
)

if not defined FOUND (
  echo No listening process found on port %PORT%.
)

exit /b 0
