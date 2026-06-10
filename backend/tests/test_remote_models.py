from pathlib import Path

from app.diarization import ApiDiarizer
from app.remote_models import RemoteModelClient
from app.schemas import TranscriptSegment
from app.config import Settings
from app.stream_processing import ApiStreamProcessor, ProcessingAudioChunk
from app.transcriber import ApiTranscriber


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeHttpClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payload)


def transcript_payload(speaker="Speaker A", text="remote transcript"):
    return {
        "language": "zh",
        "duration": 1.0,
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 1.0,
                "speaker": speaker,
                "text": text,
            }
        ],
    }


def test_remote_client_posts_audio_with_bearer_auth(tmp_path):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"audio")
    http = FakeHttpClient(transcript_payload())
    client = RemoteModelClient(
        base_url="https://models.example.com/",
        api_key="secret",
        client=http,
    )

    payload = client.post_audio("/v1/audio/transcriptions", audio)

    assert payload["language"] == "zh"
    url, kwargs = http.calls[0]
    assert url == "https://models.example.com/v1/audio/transcriptions"
    assert kwargs["headers"]["Authorization"] == "Bearer secret"
    assert kwargs["files"]["file"][0] == "sample.wav"


def test_api_diarizer_uses_remote_segments(tmp_path):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"audio")

    class Client:
        def post_audio(self, path, audio_path, data=None):
            assert path == "/v1/audio/diarizations"
            assert '"speaker": "Unknown"' in data["segments"]
            return {"segments": transcript_payload()["segments"]}

    result = ApiDiarizer(Client()).assign_speakers(
        audio,
        [
            TranscriptSegment(
                id=1,
                start=0,
                end=1,
                speaker="Unknown",
                text="remote transcript",
            )
        ],
    )

    assert result[0].speaker == "Speaker A"


def test_api_stream_processor_sends_session_metadata():
    calls = []

    class Client:
        def post_audio(self, path, audio_path, data=None):
            calls.append((path, audio_path.read_bytes(), data))
            return {"segments": transcript_payload(speaker="Speaker pending")["segments"]}

    processor = ApiStreamProcessor(Client())
    state = processor.create_session(
        mime_type="audio/pcm;format=s16le",
        sample_rate=16000,
        channels=1,
    )
    result = processor.process_incremental(
        [ProcessingAudioChunk(1, 200, b"\x00\x00" * 3200)],
        state=state,
        mime_type="audio/pcm;format=s16le",
        window_start_ms=600,
        is_final=False,
    )

    assert result[0].speaker == "Speaker pending"
    assert calls[0][0] == "/v1/audio/stream-transcriptions"
    assert calls[0][2]["session_id"] == state.session_id
    assert calls[0][2]["sample_rate"] == "16000"


def test_api_transcriber_reuses_remote_asr_and_selected_diarizer(tmp_path):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"audio")

    class Client:
        def post_audio(self, path, audio_path, data=None):
            assert path == "/v1/audio/transcriptions"
            return transcript_payload(speaker="Unknown")

    class Diarizer:
        name = "test"

        def assign_speakers(self, audio_path, segments):
            segments[0].speaker = "Speaker B"
            return segments

    result = ApiTranscriber(Settings(), Diarizer(), Client()).transcribe_path(audio)

    assert result.segments[0].speaker == "Speaker B"
