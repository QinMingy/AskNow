@echo off
setlocal EnableDelayedExpansion

echo [Classroom Assistant] Stopping demo services...

call :kill_port 8010
call :kill_port 8000
call :kill_port 5173

call :kill_window "Classroom Assistant Backend*"
call :kill_window "Classroom Assistant Frontend*"

echo.
echo Done.
endlocal
exit /b 0

:kill_window
set "WINDOW_PATTERN=%~1"
taskkill /F /T /FI "WINDOWTITLE eq %WINDOW_PATTERN%" >nul 2>nul
if errorlevel 1 (
  echo No service window found matching "%WINDOW_PATTERN%".
) else (
  echo Closed service window "%WINDOW_PATTERN%" and its process tree.
)
exit /b 0

:kill_port
set "PORT=%~1"
set "FOUND="

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
  set "FOUND=1"
  echo Stopping process %%P on port %PORT%...
  taskkill /F /T /PID %%P >nul 2>nul
  if errorlevel 1 (
    echo   Could not stop PID %%P. It may already be closed or require administrator permission.
  ) else (
    echo   Stopped PID %%P and its process tree.
  )
)

if not defined FOUND (
  echo No listening process found on port %PORT%.
)

exit /b 0
