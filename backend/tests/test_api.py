from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app, get_source_registry, get_transcriber
from app.schemas import SourceMetadata, TranscriptSegment, TranscriptionResponse


class FakeTranscriber:
    async def transcribe_upload(self, file):
        return TranscriptionResponse(
            language="zh",
            duration=4.2,
            segments=[
                TranscriptSegment(
                    id=1,
                    start=0.0,
                    end=4.2,
                    speaker="Speaker A",
                    text="这里是测试转写。",
                )
            ],
        )

    def transcribe_url(self, url, source_registry, browser=None):
        return TranscriptionResponse(
            language="zh",
            duration=6.5,
            segments=[
                TranscriptSegment(
                    id=1,
                    start=0.0,
                    end=6.5,
                    speaker="Speaker A",
                    text="这里是视频链接测试转写。",
                )
            ],
            source=SourceMetadata(
                provider="YouTube",
                title="测试视频",
                webpage_url=url,
            ),
        )


def test_health():
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["api_version"] == "0.3.0"
    assert response.json()["asr_engine"] == "faster-whisper"
    assert response.json()["diarization_provider"] == "pyannote"
    assert response.json()["assist_provider"] == "litellm"
    assert "chrome" in response.json()["browser_cookie_sources"]


def test_transcribe_returns_unified_schema(tmp_path: Path):
    app.dependency_overrides[get_transcriber] = lambda: FakeTranscriber()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/transcribe",
            files={"file": ("sample.wav", b"fake-audio", "audio/wav")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "language": "zh",
        "duration": 4.2,
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 4.2,
                "speaker": "Speaker A",
                "text": "这里是测试转写。",
            }
        ],
        "source": None,
    }


def test_transcribe_rejects_unsupported_format():
    client = TestClient(app)
    response = client.post(
        "/api/transcribe",
        files={"file": ("notes.txt", b"not-audio", "text/plain")},
    )

    assert response.status_code == 400
    assert "Unsupported audio format" in response.json()["detail"]


def test_transcribe_url_returns_source_metadata():
    app.dependency_overrides[get_transcriber] = lambda: FakeTranscriber()
    app.dependency_overrides[get_source_registry] = lambda: object()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/transcribe-url",
            json={"url": "https://youtu.be/example"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["source"] == {
        "provider": "YouTube",
        "title": "测试视频",
        "webpage_url": "https://youtu.be/example",
    }


def test_transcribe_url_accepts_browser_cookie_source():
    seen = {}

    class BrowserAwareTranscriber(FakeTranscriber):
        def transcribe_url(self, url, source_registry, browser=None):
            seen["browser"] = browser
            return super().transcribe_url(url, source_registry, browser=browser)

    app.dependency_overrides[get_transcriber] = lambda: BrowserAwareTranscriber()
    app.dependency_overrides[get_source_registry] = lambda: object()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/transcribe-url",
            json={"url": "https://www.bilibili.com/video/BVexample", "browser": "edge"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert seen["browser"] == "edge"
