import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "Classroom Comprehension Assistant"
    allowed_extensions: set[str] = {".mp3", ".wav", ".m4a", ".mp4"}
    whisper_model: str = "small"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "float16"
    assist_provider: str = "litellm"
    assist_base_url: str | None = "https://api.deepseek.com/v1"
    assist_model: str | None = "deepseek-v4-flash"
    assist_api_key: str | None = None
    assist_timeout_seconds: float = 60.0
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
        assist_provider=os.getenv("ASSIST_PROVIDER", "litellm"),
        assist_base_url=os.getenv("ASSIST_BASE_URL", "https://api.deepseek.com/v1"),
        assist_model=os.getenv("ASSIST_MODEL", "deepseek-v4-flash"),
        assist_api_key=os.getenv("ASSIST_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
        assist_timeout_seconds=float(os.getenv("ASSIST_TIMEOUT_SECONDS", "60")),
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
