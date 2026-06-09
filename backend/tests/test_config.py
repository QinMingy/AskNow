from app.config import get_settings


def test_funasr_allows_missing_model_download_by_default(monkeypatch):
    monkeypatch.delenv("FUNASR_OFFLINE_ONLY", raising=False)
    get_settings.cache_clear()

    try:
        assert get_settings().funasr_offline_only is False
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
