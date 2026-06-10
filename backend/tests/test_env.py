import os

from app.env import load_project_env


def test_project_env_loads_values(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        "ASKNOW_TEST_ENV=from-dotenv\nASKNOW_QUOTED_ENV=\"quoted value\"\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ASKNOW_TEST_ENV", raising=False)
    monkeypatch.delenv("ASKNOW_QUOTED_ENV", raising=False)

    assert load_project_env(path) is True
    assert os.environ["ASKNOW_TEST_ENV"] == "from-dotenv"
    assert os.environ["ASKNOW_QUOTED_ENV"] == "quoted value"


def test_process_environment_takes_precedence_over_dotenv(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("ASKNOW_TEST_PRIORITY=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("ASKNOW_TEST_PRIORITY", "from-process")

    load_project_env(path)

    assert os.environ["ASKNOW_TEST_PRIORITY"] == "from-process"
