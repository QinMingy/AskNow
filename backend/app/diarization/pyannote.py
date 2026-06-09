import logging
import time
from pathlib import Path

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
    ):
        self.model = model
        self.token = token
        self.device = device
        self._pipeline = pipeline

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

        started = time.perf_counter()
        logger.info(
            "pyannote.model_load.start model=%s device=%s",
            self.model,
            self.device,
        )
        try:
            import torch
            from pyannote.audio import Pipeline

            self._pipeline = Pipeline.from_pretrained(
                self.model,
                token=self.token,
            )
            if self._pipeline is None:
                raise RuntimeError(
                    "Pipeline download returned no model. Verify gated-model access."
                )
            self._pipeline.to(torch.device(self.device))
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("pyannote.model_load.failed model=%s", self.model)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Unable to initialize pyannote speaker diarization. Verify "
                    "HUGGINGFACE_API_KEY, accepted model conditions, network access, "
                    "and GPU environment. "
                    f"Original error: {exc}"
                ),
            ) from exc

        logger.info(
            "pyannote.model_load.complete model=%s elapsed_ms=%.1f",
            self.model,
            (time.perf_counter() - started) * 1000,
        )
        return self._pipeline

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
            output = self._load_pipeline()(str(audio_path))
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
