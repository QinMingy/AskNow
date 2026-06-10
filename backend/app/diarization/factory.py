from .base import Diarizer
from .api import ApiDiarizer
from .mock import MockDiarizer, PassthroughDiarizer
from .pyannote import PyannoteDiarizer
from ..remote_models import RemoteModelClient


def create_diarizer(
    provider: str,
    *,
    model: str,
    token: str | None,
    device: str,
    api_base_url: str | None = None,
    api_key: str | None = None,
    api_timeout_seconds: float = 600.0,
) -> Diarizer:
    normalized = provider.strip().lower().replace("-", "_")
    if normalized in {"mock", "simulated"}:
        return MockDiarizer()
    if normalized in {"none", "off", "disabled", "passthrough"}:
        return PassthroughDiarizer()
    if normalized in {"pyannote", "speaker_diarization_3_1"}:
        return PyannoteDiarizer(model=model, token=token, device=device)
    if normalized in {"api", "remote"}:
        return ApiDiarizer(
            RemoteModelClient(
                base_url=api_base_url or "",
                api_key=api_key,
                timeout_seconds=api_timeout_seconds,
            )
        )
    raise ValueError(f"Unsupported diarization provider: {provider}")
