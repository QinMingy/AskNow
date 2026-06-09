import logging
import wave
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol

from .schemas import IncrementalTranscriptSegment, TranscriptSegment

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessingAudioChunk:
    sequence: int
    duration_ms: int
    payload: bytes


class StreamProcessor(Protocol):
    def process(
        self,
        chunks: list[ProcessingAudioChunk],
        *,
        mime_type: str,
        window_start_ms: int,
    ) -> list[TranscriptSegment]:
        """Return segments relative to the supplied audio window."""


class WhisperStreamProcessor:
    def __init__(self, transcriber):
        self.transcriber = transcriber

    def process(
        self,
        chunks: list[ProcessingAudioChunk],
        *,
        mime_type: str,
        window_start_ms: int,
    ) -> list[TranscriptSegment]:
        suffix = mime_suffix(mime_type)
        with NamedTemporaryFile(delete=False, suffix=suffix) as audio_file:
            path = Path(audio_file.name)
            if suffix == ".wav":
                audio_file.write(build_pcm_wav_window(chunks))
            else:
                for chunk in chunks:
                    audio_file.write(chunk.payload)
        try:
            return self.transcriber.transcribe_stream_path(path)
        finally:
            path.unlink(missing_ok=True)


class TranscriptRevisionTracker:
    def __init__(self, *, finalize_delay_ms: int = 8000, stable_revisions: int = 2):
        self.finalize_delay_ms = max(0, finalize_delay_ms)
        self.stable_revisions = max(1, stable_revisions)
        self.revision = 0
        self.final_segments: list[IncrementalTranscriptSegment] = []
        self.partial_segments: list[IncrementalTranscriptSegment] = []
        self._stable_counts: dict[tuple[int, int, str], int] = {}

    def update(
        self,
        segments: list[TranscriptSegment],
        *,
        window_start_ms: int,
        audio_end_ms: int,
    ) -> tuple[list[IncrementalTranscriptSegment], list[IncrementalTranscriptSegment]]:
        self.revision += 1
        finalize_before_ms = audio_end_ms - self.finalize_delay_ms
        next_counts: dict[tuple[int, int, str], int] = {}
        partials = []
        newly_final = []

        for segment in segments:
            start_ms = window_start_ms + round(segment.start * 1000)
            end_ms = window_start_ms + round(segment.end * 1000)
            text = segment.text.strip()
            if not text or self._is_already_final(start_ms, end_ms):
                continue
            key = (start_ms, end_ms, text)
            stable_count = self._stable_counts.get(key, 0) + 1
            next_counts[key] = stable_count
            item = IncrementalTranscriptSegment(
                id=f"{start_ms}-{end_ms}",
                start=round(start_ms / 1000, 2),
                end=round(end_ms / 1000, 2),
                speaker=segment.speaker,
                text=text,
                revision=self.revision,
                final=end_ms <= finalize_before_ms or stable_count >= self.stable_revisions,
            )
            (newly_final if item.final else partials).append(item)

        self.final_segments.extend(newly_final)
        self.final_segments.sort(key=lambda item: (item.start, item.end))
        self.partial_segments = partials
        self._stable_counts = next_counts
        return newly_final, list(partials)

    def finalize_all(self) -> list[IncrementalTranscriptSegment]:
        if not self.partial_segments:
            return []
        self.revision += 1
        finalized = [
            segment.model_copy(update={"final": True, "revision": self.revision})
            for segment in self.partial_segments
        ]
        self.final_segments.extend(finalized)
        self.final_segments.sort(key=lambda item: (item.start, item.end))
        self.partial_segments = []
        self._stable_counts = {}
        return finalized

    def _is_already_final(self, start_ms: int, end_ms: int) -> bool:
        return any(
            round(segment.start * 1000) == start_ms
            and round(segment.end * 1000) == end_ms
            for segment in self.final_segments
        )


def mime_suffix(mime_type: str) -> str:
    normalized = mime_type.lower()
    if "wav" in normalized:
        return ".wav"
    if "mp4" in normalized or "m4a" in normalized:
        return ".m4a"
    if "ogg" in normalized:
        return ".ogg"
    return ".webm"


def build_pcm_wav_window(chunks: list[ProcessingAudioChunk]) -> bytes:
    if not chunks:
        raise ValueError("At least one PCM WAV chunk is required.")

    parameters = None
    frames = []
    for chunk in chunks:
        try:
            with wave.open(BytesIO(chunk.payload), "rb") as source:
                current = (
                    source.getnchannels(),
                    source.getsampwidth(),
                    source.getframerate(),
                    source.getcomptype(),
                )
                if current[3] != "NONE":
                    raise ValueError("Only uncompressed PCM WAV chunks are supported.")
                if parameters is None:
                    parameters = current
                elif current != parameters:
                    raise ValueError("PCM WAV chunk formats must match within a stream window.")
                frames.append(source.readframes(source.getnframes()))
        except wave.Error as exc:
            raise ValueError(f"Invalid PCM WAV audio chunk: {exc}") from exc

    output = BytesIO()
    channels, sample_width, sample_rate, _ = parameters
    with wave.open(output, "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(sample_width)
        target.setframerate(sample_rate)
        target.writeframes(b"".join(frames))
    return output.getvalue()
