from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.provider_status import get_assist_provider_status


def test_rule_based_provider_is_ready():
    status = get_assist_provider_status(Settings(assist_provider="rule_based"))

    assert status.ready is True
    assert status.mode == "local_rules"
    assert status.missing == []


def test_openai_compatible_provider_reports_missing_config():
    status = get_assist_provider_status(
        Settings(
            assist_provider="openai_compatible",
            assist_base_url=None,
            assist_model=None,
        )
    )

    assert status.ready is False
    assert status.mode == "openai_compatible"
    assert status.missing == ["ASSIST_BASE_URL", "ASSIST_MODEL"]


def test_litellm_provider_requires_model_but_detects_installed_package():
    status = get_assist_provider_status(
        Settings(
            assist_provider="litellm",
            assist_model=None,
            assist_api_key=None,
        )
    )

    assert status.ready is False
    assert status.mode == "litellm"
    assert status.missing == ["ASSIST_MODEL", "DEEPSEEK_API_KEY or ASSIST_API_KEY"]


def test_default_settings_use_deepseek_litellm(monkeypatch):
    monkeypatch.delenv("ASSIST_PROVIDER", raising=False)
    monkeypatch.delenv("ASSIST_BASE_URL", raising=False)
    monkeypatch.delenv("ASSIST_MODEL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")

    from app.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    get_settings.cache_clear()

    assert settings.assist_provider == "litellm"
    assert settings.assist_base_url == "https://api.deepseek.com/v1"
    assert settings.assist_model == "deepseek-v4-flash"
    assert settings.assist_api_key == "test-deepseek-key"


def test_unknown_provider_is_not_ready():
    status = get_assist_provider_status(Settings(assist_provider="unknown"))

    assert status.ready is False
    assert status.mode == "unsupported"
    assert "Unsupported assist provider" in status.details[0]


def test_provider_status_api_uses_current_settings():
    app.dependency_overrides[get_settings] = lambda: Settings(
        assist_provider="litellm",
        assist_model="openai/gpt-4o-mini",
        assist_api_key="test-key",
    )
    client = TestClient(app)

    try:
        response = client.get("/api/assist/provider")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["provider"] == "litellm"
    assert response.json()["ready"] is True
    assert response.json()["missing"] == []
