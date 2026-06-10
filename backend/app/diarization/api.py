from pathlib import Path

from ..remote_models import RemoteModelClient, serialize_segments
from ..schemas import TranscriptSegment


class ApiDiarizer:
    name = "api"

    def __init__(self, client: RemoteModelClient):
        self.client = client

    def assign_speakers(
        self,
        audio_path: Path,
        segments: list[TranscriptSegment],
    ) -> list[TranscriptSegment]:
        if not segments:
            return segments
        payload = self.client.post_audio(
            "/v1/audio/diarizations",
            audio_path,
            data={"segments": serialize_segments(segments)},
        )
        return [
            TranscriptSegment.model_validate(segment)
            for segment in payload.get("segments", [])
        ]
