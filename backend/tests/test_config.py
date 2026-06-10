from app.config import get_settings


def test_funasr_allows_missing_model_download_by_default(monkeypatch):
    monkeypatch.delenv("FUNASR_OFFLINE_ONLY", raising=False)
    get_settings.cache_clear()

    try:
        assert get_settings().funasr_offline_only is False
    finally:
        get_settings.cache_clear()


def test_stream_refinement_is_enabled_by_default(monkeypatch):
    monkeypatch.delenv("STREAM_REFINEMENT_ENABLED", raising=False)
    monkeypatch.delenv("STREAM_REFINEMENT_TIMEOUT_SECONDS", raising=False)
    get_settings.cache_clear()

    try:
        settings = get_settings()
        assert settings.stream_refinement_enabled is True
        assert settings.stream_refinement_timeout_seconds == 600
    finally:
        get_settings.cache_clear()


def test_remote_model_provider_configuration(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "api")
    monkeypatch.setenv("TRANSCRIPTION_API_BASE_URL", "https://asr.example.com")
    monkeypatch.setenv("DIARIZATION_PROVIDER", "api")
    monkeypatch.setenv("DIARIZATION_API_BASE_URL", "https://speaker.example.com")
    monkeypatch.setenv("STREAM_PROCESSOR", "api")
    monkeypatch.setenv("STREAM_API_BASE_URL", "https://live.example.com")
    get_settings.cache_clear()

    try:
        settings = get_settings()
        assert settings.transcription_provider == "api"
        assert settings.transcription_api_base_url == "https://asr.example.com"
        assert settings.diarization_api_base_url == "https://speaker.example.com"
        assert settings.stream_api_base_url == "https://live.example.com"
    finally:
        get_settings.cache_clear()


def test_shared_model_api_configuration_is_used_as_fallback(monkeypatch):
    monkeypatch.setenv("MODEL_API_BASE_URL", "https://models.example.com")
    monkeypatch.setenv("MODEL_API_KEY", "shared-key")
    monkeypatch.delenv("TRANSCRIPTION_API_BASE_URL", raising=False)
    monkeypatch.delenv("DIARIZATION_API_BASE_URL", raising=False)
    monkeypatch.delenv("STREAM_API_BASE_URL", raising=False)
    get_settings.cache_clear()

    try:
        settings = get_settings()
        assert settings.transcription_api_base_url == "https://models.example.com"
        assert settings.diarization_api_key == "shared-key"
        assert settings.stream_api_base_url == "https://models.example.com"
    finally:
        get_settings.cache_clear()


def test_huggingface_api_key_is_preferred(monkeypatch):
    monkeypatch.setenv("HUGGINGFACE_API_KEY", "primary-token")
    monkeypatch.setenv("HF_TOKEN", "fallback-token")
    get_settings.cache_clear()

    try:
        assert get_settings().huggingface_token == "primary-token"
    finally:
        get_settings.cache_clear()
