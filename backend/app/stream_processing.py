import logging
import threading
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


@dataclass
class FunASRSessionState:
    cache: dict


class FunASRStreamProcessor:
    incremental = True
    speaker_label = "Mixed speakers"

    def __init__(
        self,
        *,
        model: str = "paraformer-zh-streaming",
        device: str = "cuda",
        chunk_size: tuple[int, int, int] = (0, 10, 5),
        encoder_chunk_look_back: int = 4,
        decoder_chunk_look_back: int = 1,
        model_factory=None,
    ):
        self.model_name = model
        self.device = device
        self.chunk_size = list(chunk_size)
        self.encoder_chunk_look_back = encoder_chunk_look_back
        self.decoder_chunk_look_back = decoder_chunk_look_back
        self._model_factory = model_factory
        self._model = None
        self._model_lock = threading.Lock()

    def create_session(self, *, mime_type: str, sample_rate: int, channels: int):
        if "pcm" not in mime_type.lower():
            raise ValueError("FunASR live sessions require raw PCM16 audio.")
        if sample_rate != 16000 or channels != 1:
            raise ValueError("FunASR live sessions require 16 kHz mono audio.")
        return FunASRSessionState(cache={})

    def process_incremental(
        self,
        chunks: list[ProcessingAudioChunk],
        *,
        state: FunASRSessionState,
        mime_type: str,
        window_start_ms: int,
        is_final: bool,
    ) -> list[TranscriptSegment]:
        if not chunks:
            return []
        payload = b"".join(chunk.payload for chunk in chunks)
        if len(payload) % 2:
            raise ValueError("Raw PCM16 payload must contain complete 16-bit samples.")

        import numpy as np

        speech = np.frombuffer(payload, dtype="<i2").astype(np.float32) / 32768.0
        logger.info(
            "funasr.stream.inference start_ms=%s chunks=%s samples=%s is_final=%s",
            window_start_ms,
            len(chunks),
            len(speech),
            is_final,
        )
        result = self._get_model().generate(
            input=speech,
            cache=state.cache,
            is_final=is_final,
            chunk_size=self.chunk_size,
            encoder_chunk_look_back=self.encoder_chunk_look_back,
            decoder_chunk_look_back=self.decoder_chunk_look_back,
        )
        texts = [
            str(item.get("text", "")).strip()
            for item in (result or [])
            if isinstance(item, dict) and str(item.get("text", "")).strip()
        ]
        duration = sum(chunk.duration_ms for chunk in chunks) / 1000
        logger.info("funasr.stream.inference.complete texts=%s", len(texts))
        return [
            TranscriptSegment(
                id=index,
                start=0.0,
                end=duration,
                speaker=self.speaker_label,
                text=text,
            )
            for index, text in enumerate(texts, start=1)
        ]

    def _get_model(self):
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is None:
                logger.info(
                    "funasr.model.load model=%s device=%s",
                    self.model_name,
                    self.device,
                )
                if self._model_factory is None:
                    from funasr import AutoModel

                    self._model_factory = AutoModel
                resolved_model = resolve_funasr_model_path(self.model_name)
                self._model = self._model_factory(
                    model=resolved_model,
                    device=self.device,
                    disable_update=True,
                    disable_pbar=True,
                )
                logger.info(
                    "funasr.model.ready model=%s resolved_model=%s",
                    self.model_name,
                    resolved_model,
                )
        return self._model


def resolve_funasr_model_path(model: str) -> str:
    supplied = Path(model).expanduser()
    if supplied.exists():
        return str(supplied)

    cached_repositories = {
        "paraformer-zh-streaming": (
            "iic",
            "speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online",
        ),
    }
    repository = cached_repositories.get(model)
    if repository is None:
        return model
    cached = Path.home() / ".cache" / "modelscope" / "hub" / "models" / Path(*repository)
    if (cached / "config.yaml").exists() and (cached / "model.pt").exists():
        logger.info("funasr.model.use_local_cache path=%s", cached)
        return str(cached)
    return model


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

    def commit(
        self,
        segments: list[TranscriptSegment],
        *,
        window_start_ms: int,
    ) -> list[IncrementalTranscriptSegment]:
        if not segments:
            return []
        self.revision += 1
        committed = []
        for index, segment in enumerate(segments, start=1):
            start_ms = window_start_ms + round(segment.start * 1000)
            end_ms = window_start_ms + round(segment.end * 1000)
            text = segment.text.strip()
            if not text:
                continue
            committed.append(
                IncrementalTranscriptSegment(
                    id=f"{start_ms}-{end_ms}-{self.revision}-{index}",
                    start=round(start_ms / 1000, 2),
                    end=round(end_ms / 1000, 2),
                    speaker=segment.speaker,
                    text=text,
                    revision=self.revision,
                    final=True,
                )
            )
        self.final_segments.extend(committed)
        return committed

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
