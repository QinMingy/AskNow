import os
from pathlib import Path

try:
    from dotenv import dotenv_values
except ImportError:
    dotenv_values = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"
THIRD_PARTY_ENV_KEYS = frozenset(
    {
        "ASSIST_BASE_URL",
        "ASSIST_API_KEY",
        "ASSIST_MODEL",
        "DEEPSEEK_API_KEY",
        "DIARIZATION_API_BASE_URL",
        "DIARIZATION_API_KEY",
        "DIARIZATION_MODEL",
        "HF_TOKEN",
        "HUGGINGFACE_ACCESS_TOKEN",
        "HUGGINGFACE_API_KEY",
        "MODEL_API_BASE_URL",
        "MODEL_API_KEY",
        "STREAM_API_BASE_URL",
        "STREAM_API_KEY",
        "TRANSCRIPTION_API_BASE_URL",
        "TRANSCRIPTION_API_KEY",
        "VOLCENGINE_APP_ID",
        "VOLCENGINE_ACCESS_TOKEN",
        "VOLCENGINE_RESOURCE_ID",
        "VOLCENGINE_STREAM_ENDPOINT",
    }
)


def load_project_env(path: Path | str = DEFAULT_ENV_PATH) -> bool:
    """Load third-party integration values without overriding process variables."""
    if dotenv_values is None:
        return False
    values = dotenv_values(path)
    loaded = False
    for key in THIRD_PARTY_ENV_KEYS:
        value = values.get(key)
        if value and key not in os.environ:
            os.environ[key] = value
            loaded = True
    return loaded
