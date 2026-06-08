from pathlib import Path

import pytest
from fastapi import HTTPException

from app.sources.registry import SourceRegistry
from app.sources.base import ResolvedMedia
from app.sources.yt_dlp_resolver import YtDlpSourceResolver


def test_yt_dlp_resolver_recognizes_youtube_and_bilibili():
    resolver = YtDlpSourceResolver()

    assert resolver.supports("https://www.youtube.com/watch?v=example")
    assert resolver.supports("https://youtu.be/example")
    assert resolver.supports("https://www.bilibili.com/video/BVexample")
    assert resolver.supports("https://b23.tv/example")
    assert not resolver.supports("https://example.com/video")


@pytest.mark.parametrize(
    "url",
    [
        "not-a-url",
        "file:///tmp/video.mp4",
        "https://example.com/video",
    ],
)
def test_registry_rejects_invalid_or_unsupported_sources(url: str, tmp_path: Path):
    registry = SourceRegistry()
    registry.register(YtDlpSourceResolver())

    with pytest.raises(HTTPException) as exc_info:
        registry.resolve(url, tmp_path)

    assert exc_info.value.status_code == 400


def test_registry_can_be_extended_with_custom_resolver(tmp_path: Path):
    class CustomResolver:
        provider = "Custom Classroom Video"

        def supports(self, url: str) -> bool:
            return "classroom.example" in url

        def resolve(self, url: str, output_dir: Path, browser: str | None = None) -> ResolvedMedia:
            media_path = output_dir / "class.mp3"
            media_path.write_bytes(b"fake-audio")
            return ResolvedMedia(
                provider=self.provider,
                title="示例课堂",
                webpage_url=url,
                media_path=media_path,
            )

    registry = SourceRegistry()
    registry.register(CustomResolver())

    resolved = registry.resolve("https://classroom.example/lesson/1", tmp_path)

    assert resolved.provider == "Custom Classroom Video"
    assert resolved.media_path.read_bytes() == b"fake-audio"


def test_yt_dlp_options_include_bilibili_browser_headers(tmp_path: Path):
    resolver = YtDlpSourceResolver(user_agent="Test Browser")

    options = resolver._build_options("https://www.bilibili.com/video/BVexample", tmp_path)

    assert options["http_headers"]["User-Agent"] == "Test Browser"
    assert options["http_headers"]["Referer"] == "https://www.bilibili.com/"
    assert "zh-CN" in options["http_headers"]["Accept-Language"]


def test_yt_dlp_options_include_cookie_file_when_configured(tmp_path: Path):
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    resolver = YtDlpSourceResolver(cookies_file=str(cookies_file))

    options = resolver._build_options("https://youtu.be/example", tmp_path)

    assert options["cookiefile"] == str(cookies_file)


def test_yt_dlp_options_can_read_cookies_from_browser(tmp_path: Path):
    resolver = YtDlpSourceResolver()

    options = resolver._build_options("https://www.bilibili.com/video/BVexample", tmp_path, browser="firefox")

    assert options["cookiesfrombrowser"] == ("firefox", None, None, None)


def test_yt_dlp_options_reject_missing_cookie_file(tmp_path: Path):
    resolver = YtDlpSourceResolver(cookies_file=str(tmp_path / "missing-cookies.txt"))

    with pytest.raises(HTTPException) as exc_info:
        resolver._build_options("https://www.bilibili.com/video/BVexample", tmp_path)

    assert exc_info.value.status_code == 400
    assert "YTDLP_COOKIES_FILE" in exc_info.value.detail
