import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "Classroom Comprehension Assistant"
    allowed_extensions: set[str] = {".mp3", ".wav", ".m4a", ".mp4"}
    whisper_model: str = "small"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "float16"
    diarization_provider: str = "pyannote"
    diarization_model: str = "pyannote/speaker-diarization-community-1"
    diarization_device: str = "cuda"
    huggingface_token: str | None = None
    assist_provider: str = "litellm"
    assist_base_url: str | None = "https://api.deepseek.com/v1"
    assist_model: str | None = "deepseek-v4-flash"
    assist_api_key: str | None = None
    assist_timeout_seconds: float = 60.0
    task_worker_count: int = 4
    gpu_task_concurrency: int = 1
    task_retention_seconds: int = 3600
    stream_buffer_max_ms: int = 30000
    stream_chunk_max_bytes: int = 5 * 1024 * 1024
    stream_backpressure_warning_ms: int = 5000
    stream_backpressure_degraded_ms: int = 15000
    stream_session_retention_seconds: int = 3600
    stream_processor: str = "funasr"
    stream_window_ms: int = 20000
    stream_process_interval_ms: int = 600
    funasr_stream_model: str = "paraformer-zh-streaming"
    funasr_device: str = "cuda"
    funasr_offline_only: bool = False
    stream_finalize_delay_ms: int = 8000
    stream_stable_revisions: int = 2
    stream_worker_count: int = 2
    stream_stop_timeout_seconds: float = 30.0
    ytdlp_cookies_file: str | None = None
    ytdlp_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Classroom Comprehension Assistant"),
        whisper_model=os.getenv("WHISPER_MODEL", "small"),
        whisper_device=os.getenv("WHISPER_DEVICE", "cuda"),
        whisper_compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "float16"),
        diarization_provider=os.getenv("DIARIZATION_PROVIDER", "pyannote"),
        diarization_model=os.getenv(
            "DIARIZATION_MODEL",
            "pyannote/speaker-diarization-community-1",
        ),
        diarization_device=os.getenv("DIARIZATION_DEVICE", "cuda"),
        huggingface_token=(
            os.getenv("HUGGINGFACE_API_KEY")
            or os.getenv("HF_TOKEN")
            or os.getenv("HUGGINGFACE_ACCESS_TOKEN")
        ),
        assist_provider=os.getenv("ASSIST_PROVIDER", "litellm"),
        assist_base_url=os.getenv("ASSIST_BASE_URL", "https://api.deepseek.com/v1"),
        assist_model=os.getenv("ASSIST_MODEL", "deepseek-v4-flash"),
        assist_api_key=os.getenv("ASSIST_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
        assist_timeout_seconds=float(os.getenv("ASSIST_TIMEOUT_SECONDS", "60")),
        task_worker_count=int(os.getenv("TASK_WORKER_COUNT", "4")),
        gpu_task_concurrency=int(os.getenv("GPU_TASK_CONCURRENCY", "1")),
        task_retention_seconds=int(os.getenv("TASK_RETENTION_SECONDS", "3600")),
        stream_buffer_max_ms=int(os.getenv("STREAM_BUFFER_MAX_MS", "30000")),
        stream_chunk_max_bytes=int(
            os.getenv("STREAM_CHUNK_MAX_BYTES", str(5 * 1024 * 1024))
        ),
        stream_backpressure_warning_ms=int(
            os.getenv("STREAM_BACKPRESSURE_WARNING_MS", "5000")
        ),
        stream_backpressure_degraded_ms=int(
            os.getenv("STREAM_BACKPRESSURE_DEGRADED_MS", "15000")
        ),
        stream_session_retention_seconds=int(
            os.getenv("STREAM_SESSION_RETENTION_SECONDS", "3600")
        ),
        stream_processor=os.getenv("STREAM_PROCESSOR", "funasr"),
        stream_window_ms=int(os.getenv("STREAM_WINDOW_MS", "20000")),
        stream_process_interval_ms=int(os.getenv("STREAM_PROCESS_INTERVAL_MS", "600")),
        funasr_stream_model=os.getenv("FUNASR_STREAM_MODEL", "paraformer-zh-streaming"),
        funasr_device=os.getenv("FUNASR_DEVICE", "cuda"),
        funasr_offline_only=os.getenv("FUNASR_OFFLINE_ONLY", "false").lower()
        not in {"0", "false", "no", "off"},
        stream_finalize_delay_ms=int(os.getenv("STREAM_FINALIZE_DELAY_MS", "8000")),
        stream_stable_revisions=int(os.getenv("STREAM_STABLE_REVISIONS", "2")),
        stream_worker_count=int(os.getenv("STREAM_WORKER_COUNT", "2")),
        stream_stop_timeout_seconds=float(os.getenv("STREAM_STOP_TIMEOUT_SECONDS", "30")),
        ytdlp_cookies_file=os.getenv("YTDLP_COOKIES_FILE"),
        ytdlp_user_agent=os.getenv(
            "YTDLP_USER_AGENT",
            (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        ),
    )
