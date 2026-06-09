from pathlib import Path

import pytest
from fastapi import HTTPException

from app.diarization import MockDiarizer, PyannoteDiarizer, create_diarizer
from app.schemas import TranscriptSegment


def segment(segment_id: int, start: float, end: float) -> TranscriptSegment:
    return TranscriptSegment(
        id=segment_id,
        start=start,
        end=end,
        speaker="Unknown",
        text=f"segment {segment_id}",
    )


def test_mock_diarizer_alternates_speakers():
    segments = [segment(1, 0, 1), segment(2, 1, 2), segment(3, 2, 3)]

    result = MockDiarizer().assign_speakers(Path("sample.wav"), segments)

    assert [item.speaker for item in result] == [
        "Speaker A",
        "Speaker B",
        "Speaker A",
    ]


def test_pyannote_best_speaker_uses_total_overlap():
    turns = [
        (0.0, 2.0, "SPEAKER_00"),
        (2.0, 8.0, "SPEAKER_01"),
        (8.0, 9.0, "SPEAKER_00"),
    ]

    assert PyannoteDiarizer._best_speaker(1.0, 8.5, turns) == "SPEAKER_01"


def test_pyannote_best_speaker_uses_nearest_turn_without_overlap():
    turns = [(0.0, 2.0, "SPEAKER_00"), (8.0, 10.0, "SPEAKER_01")]

    assert PyannoteDiarizer._best_speaker(6.5, 7.0, turns) == "SPEAKER_01"


def test_pyannote_assigns_stable_display_names():
    class Turn:
        def __init__(self, start, end):
            self.start = start
            self.end = end

    class Annotation:
        def itertracks(self, yield_label=False):
            assert yield_label is True
            yield Turn(0.0, 2.0), None, "SPEAKER_03"
            yield Turn(2.0, 4.0), None, "SPEAKER_07"
            yield Turn(4.0, 6.0), None, "SPEAKER_03"

    class Pipeline:
        def __call__(self, audio_path):
            assert audio_path.endswith("sample.wav")
            return Annotation()

    segments = [segment(1, 0, 2), segment(2, 2, 4), segment(3, 4, 6)]
    diarizer = PyannoteDiarizer("model", token=None, pipeline=Pipeline())

    result = diarizer.assign_speakers(Path("sample.wav"), segments)

    assert [item.speaker for item in result] == [
        "Speaker A",
        "Speaker B",
        "Speaker A",
    ]


def test_pyannote_supports_new_output_wrapper():
    class Turn:
        start = 0.0
        end = 2.0

    class Annotation:
        def itertracks(self, yield_label=False):
            assert yield_label is True
            yield Turn(), None, "SPEAKER_00"

    class Output:
        speaker_diarization = Annotation()

    class Pipeline:
        def __call__(self, audio_path):
            return Output()

    segments = [segment(1, 0, 2)]
    diarizer = PyannoteDiarizer("model", token=None, pipeline=Pipeline())

    assert diarizer.assign_speakers(Path("sample.wav"), segments)[0].speaker == "Speaker A"


def test_pyannote_requires_token_before_loading_pipeline():
    diarizer = PyannoteDiarizer("model", token=None)

    with pytest.raises(HTTPException) as exc_info:
        diarizer._load_pipeline()

    assert exc_info.value.status_code == 503
    assert "HUGGINGFACE_API_KEY" in exc_info.value.detail


def test_diarizer_factory_selects_provider():
    assert isinstance(
        create_diarizer("mock", model="model", token=None, device="cuda"),
        MockDiarizer,
    )
    assert isinstance(
        create_diarizer("pyannote", model="model", token="token", device="cuda"),
        PyannoteDiarizer,
    )

    with pytest.raises(ValueError, match="Unsupported diarization provider"):
        create_diarizer("unknown", model="model", token=None, device="cuda")
