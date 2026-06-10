import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


def load_project_env(path: Path | str = DEFAULT_ENV_PATH) -> bool:
    """Load project-local values without overriding process environment variables."""
    if load_dotenv is None:
        return False
    return load_dotenv(dotenv_path=path, override=False)
