from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException, status

from .base import ResolvedMedia


class YtDlpSourceResolver:
    provider = "YouTube/Bilibili"

    _supported_hosts = {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
        "bilibili.com",
        "www.bilibili.com",
        "m.bilibili.com",
        "b23.tv",
    }

    def __init__(self, cookies_file: str | None = None, user_agent: str | None = None) -> None:
        self.cookies_file = cookies_file
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        )

    def supports(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return host in self._supported_hosts or any(host.endswith(f".{domain}") for domain in self._supported_hosts)

    def resolve(self, url: str, output_dir: Path, browser: str | None = None) -> ResolvedMedia:
        try:
            from yt_dlp import YoutubeDL
        except ImportError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="yt-dlp is not installed. Run `pip install -r backend/requirements.txt`.",
            ) from exc

        output_dir.mkdir(parents=True, exist_ok=True)
        options = self._build_options(url, output_dir, browser=browser)

        before = {path.resolve() for path in output_dir.iterdir() if path.is_file()}

        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
        except Exception as exc:
            auth_mode = f"browser login: {browser}" if browser else "anonymous download"
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "Failed to download media from the video URL. "
                    f"Attempted mode: {auth_mode}. "
                    "Bilibili may return HTTP 412 when it rejects non-browser requests. "
                    "Choose a browser login session in the UI and retry. Firefox is often the most reliable "
                    "choice on Windows; Chromium browsers may fail if their cookie database is locked. "
                    "If cookies also fail, Bilibili may be temporarily limiting the current IP. "
                    "Some YouTube videos may also require cookies, age confirmation, or network access. "
                    f"Original error: {exc}"
                ),
            ) from exc

        after = [path for path in output_dir.iterdir() if path.is_file() and path.resolve() not in before]
        media_path = self._pick_media_file(after)
        if media_path is None:
            requested = info.get("requested_downloads") or []
            candidates = [Path(item["filepath"]) for item in requested if item.get("filepath")]
            media_path = self._pick_media_file(candidates)

        if media_path is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Video download finished, but no local media file was found.",
            )

        return ResolvedMedia(
            provider=str(info.get("extractor_key") or self.provider),
            title=info.get("title"),
            webpage_url=str(info.get("webpage_url") or url),
            media_path=media_path,
        )

    @staticmethod
    def _pick_media_file(paths: list[Path]) -> Path | None:
        for path in paths:
            if path.exists() and path.is_file() and path.suffix.lower() not in {".json", ".part", ".ytdl"}:
                return path
        return None

    def _build_options(self, url: str, output_dir: Path, browser: str | None = None) -> dict:
        host = urlparse(url).netloc.lower()
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        if "bilibili.com" in host or host == "b23.tv" or host.endswith(".b23.tv"):
            headers["Referer"] = "https://www.bilibili.com/"
        elif "youtube.com" in host or host == "youtu.be" or host.endswith(".youtu.be"):
            headers["Referer"] = "https://www.youtube.com/"

        options = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "outtmpl": str(output_dir / "%(extractor)s-%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "http_headers": headers,
        }

        if self.cookies_file:
            cookies_path = Path(self.cookies_file)
            if not cookies_path.exists():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Configured YTDLP_COOKIES_FILE does not exist: {cookies_path}",
                )
            options["cookiefile"] = str(cookies_path)
        elif browser:
            options["cookiesfrombrowser"] = (browser, None, None, None)

        return options
