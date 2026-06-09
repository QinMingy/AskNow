from pathlib import Path

from ..schemas import TranscriptSegment


class MockDiarizer:
    name = "mock"

    def assign_speakers(
        self,
        audio_path: Path,
        segments: list[TranscriptSegment],
    ) -> list[TranscriptSegment]:
        del audio_path
        for index, segment in enumerate(segments):
            segment.speaker = "Speaker A" if index % 2 == 0 else "Speaker B"
        return segments
