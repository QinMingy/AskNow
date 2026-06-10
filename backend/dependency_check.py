"""Visible startup dependency checks for start_demo.bat."""

from __future__ import annotations

import importlib
import io
import os
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from collections.abc import Callable, Iterable
from typing import TextIO


DEPENDENCIES = (
    ("requests", "Requests"),
    ("yt_dlp", "yt-dlp"),
    ("uvicorn", "Uvicorn"),
    ("torch", "PyTorch"),
    ("torchaudio", "TorchAudio"),
    ("faster_whisper", "faster-whisper"),
    ("funasr", "FunASR"),
    ("pyannote.audio", "pyannote.audio"),
)


def configured_dependencies() -> tuple[tuple[str, str], ...]:
    dependencies = [
        ("requests", "Requests"),
        ("httpx", "HTTPX"),
        ("yt_dlp", "yt-dlp"),
        ("uvicorn", "Uvicorn"),
    ]
    transcription_provider = os.getenv("TRANSCRIPTION_PROVIDER", "local").lower()
    diarization_provider = os.getenv("DIARIZATION_PROVIDER", "pyannote").lower()
    stream_processor = os.getenv("STREAM_PROCESSOR", "funasr").lower()

    if transcription_provider == "local":
        dependencies.append(("faster_whisper", "faster-whisper"))
    if stream_processor == "funasr":
        dependencies.extend((("torch", "PyTorch"), ("funasr", "FunASR")))
    if stream_processor in {"volcengine", "doubao"}:
        dependencies.append(("websockets", "WebSockets"))
    if diarization_provider == "pyannote":
        dependencies.extend(
            (
                ("torch", "PyTorch"),
                ("torchaudio", "TorchAudio"),
                ("pyannote.audio", "pyannote.audio"),
            )
        )
    return tuple(dict.fromkeys(dependencies))


def progress_bar(completed: int, total: int, width: int = 20) -> str:
    filled = width if total == 0 else round(width * completed / total)
    return f"[{'#' * filled}{'-' * (width - filled)}]"


def check_dependencies(
    dependencies: Iterable[tuple[str, str]] = DEPENDENCIES,
    *,
    importer: Callable[[str], object] = importlib.import_module,
    output: TextIO = sys.stdout,
) -> bool:
    items = tuple(dependencies)
    total = len(items)
    overall_started = time.perf_counter()

    for index, (module_name, label) in enumerate(items, start=1):
        print(
            f"{progress_bar(index - 1, total)} [{index}/{total}] Loading {label}...",
            file=output,
            flush=True,
        )
        started = time.perf_counter()
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        try:
            with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
                importer(module_name)
        except Exception as exc:
            elapsed = time.perf_counter() - started
            print(
                f"{progress_bar(index - 1, total)} [{index}/{total}] FAILED {label} "
                f"({elapsed:.1f}s): {exc}",
                file=output,
                flush=True,
            )
            internal_output = (
                captured_stdout.getvalue().strip() or captured_stderr.getvalue().strip()
            )
            if internal_output:
                print("Dependency output:", file=output)
                print(internal_output, file=output)
            return False

        elapsed = time.perf_counter() - started
        print(
            f"{progress_bar(index, total)} [{index}/{total}] Ready {label} "
            f"({elapsed:.1f}s)",
            file=output,
            flush=True,
        )

    print(
        f"{progress_bar(total, total)} Backend dependencies ready "
        f"({time.perf_counter() - overall_started:.1f}s total).",
        file=output,
        flush=True,
    )
    return True


if __name__ == "__main__":
    raise SystemExit(0 if check_dependencies(configured_dependencies()) else 1)
