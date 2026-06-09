import logging
import time
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Callable

from fastapi import HTTPException, UploadFile, status

from .config import Settings
from .diarization import Diarizer
from .schemas import SourceMetadata, TranscriptSegment, TranscriptionResponse
from .sources.registry import SourceRegistry

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, int, str], None]
CancelCheck = Callable[[], bool]


class TranscriptionCancelled(Exception):
    pass


class WhisperTranscriber:
    def __init__(self, settings: Settings, diarizer: Diarizer):
        self.settings = settings
        self.diarizer = diarizer
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model

        started = time.perf_counter()
        logger.info(
            "whisper.model_load.start model=%s device=%s compute_type=%s",
            self.settings.whisper_model,
            self.settings.whisper_device,
            self.settings.whisper_compute_type,
        )
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "faster-whisper or one of its runtime dependencies could not be imported. "
                    "Install the project dependencies in the `whisperproject` Conda environment. "
                    f"Original error: {exc}"
                ),
            ) from exc

        try:
            self._model = WhisperModel(
                self.settings.whisper_model,
                device=self.settings.whisper_device,
                compute_type=self.settings.whisper_compute_type,
            )
        except Exception as exc:
            logger.exception("whisper.model_load.failed model=%s", self.settings.whisper_model)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Unable to initialize faster-whisper with CUDA. "
                    "Phase 1 expects a Windows GPU environment with CUDA available. "
                    f"Original error: {exc}"
                ),
            ) from exc

        logger.info(
            "whisper.model_load.complete model=%s elapsed_ms=%.1f",
            self.settings.whisper_model,
            (time.perf_counter() - started) * 1000,
        )
        return self._model

    async def transcribe_upload(self, file: UploadFile) -> TranscriptionResponse:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in self.settings.allowed_extensions:
            allowed = ", ".join(sorted(self.settings.allowed_extensions))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported audio format `{suffix or 'unknown'}`. Supported formats: {allowed}.",
            )

        with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = Path(tmp.name)
            uploaded_bytes = 0
            while chunk := await file.read(1024 * 1024):
                tmp.write(chunk)
                uploaded_bytes += len(chunk)

        try:
            logger.info(
                "upload.ready extension=%s bytes=%s",
                suffix,
                uploaded_bytes,
            )
            return self._transcribe_path(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
            await file.close()

    def transcribe_url(
        self,
        url: str,
        source_registry: SourceRegistry,
        browser: str | None = None,
    ) -> TranscriptionResponse:
        with TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            logger.info("video.resolve.start browser=%s", browser or "anonymous")
            media = source_registry.resolve(url, Path(tmpdir), browser=browser)
            logger.info(
                "video.resolve.complete provider=%s extension=%s bytes=%s",
                media.provider,
                media.media_path.suffix.lower(),
                media.media_path.stat().st_size,
            )
            response = self._transcribe_path(media.media_path)
            response.source = SourceMetadata(
                provider=media.provider,
                title=media.title,
                webpage_url=media.webpage_url,
            )
            return response

    def transcribe_path(
        self,
        audio_path: Path,
        *,
        progress: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> TranscriptionResponse:
        model = self._load_model()

        started = time.perf_counter()
        logger.info(
            "whisper.inference.start model=%s extension=%s bytes=%s",
            self.settings.whisper_model,
            audio_path.suffix.lower(),
            audio_path.stat().st_size,
        )
        try:
            if progress:
                progress("transcribing", 25, "Transcribing audio")
            segments_iter, info = model.transcribe(
                str(audio_path),
                language="zh",
                vad_filter=True,
                beam_size=5,
            )
            segments = []
            for idx, segment in enumerate(segments_iter, start=1):
                if cancel_check and cancel_check():
                    raise TranscriptionCancelled()
                segments.append(
                    TranscriptSegment(
                        id=idx,
                        start=round(float(segment.start), 2),
                        end=round(float(segment.end), 2),
                        speaker="Unknown",
                        text=segment.text.strip(),
                    )
                )
                duration_hint = float(getattr(info, "duration", 0.0) or 0.0)
                if progress and duration_hint > 0:
                    fraction = min(1.0, float(segment.end) / duration_hint)
                    progress(
                        "transcribing",
                        25 + int(fraction * 50),
                        f"Transcribed {idx} segments",
                    )
            whisper_elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "whisper.inference.complete segments=%s elapsed_ms=%.1f",
                len(segments),
                whisper_elapsed_ms,
            )
            diarization_started = time.perf_counter()
            if cancel_check and cancel_check():
                raise TranscriptionCancelled()
            if progress:
                progress("diarizing", 78, "Identifying speakers")
            logger.info(
                "diarization.start provider=%s segments=%s",
                self.diarizer.name,
                len(segments),
            )
            segments = self.diarizer.assign_speakers(audio_path, segments)
            logger.info(
                "diarization.complete provider=%s speakers=%s elapsed_ms=%.1f",
                self.diarizer.name,
                len({segment.speaker for segment in segments}),
                (time.perf_counter() - diarization_started) * 1000,
            )
            if progress:
                progress("diarizing", 95, "Speaker identification complete")
        except HTTPException:
            logger.exception("transcription.pipeline.failed")
            raise
        except TranscriptionCancelled:
            logger.info("transcription.pipeline.cancelled")
            raise
        except Exception as exc:
            logger.exception("transcription.pipeline.failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Transcription failed: {exc}",
            ) from exc

        duration = float(getattr(info, "duration", 0.0) or 0.0)
        language = str(getattr(info, "language", "zh") or "zh")
        logger.info(
            "transcription.pipeline.complete language=%s duration_seconds=%.2f total_elapsed_ms=%.1f",
            language,
            duration,
            (time.perf_counter() - started) * 1000,
        )

        return TranscriptionResponse(
            language=language,
            duration=round(duration, 2),
            segments=segments,
        )

    _transcribe_path = transcribe_path
