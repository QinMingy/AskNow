import ctypes
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.env import load_project_env

load_project_env()


def check_python_package(package: str) -> str:
    return "ok" if importlib.util.find_spec(package) else "missing"


def run_version(command: list[str]) -> str:
    executable = shutil.which(command[0])
    if not executable:
        return "missing"

    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception as exc:
        return f"error: {exc}"

    return result.stdout.strip() or "ok"


def check_dll(name: str) -> str:
    try:
        ctypes.WinDLL(name)
    except OSError as exc:
        return f"missing: {exc}"
    return "ok"


def check_cuda_compute_types() -> str:
    try:
        import ctranslate2

        compute_types = ctranslate2.get_supported_compute_types("cuda")
    except Exception as exc:
        return f"error: {exc}"
    return ", ".join(sorted(compute_types))


def check_torch_cuda() -> str:
    try:
        import torch

        if not torch.cuda.is_available():
            return "error: torch CUDA is unavailable"
        return f"ok: {torch.cuda.get_device_name(0)}"
    except Exception as exc:
        return f"error: {exc}"


def find_ffmpeg() -> str:
    conda_ffmpeg = Path(sys.executable).parent / "Library" / "bin" / "ffmpeg.exe"
    return str(conda_ffmpeg) if conda_ffmpeg.exists() else "ffmpeg"


def main() -> int:
    checks = {
        "python": sys.version.split()[0],
        "fastapi": check_python_package("fastapi"),
        "faster_whisper": check_python_package("faster_whisper"),
        "torch": check_python_package("torch"),
        "torchaudio": check_python_package("torchaudio"),
        "pyannote.audio": check_python_package("pyannote.audio"),
        "torchcodec": check_python_package("torchcodec"),
        "uvicorn": check_python_package("uvicorn"),
        "yt_dlp": check_python_package("yt_dlp"),
        "Hugging Face token": "configured"
        if (
            os.getenv("HUGGINGFACE_API_KEY")
            or os.getenv("HF_TOKEN")
            or os.getenv("HUGGINGFACE_ACCESS_TOKEN")
        )
        else "not configured (required for pyannote model download)",
        "nvidia-smi": run_version(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"]
        ),
        "ffmpeg": run_version([find_ffmpeg(), "-version"]),
        "torch CUDA": check_torch_cuda(),
        "cublas64_12.dll": check_dll("cublas64_12.dll"),
        "cudnn64_9.dll": check_dll("cudnn64_9.dll"),
        "cuda compute types": check_cuda_compute_types(),
    }

    for name, value in checks.items():
        print(f"{name}: {value}")

    missing = [
        name
        for name, value in checks.items()
        if value == "missing" or value.startswith(("missing:", "error:"))
    ]
    if missing:
        print("\nMissing requirements:", ", ".join(missing))
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
