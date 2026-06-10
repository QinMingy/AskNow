import time
import wave

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app, get_stream_session_manager
from app.schemas import StreamSessionCreateRequest, TranscriptSegment
from app.stream_processing import (
    build_raw_pcm_wav,
    build_pcm_wav_window,
    FunASRStreamProcessor,
    ProcessingAudioChunk,
    resolve_funasr_model_path,
    TranscriptRevisionTracker,
    WhisperStreamFinalizer,
    WhisperStreamProcessor,
)
from app.streaming import AudioChunk, StreamSessionManager


def create_session(manager: StreamSessionManager):
    return manager.create(
        StreamSessionCreateRequest(
            mime_type="audio/webm;codecs=opus",
            sample_rate=48000,
            channels=1,
            chunk_duration_ms=1000,
        )
    )


def test_stream_buffer_tracks_backpressure_and_consumption():
    manager = StreamSessionManager(
        max_buffer_ms=4000,
        warning_ms=1000,
        degraded_ms=3000,
    )
    created = create_session(manager)

    first = manager.add_chunk(
        created.session_id,
        sequence=1,
        duration_ms=1000,
        payload=b"chunk-1",
    )
    third = manager.add_chunk(
        created.session_id,
        sequence=2,
        duration_ms=2000,
        payload=b"chunk-2",
    )

    assert first.backpressure == "warning"
    assert third.backpressure == "degraded"
    assert third.queued_ms == 3000
    assert third.received_chunks == 2

    consumed = manager.consume_next(created.session_id)
    status = manager.get_status(created.session_id)

    assert consumed.sequence == 1
    assert status.queued_ms == 2000
    assert status.backpressure == "warning"


def test_stream_buffer_rejects_out_of_order_and_overflow():
    manager = StreamSessionManager(max_buffer_ms=2000, warning_ms=1000, degraded_ms=1500)
    created = create_session(manager)
    manager.add_chunk(
        created.session_id,
        sequence=4,
        duration_ms=1000,
        payload=b"chunk-4",
    )

    with pytest.raises(HTTPException, match="sequence must be greater"):
        manager.add_chunk(
            created.session_id,
            sequence=4,
            duration_ms=1000,
            payload=b"duplicate",
        )

    with pytest.raises(HTTPException) as exc_info:
        manager.add_chunk(
            created.session_id,
            sequence=5,
            duration_ms=1500,
            payload=b"overflow",
        )

    assert exc_info.value.status_code == 429
    assert manager.get_status(created.session_id).dropped_chunks == 1


def test_stream_buffer_rejects_oversized_binary_chunk():
    manager = StreamSessionManager(max_chunk_bytes=8)
    created = create_session(manager)

    with pytest.raises(HTTPException) as exc_info:
        manager.add_chunk(
            created.session_id,
            sequence=1,
            duration_ms=1000,
            payload=b"too-large",
        )

    assert exc_info.value.status_code == 413


def test_closed_stream_rejects_new_audio():
    manager = StreamSessionManager()
    created = create_session(manager)

    stopped = manager.stop(created.session_id)

    assert stopped.state == "stopped"
    with pytest.raises(HTTPException) as exc_info:
        manager.add_chunk(
            created.session_id,
            sequence=1,
            duration_ms=1000,
            payload=b"audio",
        )
    assert exc_info.value.status_code == 409


def test_stream_websocket_protocol_and_stop():
    manager = StreamSessionManager(max_buffer_ms=3000, warning_ms=1000, degraded_ms=2000)
    created = create_session(manager)
    app.dependency_overrides[get_stream_session_manager] = lambda: manager
    client = TestClient(app)

    try:
        with client.websocket_connect(created.websocket_url) as websocket:
            ready = websocket.receive_json()
            assert ready["type"] == "session_ready"
            assert ready["session"]["state"] == "connected"

            websocket.send_json({"type": "audio_chunk", "sequence": 1, "duration_ms": 1000})
            websocket.send_bytes(b"first-audio-chunk")
            buffered = websocket.receive_json()
            pressure = websocket.receive_json()

            assert buffered["type"] == "buffer_status"
            assert buffered["session"]["queued_ms"] == 1000
            assert pressure["type"] == "backpressure"
            assert pressure["level"] == "warning"

            websocket.send_json({"type": "stop"})
            stopped = websocket.receive_json()
            assert stopped["type"] == "session_stopped"
            assert stopped["session"]["state"] == "stopped"
    finally:
        app.dependency_overrides.clear()

    assert manager.get_status(created.session_id).state == "stopped"


def test_stream_session_rest_lifecycle():
    manager = StreamSessionManager()
    app.dependency_overrides[get_stream_session_manager] = lambda: manager
    client = TestClient(app)

    try:
        created = client.post(
            "/api/stream/sessions",
            json={
                "mime_type": "audio/webm;codecs=opus",
                "sample_rate": 48000,
                "channels": 1,
                "chunk_duration_ms": 1000,
            },
        )
        session_id = created.json()["session_id"]
        status = client.get(f"/api/stream/sessions/{session_id}")
        stopped = client.post(f"/api/stream/sessions/{session_id}/stop")
    finally:
        app.dependency_overrides.clear()

    assert created.status_code == 201
    assert status.json()["state"] == "created"
    assert stopped.json()["state"] == "stopped"


def test_stream_websocket_reports_protocol_errors():
    manager = StreamSessionManager()
    created = create_session(manager)
    app.dependency_overrides[get_stream_session_manager] = lambda: manager
    client = TestClient(app)

    try:
        with client.websocket_connect(created.websocket_url) as websocket:
            websocket.receive_json()
            websocket.send_bytes(b"missing-metadata")
            error = websocket.receive_json()

            assert error == {
                "type": "error",
                "code": "unexpected_binary",
                "detail": "Send audio_chunk metadata before its binary payload.",
            }
    finally:
        app.dependency_overrides.clear()

    assert manager.get_status(created.session_id).state == "cancelled"


def test_disconnected_stream_releases_worker_capacity():
    class FakeProcessor:
        def process(self, chunks, *, mime_type, window_start_ms):
            return []

    manager = StreamSessionManager(processor=FakeProcessor(), worker_count=1)
    first = create_session(manager)
    first_session = manager._get(first.session_id)

    manager.connect(first.session_id)
    manager.add_chunk(
        first.session_id,
        sequence=1,
        duration_ms=200,
        payload=b"audio",
    )
    manager.disconnect(first.session_id)
    first_session.worker_future.result(timeout=1)

    second = create_session(manager)
    second_session = manager._get(second.session_id)
    manager.disconnect(second.session_id)
    second_session.worker_future.result(timeout=1)

    assert manager.get_status(first.session_id).state == "cancelled"
    assert manager.get_status(first.session_id).queued_ms == 0
    assert first_session.recording == []
    assert manager.get_status(second.session_id).state == "cancelled"
    manager.shutdown()


def test_stream_websocket_reports_full_backpressure():
    manager = StreamSessionManager(max_buffer_ms=1000, warning_ms=500, degraded_ms=800)
    created = create_session(manager)
    app.dependency_overrides[get_stream_session_manager] = lambda: manager
    client = TestClient(app)

    try:
        with client.websocket_connect(created.websocket_url) as websocket:
            websocket.receive_json()
            websocket.send_json({"type": "audio_chunk", "sequence": 1, "duration_ms": 1000})
            websocket.send_bytes(b"first")
            websocket.receive_json()
            websocket.receive_json()

            websocket.send_json({"type": "audio_chunk", "sequence": 2, "duration_ms": 1000})
            websocket.send_bytes(b"overflow")
            rejected = websocket.receive_json()
            pressure = websocket.receive_json()

            assert rejected["type"] == "error"
            assert rejected["code"] == "chunk_rejected"
            assert pressure["type"] == "backpressure"
            assert pressure["level"] == "full"
    finally:
        app.dependency_overrides.clear()


def test_revision_tracker_promotes_stable_partial_to_final():
    tracker = TranscriptRevisionTracker(finalize_delay_ms=8000, stable_revisions=2)
    segments = [
        TranscriptSegment(id=1, start=0.0, end=1.0, speaker="Unknown", text="稳定字幕")
    ]

    first_final, first_partial = tracker.update(
        segments,
        window_start_ms=0,
        audio_end_ms=1000,
    )
    second_final, second_partial = tracker.update(
        segments,
        window_start_ms=0,
        audio_end_ms=2000,
    )

    assert not first_final
    assert first_partial[0].final is False
    assert second_final[0].final is True
    assert not second_partial


def test_revision_tracker_finalizes_old_segments_by_time():
    tracker = TranscriptRevisionTracker(finalize_delay_ms=3000, stable_revisions=9)

    finalized, partial = tracker.update(
        [TranscriptSegment(id=1, start=0.0, end=1.0, speaker="Unknown", text="较早字幕")],
        window_start_ms=0,
        audio_end_ms=5000,
    )

    assert finalized[0].final is True
    assert not partial


def test_stream_worker_consumes_chunks_and_publishes_transcript_events():
    class FakeProcessor:
        def process(self, chunks, *, mime_type, window_start_ms):
            return [
                TranscriptSegment(
                    id=1,
                    start=0.0,
                    end=sum(chunk.duration_ms for chunk in chunks) / 1000,
                    speaker="Unknown",
                    text="流式测试字幕",
                )
            ]

    manager = StreamSessionManager(
        processor=FakeProcessor(),
        finalize_delay_ms=8000,
        stable_revisions=2,
    )
    created = create_session(manager)
    manager.add_chunk(
        created.session_id,
        sequence=1,
        duration_ms=1000,
        payload=b"audio",
    )

    deadline = time.time() + 2
    events = []
    while time.time() < deadline:
        event = manager.wait_for_event(created.session_id, timeout=0.1)
        if event:
            events.append(event)
        if any(event["type"] == "transcript_partial" for event in events):
            break

    status = manager.get_status(created.session_id)
    partial = next(event for event in events if event["type"] == "transcript_partial")

    assert status.processed_chunks == 1
    assert status.queued_ms == 0
    assert partial["segments"][0]["text"] == "流式测试字幕"
    assert partial["segments"][0]["final"] is False
    manager.shutdown()


def test_stream_worker_batches_small_transport_chunks_before_inference():
    class FakeProcessor:
        def __init__(self):
            self.windows = []

        def process(self, chunks, *, mime_type, window_start_ms):
            self.windows.append([chunk.sequence for chunk in chunks])
            return []

    processor = FakeProcessor()
    manager = StreamSessionManager(processor=processor, process_interval_ms=1000)
    created = create_session(manager)

    for sequence in range(1, 5):
        manager.add_chunk(
            created.session_id,
            sequence=sequence,
            duration_ms=200,
            payload=b"audio",
        )
    time.sleep(0.1)
    assert processor.windows == []

    manager.add_chunk(
        created.session_id,
        sequence=5,
        duration_ms=200,
        payload=b"audio",
    )

    deadline = time.time() + 2
    while time.time() < deadline and not processor.windows:
        time.sleep(0.01)

    assert processor.windows == [[1, 2, 3, 4, 5]]
    manager.shutdown()


def test_stream_websocket_pushes_incremental_transcript_without_client_polling():
    class FakeProcessor:
        def process(self, chunks, *, mime_type, window_start_ms):
            return [
                TranscriptSegment(
                    id=1,
                    start=0.0,
                    end=1.0,
                    speaker="Unknown",
                    text="主动推送字幕",
                )
            ]

    manager = StreamSessionManager(processor=FakeProcessor())
    created = create_session(manager)
    app.dependency_overrides[get_stream_session_manager] = lambda: manager
    client = TestClient(app)

    try:
        with client.websocket_connect(created.websocket_url) as websocket:
            websocket.receive_json()
            websocket.send_json({"type": "audio_chunk", "sequence": 1, "duration_ms": 1000})
            websocket.send_bytes(b"audio")

            events = []
            for _ in range(8):
                event = websocket.receive_json()
                events.append(event)
                if event["type"] == "transcript_partial":
                    break
    finally:
        app.dependency_overrides.clear()
        manager.shutdown()

    transcript = next(event for event in events if event["type"] == "transcript_partial")
    assert transcript["segments"][0]["text"] == "主动推送字幕"


def test_websocket_stop_waits_for_final_transcript_before_closing():
    class FakeProcessor:
        def process(self, chunks, *, mime_type, window_start_ms):
            time.sleep(0.05)
            return [
                TranscriptSegment(
                    id=1,
                    start=0.0,
                    end=1.0,
                    speaker="Unknown",
                    text="停止前最终字幕",
                )
            ]

    manager = StreamSessionManager(processor=FakeProcessor(), stop_timeout_seconds=2)
    created = create_session(manager)
    app.dependency_overrides[get_stream_session_manager] = lambda: manager
    client = TestClient(app)

    try:
        with client.websocket_connect(created.websocket_url) as websocket:
            websocket.receive_json()
            websocket.send_json({"type": "audio_chunk", "sequence": 1, "duration_ms": 1000})
            websocket.send_bytes(b"audio")
            websocket.send_json({"type": "stop"})

            events = []
            while True:
                event = websocket.receive_json()
                events.append(event)
                if event["type"] == "session_stopped":
                    break
    finally:
        app.dependency_overrides.clear()
        manager.shutdown()

    event_types = [event["type"] for event in events]
    assert "transcript_final" in event_types
    assert event_types.index("transcript_final") < event_types.index("session_stopped")


def test_stopped_pcm_stream_emits_offline_transcript_and_speaker_revision():
    class FakeIncrementalProcessor:
        incremental = True

        def create_session(self, **kwargs):
            return {}

        def process_incremental(self, chunks, **kwargs):
            return [
                TranscriptSegment(
                    id=1,
                    start=0,
                    end=0.2,
                    speaker="Speaker pending",
                    text="live draft",
                )
            ]

    class FakeFinalizer:
        def finalize(self, chunks, *, sample_rate, channels):
            assert len(chunks) == 1
            assert sample_rate == 16000
            assert channels == 1
            return [
                TranscriptSegment(
                    id=1,
                    start=0,
                    end=0.2,
                    speaker="Speaker A",
                    text="refined transcript",
                )
            ]

    manager = StreamSessionManager(
        processor=FakeIncrementalProcessor(),
        finalizer=FakeFinalizer(),
        process_interval_ms=200,
    )
    created = manager.create(
        StreamSessionCreateRequest(
            mime_type="audio/pcm;format=s16le",
            sample_rate=16000,
            channels=1,
            chunk_duration_ms=200,
        )
    )
    manager.add_chunk(
        created.session_id,
        sequence=1,
        duration_ms=200,
        payload=b"\x00\x00" * 3200,
    )
    manager.stop_and_wait(created.session_id)

    events = []
    while event := manager.wait_for_event(created.session_id, timeout=0.01):
        events.append(event)
        manager.acknowledge_event(created.session_id)

    revision = next(event for event in events if event["type"] == "transcript_revision")
    assert revision["replace_all"] is True
    assert revision["segments"][0]["speaker"] == "Speaker A"
    assert revision["segments"][0]["text"] == "refined transcript"
    assert manager._get(created.session_id).recording == []
    manager.shutdown()


def test_whisper_stream_finalizer_builds_pcm_wav_for_offline_pipeline():
    seen = {}

    class FakeResponse:
        segments = [
            TranscriptSegment(
                id=1,
                start=0,
                end=0.2,
                speaker="Speaker A",
                text="refined",
            )
        ]

    class FakeTranscriber:
        def transcribe_path(self, path):
            with wave.open(str(path), "rb") as source:
                seen["channels"] = source.getnchannels()
                seen["sample_rate"] = source.getframerate()
                seen["frames"] = source.readframes(source.getnframes())
            return FakeResponse()

    finalizer = WhisperStreamFinalizer(FakeTranscriber())
    result = finalizer.finalize(
        [ProcessingAudioChunk(1, 200, b"\x01\x00" * 3200)],
        sample_rate=16000,
        channels=1,
    )

    assert result[0].speaker == "Speaker A"
    assert seen == {
        "channels": 1,
        "sample_rate": 16000,
        "frames": b"\x01\x00" * 3200,
    }


def test_build_raw_pcm_wav_rejects_empty_recording():
    with pytest.raises(ValueError, match="At least one raw PCM chunk"):
        build_raw_pcm_wav([], sample_rate=16000, channels=1)


def test_whisper_stream_processor_writes_encoded_window_to_temporary_file():
    seen = {}

    class FakeTranscriber:
        def transcribe_stream_path(self, path):
            seen["suffix"] = path.suffix
            seen["payload"] = path.read_bytes()
            return []

    processor = WhisperStreamProcessor(FakeTranscriber())
    processor.process(
        [
            ProcessingAudioChunk(sequence=1, duration_ms=1000, payload=b"first"),
            ProcessingAudioChunk(sequence=2, duration_ms=1000, payload=b"second"),
        ],
        mime_type="audio/webm;codecs=opus",
        window_start_ms=0,
    )

    assert seen == {"suffix": ".webm", "payload": b"firstsecond"}


def test_funasr_stream_processor_uses_raw_pcm_and_per_session_cache():
    calls = []

    class FakeModel:
        def generate(self, **kwargs):
            calls.append(kwargs)
            kwargs["cache"]["seen"] = True
            return [{"text": "实时识别"}]

    processor = FunASRStreamProcessor(
        model_factory=lambda **_: FakeModel(),
        hotwords="AskNow 人机共生",
    )
    first_state = processor.create_session(
        mime_type="audio/pcm;format=s16le",
        sample_rate=16000,
        channels=1,
    )
    second_state = processor.create_session(
        mime_type="audio/pcm;format=s16le",
        sample_rate=16000,
        channels=1,
    )
    segments = processor.process_incremental(
        [ProcessingAudioChunk(1, 200, b"\x00\x00" * 3200)],
        state=first_state,
        mime_type="audio/pcm;format=s16le",
        window_start_ms=0,
        is_final=False,
    )

    assert segments[0].text == "实时识别"
    assert segments[0].speaker == "Speaker pending"
    assert calls[0]["input"].shape == (3200,)
    assert calls[0]["chunk_size"] == [0, 10, 5]
    assert calls[0]["hotword"] == "AskNow 人机共生"
    assert first_state.cache == {"seen": True}
    assert second_state.cache == {}


def test_funasr_stream_processor_rejects_non_pcm_or_wrong_audio_shape():
    processor = FunASRStreamProcessor(model_factory=lambda **_: object())

    with pytest.raises(ValueError, match="raw PCM16"):
        processor.create_session(mime_type="audio/wav", sample_rate=16000, channels=1)
    with pytest.raises(ValueError, match="16 kHz mono"):
        processor.create_session(
            mime_type="audio/pcm;format=s16le",
            sample_rate=48000,
            channels=1,
        )


def test_funasr_model_resolution_prefers_complete_local_cache(monkeypatch, tmp_path):
    model_dir = (
        tmp_path
        / ".cache"
        / "modelscope"
        / "hub"
        / "models"
        / "iic"
        / "speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online"
    )
    model_dir.mkdir(parents=True)
    (model_dir / "config.yaml").write_text("model: ParaformerStreaming", encoding="utf-8")
    (model_dir / "model.pt").write_bytes(b"model")
    (model_dir / "tokens.json").write_text("[]", encoding="utf-8")
    (model_dir / "am.mvn").write_bytes(b"mvn")
    monkeypatch.setattr("app.stream_processing.Path.home", lambda: tmp_path)

    assert resolve_funasr_model_path("paraformer-zh-streaming") == str(model_dir)
    with pytest.raises(FileNotFoundError, match="FUNASR_OFFLINE_ONLY"):
        resolve_funasr_model_path("another-model", offline_only=True)
    assert (
        resolve_funasr_model_path("another-model", offline_only=False)
        == "another-model"
    )


def test_funasr_model_resolution_rejects_missing_local_model(monkeypatch, tmp_path):
    monkeypatch.setattr("app.stream_processing.Path.home", lambda: tmp_path)

    with pytest.raises(FileNotFoundError, match="Automatic download is disabled"):
        resolve_funasr_model_path("paraformer-zh-streaming", offline_only=True)


def test_funasr_processor_downloads_missing_model_with_explicit_downloader(
    monkeypatch,
    tmp_path,
):
    downloaded = tmp_path / "downloaded-model"
    downloaded.mkdir()
    for filename in ("config.yaml", "model.pt", "tokens.json", "am.mvn"):
        (downloaded / filename).write_bytes(b"content")
    calls = []

    def downloader(repository, revision):
        calls.append((repository, revision))
        return str(downloaded)

    class FakeModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr("app.stream_processing.Path.home", lambda: tmp_path)
    processor = FunASRStreamProcessor(
        offline_only=False,
        model_factory=FakeModel,
        model_downloader=downloader,
    )

    model = processor._get_model()

    assert calls == [
        ("iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online", "master")
    ]
    assert model.kwargs["model"] == str(downloaded)


def test_stream_manager_commits_incremental_processor_results():
    class FakeIncrementalProcessor:
        incremental = True

        def create_session(self, **kwargs):
            return {"calls": 0}

        def process_incremental(self, chunks, *, state, mime_type, window_start_ms, is_final):
            state["calls"] += 1
            return [
                TranscriptSegment(
                    id=1,
                    start=0,
                    end=sum(chunk.duration_ms for chunk in chunks) / 1000,
                    speaker="Unknown",
                    text="增量结果",
                )
            ]

    manager = StreamSessionManager(
        processor=FakeIncrementalProcessor(),
        process_interval_ms=600,
    )
    created = manager.create(
        StreamSessionCreateRequest(
            mime_type="audio/pcm;format=s16le",
            sample_rate=16000,
            channels=1,
            chunk_duration_ms=200,
        )
    )
    for sequence in range(1, 4):
        manager.add_chunk(
            created.session_id,
            sequence=sequence,
            duration_ms=200,
            payload=b"\x00\x00" * 3200,
        )

    deadline = time.time() + 2
    events = []
    while time.time() < deadline:
        event = manager.wait_for_event(created.session_id, timeout=0.1)
        if event:
            events.append(event)
        if any(item["type"] == "transcript_final" for item in events):
            break

    final = next(item for item in events if item["type"] == "transcript_final")
    status = manager.get_status(created.session_id)
    assert final["segments"][0]["text"] == "增量结果"
    assert final["segments"][0]["start"] == 0.0
    assert final["segments"][0]["end"] == 0.6
    assert status.final_segments == 1
    manager.shutdown()


def test_stream_manager_keeps_incremental_inference_batches_bounded():
    class FakeIncrementalProcessor:
        incremental = True

        def __init__(self):
            self.batches = []

        def create_session(self, **kwargs):
            return {}

        def process_incremental(self, chunks, **kwargs):
            self.batches.append(sum(chunk.duration_ms for chunk in chunks))
            return []

    processor = FakeIncrementalProcessor()
    manager = StreamSessionManager(processor=processor, process_interval_ms=600)
    created = manager.create(
        StreamSessionCreateRequest(
            mime_type="audio/pcm;format=s16le",
            sample_rate=16000,
            channels=1,
            chunk_duration_ms=200,
        )
    )
    session = manager._get(created.session_id)
    with manager._lock:
        for sequence in range(1, 7):
            session.chunks.append(AudioChunk(sequence, 200, b"\x00\x00"))
            session.queued_ms += 200

    first = manager._consume_available(session)
    second = manager._consume_available(session)

    assert sum(chunk.duration_ms for chunk in first) == 600
    assert sum(chunk.duration_ms for chunk in second) == 600
    manager.shutdown()


def test_stream_manager_warms_up_processor_once():
    class WarmableProcessor:
        def __init__(self):
            self.calls = 0

        def prepare(self):
            self.calls += 1

    processor = WarmableProcessor()
    manager = StreamSessionManager(processor=processor)

    manager.warm_up()
    manager.warm_up()
    manager._warmup_future.result(timeout=1)

    assert processor.calls == 1
    manager.shutdown()


def test_stream_manager_finalizes_incremental_provider_after_idle_stop():
    class FinalizableProcessor:
        incremental = True

        def create_session(self, **kwargs):
            return {"finalized": False}

        def process_incremental(self, chunks, **kwargs):
            return []

        def finalize_session(self, *, state):
            state["finalized"] = True
            return [
                TranscriptSegment(
                    id=1,
                    start=0,
                    end=0.4,
                    speaker="Speaker pending",
                    text="provider final result",
                )
            ]

    manager = StreamSessionManager(
        processor=FinalizableProcessor(),
        process_interval_ms=200,
    )
    created = manager.create(
        StreamSessionCreateRequest(
            mime_type="audio/pcm;format=s16le",
            sample_rate=16000,
            channels=1,
            chunk_duration_ms=200,
        )
    )
    manager.add_chunk(
        created.session_id,
        sequence=1,
        duration_ms=200,
        payload=b"\x00\x00" * 3200,
    )
    deadline = time.time() + 2
    while time.time() < deadline and manager.get_status(created.session_id).processed_chunks < 1:
        time.sleep(0.01)

    manager.stop_and_wait(created.session_id)
    events = []
    while event := manager.wait_for_event(created.session_id, timeout=0.01):
        events.append(event)
        manager.acknowledge_event(created.session_id)

    final = next(event for event in events if event["type"] == "transcript_final")
    assert final["segments"][0]["text"] == "provider final result"
    assert manager._get(created.session_id).processor_state["finalized"] is True
    manager.shutdown()


def test_pcm_wav_window_combines_independently_decodable_chunks():
    import io
    import wave

    def wav_chunk(samples):
        output = io.BytesIO()
        with wave.open(output, "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(16000)
            target.writeframes(samples)
        return output.getvalue()

    combined = build_pcm_wav_window(
        [
            ProcessingAudioChunk(1, 1000, wav_chunk(b"\x01\x00" * 4)),
            ProcessingAudioChunk(2, 1000, wav_chunk(b"\x02\x00" * 3)),
        ]
    )

    with wave.open(io.BytesIO(combined), "rb") as source:
        assert source.getnchannels() == 1
        assert source.getframerate() == 16000
        assert source.getnframes() == 7
        assert source.readframes(7) == b"\x01\x00" * 4 + b"\x02\x00" * 3


def test_pcm_wav_window_rejects_mismatched_formats_and_invalid_audio():
    import io
    import wave

    def wav_chunk(sample_rate):
        output = io.BytesIO()
        with wave.open(output, "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(sample_rate)
            target.writeframes(b"\x00\x00" * 4)
        return output.getvalue()

    with pytest.raises(ValueError, match="formats must match"):
        build_pcm_wav_window(
            [
                ProcessingAudioChunk(1, 1000, wav_chunk(16000)),
                ProcessingAudioChunk(2, 1000, wav_chunk(48000)),
            ]
        )

    with pytest.raises(ValueError, match="Invalid PCM WAV"):
        build_pcm_wav_window([ProcessingAudioChunk(1, 1000, b"not-a-wav")])


def test_stream_event_queue_discards_oldest_event_when_full():
    manager = StreamSessionManager()
    created = create_session(manager)
    session = manager._get(created.session_id)

    for index in range(105):
        manager._publish(session, "test_event", index=index)

    events = []
    while event := manager.wait_for_event(created.session_id, timeout=0.01):
        events.append(event)

    assert len(events) == 100
    assert events[0]["index"] == 5
