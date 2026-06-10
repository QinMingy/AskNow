import os

from app.env import load_project_env


def test_project_env_loads_values(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        "DEEPSEEK_API_KEY=from-dotenv\n"
        "VOLCENGINE_APP_ID=third-party-app\n"
        "STREAM_PROCESSOR=volcengine\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_APP_ID", raising=False)
    monkeypatch.delenv("STREAM_PROCESSOR", raising=False)

    assert load_project_env(path) is True
    assert os.environ["DEEPSEEK_API_KEY"] == "from-dotenv"
    assert os.environ["VOLCENGINE_APP_ID"] == "third-party-app"
    assert "STREAM_PROCESSOR" not in os.environ


def test_process_environment_takes_precedence_over_dotenv(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("HUGGINGFACE_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("HUGGINGFACE_API_KEY", "from-process")

    load_project_env(path)

    assert os.environ["HUGGINGFACE_API_KEY"] == "from-process"
