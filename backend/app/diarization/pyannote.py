from pathlib import Path

from fastapi import HTTPException, status

from ..schemas import TranscriptSegment


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
                    "Pyannote speaker diarization requires HF_TOKEN. Accept access for "
                    "`pyannote/segmentation-3.0` and `pyannote/speaker-diarization-3.1`, "
                    "then set the HF_TOKEN environment variable."
                ),
            )

        try:
            import torch
            from pyannote.audio import Pipeline

            self._pipeline = Pipeline.from_pretrained(
                self.model,
                use_auth_token=self.token,
            )
            if self._pipeline is None:
                raise RuntimeError(
                    "Pipeline download returned no model. Verify gated-model access."
                )
            self._pipeline.to(torch.device(self.device))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Unable to initialize pyannote speaker diarization. Verify HF_TOKEN, "
                    "accepted model conditions, network access, and GPU environment. "
                    f"Original error: {exc}"
                ),
            ) from exc

        return self._pipeline

    def assign_speakers(
        self,
        audio_path: Path,
        segments: list[TranscriptSegment],
    ) -> list[TranscriptSegment]:
        if not segments:
            return segments

        try:
            diarization = self._load_pipeline()(str(audio_path))
            turns = [
                (float(turn.start), float(turn.end), str(speaker))
                for turn, _, speaker in diarization.itertracks(yield_label=True)
            ]
        except HTTPException:
            raise
        except Exception as exc:
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
