from pathlib import Path

import pytest
from fastapi import HTTPException

from app.diarization import ApiDiarizer, MockDiarizer, PassthroughDiarizer, PyannoteDiarizer, create_diarizer
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
        def __call__(self, audio):
            assert audio == {"prepared": True}
            return Annotation()

    segments = [segment(1, 0, 2), segment(2, 2, 4), segment(3, 4, 6)]
    diarizer = PyannoteDiarizer(
        "model",
        token=None,
        pipeline=Pipeline(),
        audio_loader=lambda path: {"prepared": True},
    )

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
    diarizer = PyannoteDiarizer(
        "model",
        token=None,
        pipeline=Pipeline(),
        audio_loader=lambda path: {"prepared": True},
    )

    assert diarizer.assign_speakers(Path("sample.wav"), segments)[0].speaker == "Speaker A"


def test_pyannote_requires_token_before_loading_pipeline():
    diarizer = PyannoteDiarizer("model", token=None)

    with pytest.raises(HTTPException) as exc_info:
        diarizer._load_pipeline()

    assert exc_info.value.status_code == 503
    assert "HUGGINGFACE_API_KEY" in exc_info.value.detail


def test_pyannote_retries_transient_network_disconnect():
    calls = []
    sleeps = []

    class Pipeline:
        def to(self, device):
            self.device = device

    def factory(model, token):
        calls.append((model, token))
        if len(calls) < 3:
            raise RuntimeError("Server disconnected without sending a response.")
        return Pipeline()

    diarizer = PyannoteDiarizer(
        "model",
        token="token",
        pipeline_factory=factory,
        load_max_attempts=3,
        load_retry_backoff_seconds=0.5,
        sleep_func=sleeps.append,
    )

    pipeline = diarizer._load_pipeline()

    assert len(calls) == 3
    assert sleeps == [0.5, 1.0]
    assert pipeline.device.type == "cuda"
    assert diarizer._load_pipeline() is pipeline


def test_pyannote_does_not_retry_non_network_model_error():
    calls = []

    def factory(model, token):
        calls.append((model, token))
        raise RuntimeError("403 Client Error: access denied")

    diarizer = PyannoteDiarizer(
        "model",
        token="token",
        pipeline_factory=factory,
        load_max_attempts=3,
        sleep_func=lambda _: pytest.fail("non-network errors must not retry"),
    )

    with pytest.raises(HTTPException) as exc_info:
        diarizer._load_pipeline()

    assert len(calls) == 1
    assert exc_info.value.status_code == 503
    assert "403 Client Error" in exc_info.value.detail


def test_pyannote_network_failure_reports_retry_guidance():
    diarizer = PyannoteDiarizer(
        "model",
        token="token",
        pipeline_factory=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("Server disconnected without sending a response.")
        ),
        load_max_attempts=2,
        load_retry_backoff_seconds=0,
    )

    with pytest.raises(HTTPException) as exc_info:
        diarizer._load_pipeline()

    assert "after 2 network attempts" in exc_info.value.detail
    assert "HF_HUB_DOWNLOAD_TIMEOUT=120" in exc_info.value.detail


def test_diarizer_factory_selects_provider():
    assert isinstance(
        create_diarizer("mock", model="model", token=None, device="cuda"),
        MockDiarizer,
    )
    assert isinstance(
        create_diarizer("pyannote", model="model", token="token", device="cuda"),
        PyannoteDiarizer,
    )
    assert isinstance(
        create_diarizer(
            "api",
            model="model",
            token=None,
            device="cuda",
            api_base_url="https://models.example.com",
        ),
        ApiDiarizer,
    )
    assert isinstance(
        create_diarizer("passthrough", model="model", token=None, device="cuda"),
        PassthroughDiarizer,
    )

    with pytest.raises(ValueError, match="Unsupported diarization provider"):
        create_diarizer("unknown", model="model", token=None, device="cuda")
