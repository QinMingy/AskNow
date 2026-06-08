from .registry import SourceRegistry
from .yt_dlp_resolver import YtDlpSourceResolver


def create_default_registry(settings=None) -> SourceRegistry:
    registry = SourceRegistry()
    registry.register(
        YtDlpSourceResolver(
            cookies_file=getattr(settings, "ytdlp_cookies_file", None),
            user_agent=getattr(settings, "ytdlp_user_agent", None),
        )
    )
    return registry
