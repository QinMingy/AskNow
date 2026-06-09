import logging
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException, status

from .base import ResolvedMedia, SourceResolver

logger = logging.getLogger(__name__)


class SourceRegistry:
    def __init__(self) -> None:
        self._resolvers: list[SourceResolver] = []

    def register(self, resolver: SourceResolver) -> None:
        self._resolvers.append(resolver)

    def resolve(self, url: str, output_dir: Path, browser: str | None = None) -> ResolvedMedia:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please provide a valid http(s) video URL.",
            )

        for resolver in self._resolvers:
            if resolver.supports(url):
                logger.info(
                    "source.selected provider=%s host=%s browser=%s",
                    resolver.provider,
                    parsed.netloc.lower(),
                    browser or "anonymous",
                )
                return resolver.resolve(url, output_dir, browser=browser)

        supported = ", ".join(resolver.provider for resolver in self._resolvers)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported video source. Supported sources: {supported}.",
        )
