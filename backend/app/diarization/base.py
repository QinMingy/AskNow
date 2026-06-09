from pathlib import Path
from typing import Protocol

from ..schemas import TranscriptSegment


class Diarizer(Protocol):
    name: str

    def assign_speakers(
        self,
        audio_path: Path,
        segments: list[TranscriptSegment],
    ) -> list[TranscriptSegment]:
        """Assign a speaker label to every transcript segment."""
