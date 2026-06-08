@echo off
setlocal

set "ROOT=%~dp0.."
set "CONDA_EXE=%USERPROFILE%\miniforge3\Scripts\conda.exe"
set "CONDA_ENV=whisperproject"
set "SAMPLE=%ROOT%\samples\phase1_zh_sample.wav"

if not exist "%CONDA_EXE%" (
  echo [ERROR] Miniforge was not found:
  echo         %CONDA_EXE%
  exit /b 1
)

"%CONDA_EXE%" run -n "%CONDA_ENV%" python -V >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Conda environment "%CONDA_ENV%" was not found or is not usable.
  exit /b 1
)

if not exist "%SAMPLE%" (
  echo [1/2] Creating Chinese sample audio:
  echo       %SAMPLE%
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Add-Type -AssemblyName System.Speech; " ^
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; " ^
    "$s.SelectVoice('Microsoft Huihui Desktop'); " ^
    "$s.Rate = -1; " ^
    "$s.SetOutputToWaveFile('%SAMPLE%'); " ^
    "$s.Speak('这是课堂助手第一阶段的中文端到端测试音频。上传录音后，系统应该返回带时间戳的字幕。'); " ^
    "$s.Dispose();"
  if errorlevel 1 (
    echo [ERROR] Failed to create sample audio.
    exit /b 1
  )
) else (
  echo [1/2] Reusing sample audio:
  echo       %SAMPLE%
)

echo [2/2] Running real faster-whisper CUDA transcription with tiny model...
set "WHISPER_MODEL=tiny"
"%CONDA_EXE%" run --no-capture-output -n "%CONDA_ENV%" python "%ROOT%\scripts\e2e_transcribe_file.py" "%SAMPLE%"
if errorlevel 1 (
  echo [ERROR] Phase 1 E2E transcription failed.
  exit /b 1
)

echo.
echo Phase 1 E2E check completed.
endlocal
