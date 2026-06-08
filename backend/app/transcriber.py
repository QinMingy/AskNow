from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from fastapi import HTTPException, UploadFile, status

from .config import Settings
from .schemas import SourceMetadata, TranscriptSegment, TranscriptionResponse
from .sources.registry import SourceRegistry


class WhisperTranscriber:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model

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
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Unable to initialize faster-whisper with CUDA. "
                    "Phase 1 expects a Windows GPU environment with CUDA available. "
                    f"Original error: {exc}"
                ),
            ) from exc

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
            while chunk := await file.read(1024 * 1024):
                tmp.write(chunk)

        try:
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
        with TemporaryDirectory() as tmpdir:
            media = source_registry.resolve(url, Path(tmpdir), browser=browser)
            response = self._transcribe_path(media.media_path)
            response.source = SourceMetadata(
                provider=media.provider,
                title=media.title,
                webpage_url=media.webpage_url,
            )
            return response

    def _transcribe_path(self, audio_path: Path) -> TranscriptionResponse:
        model = self._load_model()

        try:
            segments_iter, info = model.transcribe(
                str(audio_path),
                language="zh",
                vad_filter=True,
                beam_size=5,
            )
            segments = []
            for idx, segment in enumerate(segments_iter, start=1):
                segments.append(
                    TranscriptSegment(
                        id=idx,
                        start=round(float(segment.start), 2),
                        end=round(float(segment.end), 2),
                        speaker="Speaker A" if idx % 2 else "Speaker B",
                        text=segment.text.strip(),
                    )
                )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Transcription failed: {exc}",
            ) from exc

        duration = float(getattr(info, "duration", 0.0) or 0.0)
        language = str(getattr(info, "language", "zh") or "zh")

        return TranscriptionResponse(
            language=language,
            duration=round(duration, 2),
            segments=segments,
        )
