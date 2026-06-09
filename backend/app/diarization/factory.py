from .base import Diarizer
from .mock import MockDiarizer
from .pyannote import PyannoteDiarizer


def create_diarizer(
    provider: str,
    *,
    model: str,
    token: str | None,
    device: str,
) -> Diarizer:
    normalized = provider.strip().lower().replace("-", "_")
    if normalized in {"mock", "simulated"}:
        return MockDiarizer()
    if normalized in {"pyannote", "speaker_diarization_3_1"}:
        return PyannoteDiarizer(model=model, token=token, device=device)
    raise ValueError(f"Unsupported diarization provider: {provider}")
