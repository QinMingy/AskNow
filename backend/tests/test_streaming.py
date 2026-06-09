import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app, get_stream_session_manager
from app.schemas import StreamSessionCreateRequest
from app.streaming import StreamSessionManager


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

    assert manager.get_status(created.session_id).state == "created"


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
