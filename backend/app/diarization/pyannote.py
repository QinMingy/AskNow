import logging
import subprocess
import sys
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import HTTPException, status

from ..schemas import TranscriptSegment

logger = logging.getLogger(__name__)


class PyannoteDiarizer:
    name = "pyannote"

    def __init__(
        self,
        model: str,
        token: str | None,
        device: str = "cuda",
        pipeline=None,
        audio_loader=None,
        pipeline_factory=None,
        load_max_attempts: int = 3,
        load_retry_backoff_seconds: float = 2.0,
        sleep_func=time.sleep,
    ):
        self.model = model
        self.token = token
        self.device = device
        self._pipeline = pipeline
        self._audio_loader = audio_loader
        self._pipeline_factory = pipeline_factory
        self.load_max_attempts = max(1, load_max_attempts)
        self.load_retry_backoff_seconds = max(0.0, load_retry_backoff_seconds)
        self._sleep = sleep_func
        self._pipeline_lock = threading.Lock()

    def _load_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        if not self.token:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Pyannote speaker diarization requires a Hugging Face token. "
                    "Accept access for "
                    "`pyannote/speaker-diarization-community-1`, "
                    "then set the HUGGINGFACE_API_KEY environment variable."
                ),
            )

        with self._pipeline_lock:
            if self._pipeline is not None:
                return self._pipeline
            started = time.perf_counter()
            logger.info(
                "pyannote.model_load.start model=%s device=%s max_attempts=%s",
                self.model,
                self.device,
                self.load_max_attempts,
            )
            last_error = None
            for attempt in range(1, self.load_max_attempts + 1):
                try:
                    self._pipeline = self._create_pipeline()
                    break
                except HTTPException:
                    raise
                except Exception as exc:
                    last_error = exc
                    retryable = self._is_retryable_network_error(exc)
                    logger.warning(
                        "pyannote.model_load.attempt_failed model=%s attempt=%s/%s retryable=%s error_type=%s error=%s",
                        self.model,
                        attempt,
                        self.load_max_attempts,
                        retryable,
                        type(exc).__name__,
                        exc,
                    )
                    if not retryable or attempt >= self.load_max_attempts:
                        break
                    delay = self.load_retry_backoff_seconds * attempt
                    logger.info(
                        "pyannote.model_load.retry model=%s next_attempt=%s delay_seconds=%.1f",
                        self.model,
                        attempt + 1,
                        delay,
                    )
                    self._sleep(delay)

            if self._pipeline is None:
                logger.exception(
                    "pyannote.model_load.failed model=%s attempts=%s",
                    self.model,
                    self.load_max_attempts,
                    exc_info=last_error,
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=self._load_error_detail(last_error),
                ) from last_error

            logger.info(
                "pyannote.model_load.complete model=%s elapsed_ms=%.1f",
                self.model,
                (time.perf_counter() - started) * 1000,
            )
        return self._pipeline

    def _create_pipeline(self):
        import torch

        if self._pipeline_factory is None:
            from pyannote.audio import Pipeline

            self._pipeline_factory = Pipeline.from_pretrained
        pipeline = self._pipeline_factory(self.model, token=self.token)
        if pipeline is None:
            raise RuntimeError(
                "Pipeline download returned no model. Verify gated-model access."
            )
        pipeline.to(torch.device(self.device))
        return pipeline

    @staticmethod
    def _is_retryable_network_error(exc: Exception) -> bool:
        retryable_names = {
            "ConnectError",
            "ConnectionError",
            "ConnectionResetError",
            "ConnectTimeout",
            "ReadError",
            "ReadTimeout",
            "RemoteProtocolError",
            "ServerDisconnectedError",
            "TimeoutError",
        }
        retryable_messages = (
            "server disconnected",
            "connection reset",
            "connection aborted",
            "connection refused",
            "connection timed out",
            "read timed out",
            "temporary failure",
            "temporarily unavailable",
            "remote protocol error",
        )
        current: BaseException | None = exc
        while current is not None:
            if type(current).__name__ in retryable_names:
                return True
            message = str(current).lower()
            if any(pattern in message for pattern in retryable_messages):
                return True
            current = current.__cause__ or current.__context__
        return False

    def _load_error_detail(self, exc: Exception | None) -> str:
        if exc is not None and self._is_retryable_network_error(exc):
            return (
                "Unable to initialize pyannote speaker diarization after "
                f"{self.load_max_attempts} network attempts. The model cache exists, "
                "but Hugging Face disconnected while the pipeline checked or fetched "
                "model files. Retry later, verify network/proxy access to huggingface.co, "
                "or set HF_HUB_DOWNLOAD_TIMEOUT=120. "
                f"Original error: {exc}"
            )
        return (
            "Unable to initialize pyannote speaker diarization. Verify "
            "HUGGINGFACE_API_KEY, accepted model conditions, network access, "
            "and GPU environment. "
            f"Original error: {exc}"
        )

    def _load_audio(self, audio_path: Path) -> dict:
        if self._audio_loader is not None:
            return self._audio_loader(audio_path)

        try:
            import torchaudio

            with TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
                normalized_path = Path(tmpdir) / "diarization-input.wav"
                command = [
                    str(self._ffmpeg_executable()),
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(audio_path),
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(normalized_path),
                ]
                started = time.perf_counter()
                logger.info(
                    "pyannote.audio_decode.start extension=%s",
                    audio_path.suffix.lower(),
                )
                subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                waveform, sample_rate = torchaudio.load(str(normalized_path))
                logger.info(
                    "pyannote.audio_decode.complete sample_rate=%s channels=%s samples=%s elapsed_ms=%.1f",
                    sample_rate,
                    waveform.shape[0],
                    waveform.shape[-1],
                    (time.perf_counter() - started) * 1000,
                )
                return {"waveform": waveform, "sample_rate": sample_rate}
        except Exception as exc:
            logger.exception("pyannote.audio_decode.failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unable to prepare audio for speaker diarization: {exc}",
            ) from exc

    @staticmethod
    def _ffmpeg_executable() -> Path | str:
        conda_ffmpeg = Path(sys.executable).parent / "Library" / "bin" / "ffmpeg.exe"
        return conda_ffmpeg if conda_ffmpeg.exists() else "ffmpeg"

    def assign_speakers(
        self,
        audio_path: Path,
        segments: list[TranscriptSegment],
    ) -> list[TranscriptSegment]:
        if not segments:
            return segments

        started = time.perf_counter()
        logger.info(
            "pyannote.inference.start model=%s segments=%s",
            self.model,
            len(segments),
        )
        try:
            audio = self._load_audio(audio_path)
            output = self._load_pipeline()(audio)
            diarization = getattr(output, "speaker_diarization", output)
            turns = [
                (float(turn.start), float(turn.end), str(speaker))
                for turn, _, speaker in diarization.itertracks(yield_label=True)
            ]
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("pyannote.inference.failed model=%s", self.model)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Speaker diarization failed: {exc}",
            ) from exc

        speaker_names: dict[str, str] = {}
        for segment in segments:
            raw_speaker = self._best_speaker(segment.start, segment.end, turns)
            if raw_speaker not in speaker_names:
                speaker_names[raw_speaker] = self._display_name(len(speaker_names))
            segment.speaker = speaker_names[raw_speaker]

        logger.info(
            "pyannote.inference.complete turns=%s speakers=%s elapsed_ms=%.1f",
            len(turns),
            len(speaker_names),
            (time.perf_counter() - started) * 1000,
        )
        return segments

    @staticmethod
    def _best_speaker(
        start: float,
        end: float,
        turns: list[tuple[float, float, str]],
    ) -> str:
        overlaps: dict[str, float] = {}
        for turn_start, turn_end, speaker in turns:
            overlap = max(0.0, min(end, turn_end) - max(start, turn_start))
            if overlap > 0:
                overlaps[speaker] = overlaps.get(speaker, 0.0) + overlap

        if overlaps:
            return max(overlaps, key=overlaps.get)

        midpoint = (start + end) / 2
        if turns:
            return min(
                turns,
                key=lambda turn: abs(((turn[0] + turn[1]) / 2) - midpoint),
            )[2]
        return "UNKNOWN"

    @staticmethod
    def _display_name(index: int) -> str:
        if index < 26:
            return f"Speaker {chr(ord('A') + index)}"
        return f"Speaker {index + 1}"
