from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ResolvedMedia:
    provider: str
    title: str | None
    webpage_url: str
    media_path: Path


class SourceResolver(Protocol):
    provider: str

    def supports(self, url: str) -> bool:
        """Return whether this resolver can handle the URL."""

    def resolve(self, url: str, output_dir: Path, browser: str | None = None) -> ResolvedMedia:
        """Download or resolve a URL into a local media file ready for transcription."""
