import json
import logging
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, WebSocket, WebSocketDisconnect, status

from .schemas import (
    BackpressureLevel,
    StreamSessionCreateRequest,
    StreamSessionCreatedResponse,
    StreamSessionState,
    StreamSessionStatusResponse,
)

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AudioChunk:
    sequence: int
    duration_ms: int
    payload: bytes
    received_at: datetime = field(default_factory=utc_now)


@dataclass
class StreamSession:
    session_id: str
    mime_type: str
    sample_rate: int
    channels: int
    chunk_duration_ms: int
    state: StreamSessionState = "created"
    chunks: deque[AudioChunk] = field(default_factory=deque)
    queued_ms: int = 0
    received_chunks: int = 0
    received_ms: int = 0
    dropped_chunks: int = 0
    last_sequence: int | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    connected_at: datetime | None = None
    stopped_at: datetime | None = None


class StreamSessionManager:
    def __init__(
        self,
        *,
        max_buffer_ms: int = 30000,
        max_chunk_bytes: int = 5 * 1024 * 1024,
        warning_ms: int = 5000,
        degraded_ms: int = 15000,
        retention_seconds: int = 3600,
    ):
        self.max_buffer_ms = max(1000, max_buffer_ms)
        self.max_chunk_bytes = max(1, max_chunk_bytes)
        self.warning_ms = max(0, min(warning_ms, self.max_buffer_ms))
        self.degraded_ms = max(
            self.warning_ms,
            min(degraded_ms, self.max_buffer_ms),
        )
        self.retention = timedelta(seconds=max(60, retention_seconds))
        self._sessions: dict[str, StreamSession] = {}
        self._lock = threading.RLock()

    def create(self, request: StreamSessionCreateRequest) -> StreamSessionCreatedResponse:
        self._cleanup_expired()
        if request.sample_rate <= 0 or request.channels <= 0 or request.chunk_duration_ms <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="sample_rate, channels, and chunk_duration_ms must be positive.",
            )
        if request.chunk_duration_ms > self.max_buffer_ms:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="chunk_duration_ms cannot exceed the maximum stream buffer.",
            )

        session = StreamSession(
            session_id=uuid.uuid4().hex,
            mime_type=request.mime_type,
            sample_rate=request.sample_rate,
            channels=request.channels,
            chunk_duration_ms=request.chunk_duration_ms,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        logger.info(
            "stream.session.created session_id=%s mime_type=%s sample_rate=%s channels=%s",
            session.session_id,
            session.mime_type,
            session.sample_rate,
            session.channels,
        )
        return StreamSessionCreatedResponse(
            session_id=session.session_id,
            websocket_url=f"/api/stream/sessions/{session.session_id}/ws",
            status_url=f"/api/stream/sessions/{session.session_id}",
        )

    def connect(self, session_id: str) -> StreamSessionStatusResponse:
        session = self._get(session_id)
        with self._lock:
            if session.state in {"stopped", "cancelled"}:
                raise HTTPException(status_code=409, detail="Stream session is already closed.")
            if session.state in {"connected", "active"}:
                raise HTTPException(status_code=409, detail="Stream session is already connected.")
            now = utc_now()
            session.state = "connected"
            session.connected_at = session.connected_at or now
            session.updated_at = now
            return self._status(session)

    def disconnect(self, session_id: str) -> None:
        session = self._get(session_id)
        with self._lock:
            if session.state not in {"stopped", "cancelled"}:
                session.state = "created"
                session.updated_at = utc_now()
        logger.info("stream.session.disconnected session_id=%s", session_id)

    def add_chunk(
        self,
        session_id: str,
        *,
        sequence: int,
        duration_ms: int,
        payload: bytes,
    ) -> StreamSessionStatusResponse:
        session = self._get(session_id)
        if duration_ms <= 0:
            raise HTTPException(status_code=400, detail="Audio chunk duration_ms must be positive.")
        if not payload:
            raise HTTPException(status_code=400, detail="Audio chunk payload cannot be empty.")
        if len(payload) > self.max_chunk_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Audio chunk exceeds the {self.max_chunk_bytes}-byte limit.",
            )

        with self._lock:
            if session.state in {"stopped", "cancelled"}:
                raise HTTPException(status_code=409, detail="Stream session is closed.")
            if session.last_sequence is not None and sequence <= session.last_sequence:
                raise HTTPException(
                    status_code=409,
                    detail=f"Audio chunk sequence must be greater than {session.last_sequence}.",
                )
            if session.queued_ms + duration_ms > self.max_buffer_ms:
                session.dropped_chunks += 1
                session.updated_at = utc_now()
                logger.warning(
                    "stream.chunk.dropped session_id=%s sequence=%s queued_ms=%s",
                    session_id,
                    sequence,
                    session.queued_ms,
                )
                raise HTTPException(
                    status_code=429,
                    detail="Stream audio buffer is full. Pause sending and retry.",
                )

            session.chunks.append(AudioChunk(sequence, duration_ms, payload))
            session.queued_ms += duration_ms
            session.received_chunks += 1
            session.received_ms += duration_ms
            session.last_sequence = sequence
            session.state = "active"
            session.updated_at = utc_now()
            response = self._status(session)
        logger.info(
            "stream.chunk.accepted session_id=%s sequence=%s duration_ms=%s queued_ms=%s",
            session_id,
            sequence,
            duration_ms,
            response.queued_ms,
        )
        return response

    def consume_next(self, session_id: str) -> AudioChunk | None:
        session = self._get(session_id)
        with self._lock:
            if not session.chunks:
                return None
            chunk = session.chunks.popleft()
            session.queued_ms = max(0, session.queued_ms - chunk.duration_ms)
            session.updated_at = utc_now()
            return chunk

    def stop(self, session_id: str) -> StreamSessionStatusResponse:
        return self._close(session_id, "stopped")

    def cancel(self, session_id: str) -> StreamSessionStatusResponse:
        return self._close(session_id, "cancelled")

    def get_status(self, session_id: str) -> StreamSessionStatusResponse:
        session = self._get(session_id)
        with self._lock:
            return self._status(session)

    def shutdown(self) -> None:
        with self._lock:
            for session in self._sessions.values():
                if session.state not in {"stopped", "cancelled"}:
                    self._mark_closed(session, "cancelled")

    def _close(
        self,
        session_id: str,
        state: StreamSessionState,
    ) -> StreamSessionStatusResponse:
        session = self._get(session_id)
        with self._lock:
            if session.state not in {"stopped", "cancelled"}:
                self._mark_closed(session, state)
            response = self._status(session)
        logger.info("stream.session.%s session_id=%s", response.state, session_id)
        return response

    @staticmethod
    def _mark_closed(session: StreamSession, state: StreamSessionState) -> None:
        now = utc_now()
        session.state = state
        session.updated_at = now
        session.stopped_at = now

    def _get(self, session_id: str) -> StreamSession:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Stream session not found.")
        return session

    def _status(self, session: StreamSession) -> StreamSessionStatusResponse:
        return StreamSessionStatusResponse(
            session_id=session.session_id,
            state=session.state,
            mime_type=session.mime_type,
            sample_rate=session.sample_rate,
            channels=session.channels,
            chunk_duration_ms=session.chunk_duration_ms,
            queued_chunks=len(session.chunks),
            queued_ms=session.queued_ms,
            received_chunks=session.received_chunks,
            received_ms=session.received_ms,
            dropped_chunks=session.dropped_chunks,
            last_sequence=session.last_sequence,
            backpressure=self._backpressure(session.queued_ms),
            created_at=session.created_at,
            updated_at=session.updated_at,
            connected_at=session.connected_at,
            stopped_at=session.stopped_at,
        )

    def _backpressure(self, queued_ms: int) -> BackpressureLevel:
        if queued_ms >= self.max_buffer_ms:
            return "full"
        if queued_ms >= self.degraded_ms:
            return "degraded"
        if queued_ms >= self.warning_ms:
            return "warning"
        return "normal"

    def _cleanup_expired(self) -> None:
        cutoff = utc_now() - self.retention
        with self._lock:
            expired = [
                session_id
                for session_id, session in self._sessions.items()
                if session.stopped_at is not None and session.stopped_at < cutoff
            ]
            for session_id in expired:
                del self._sessions[session_id]


async def handle_stream_websocket(
    websocket: WebSocket,
    session_id: str,
    manager: StreamSessionManager,
) -> None:
    try:
        initial = manager.connect(session_id)
    except HTTPException as exc:
        await websocket.close(code=4404 if exc.status_code == 404 else 4409)
        return

    await websocket.accept()
    await websocket.send_json(
        {
            "type": "session_ready",
            "session": initial.model_dump(mode="json"),
        }
    )
    pending_chunk: dict | None = None

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            if message.get("bytes") is not None:
                pending_chunk = await _handle_binary_frame(
                    websocket,
                    manager,
                    session_id,
                    pending_chunk,
                    message["bytes"],
                )
                continue

            text = message.get("text")
            if text is None:
                continue
            pending_chunk, should_close = await _handle_control_event(
                websocket,
                manager,
                session_id,
                pending_chunk,
                text,
            )
            if should_close:
                return
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(session_id)


async def _handle_binary_frame(
    websocket: WebSocket,
    manager: StreamSessionManager,
    session_id: str,
    pending_chunk: dict | None,
    payload: bytes,
) -> None:
    if pending_chunk is None:
        await _send_stream_error(
            websocket,
            "unexpected_binary",
            "Send audio_chunk metadata before its binary payload.",
        )
        return None

    try:
        session = manager.add_chunk(
            session_id,
            sequence=pending_chunk["sequence"],
            duration_ms=pending_chunk["duration_ms"],
            payload=payload,
        )
        await websocket.send_json(
            {
                "type": "buffer_status",
                "session": session.model_dump(mode="json"),
            }
        )
        if session.backpressure != "normal":
            await websocket.send_json(
                {
                    "type": "backpressure",
                    "level": session.backpressure,
                    "queued_ms": session.queued_ms,
                    "message": "Audio processing is falling behind incoming audio.",
                }
            )
    except HTTPException as exc:
        await _send_stream_error(websocket, "chunk_rejected", str(exc.detail))
        if exc.status_code == 429:
            session = manager.get_status(session_id)
            await websocket.send_json(
                {
                    "type": "backpressure",
                    "level": "full",
                    "queued_ms": session.queued_ms,
                    "message": "Audio buffer is full. Pause sending before retrying.",
                }
            )
    return None


async def _handle_control_event(
    websocket: WebSocket,
    manager: StreamSessionManager,
    session_id: str,
    pending_chunk: dict | None,
    text: str,
) -> tuple[dict | None, bool]:
    try:
        event = json.loads(text)
    except json.JSONDecodeError:
        await _send_stream_error(websocket, "invalid_json", "Control event must be valid JSON.")
        return pending_chunk, False
    if not isinstance(event, dict):
        await _send_stream_error(websocket, "invalid_event", "Control event must be a JSON object.")
        return pending_chunk, False

    event_type = event.get("type")
    if event_type == "audio_chunk":
        if pending_chunk is not None:
            await _send_stream_error(
                websocket,
                "missing_binary",
                "The previous audio_chunk metadata has no binary payload.",
            )
            return pending_chunk, False
        try:
            return {
                "sequence": int(event["sequence"]),
                "duration_ms": int(event["duration_ms"]),
            }, False
        except (KeyError, TypeError, ValueError):
            await _send_stream_error(
                websocket,
                "invalid_chunk_metadata",
                "audio_chunk requires integer sequence and duration_ms fields.",
            )
            return None, False
    if event_type == "ping":
        await websocket.send_json({"type": "pong"})
        return pending_chunk, False
    if event_type == "stop":
        stopped = manager.stop(session_id)
        await websocket.send_json(
            {
                "type": "session_stopped",
                "session": stopped.model_dump(mode="json"),
            }
        )
        await websocket.close(code=1000)
        return pending_chunk, True

    await _send_stream_error(
        websocket,
        "unsupported_event",
        f"Unsupported stream event: {event_type or 'missing type'}.",
    )
    return pending_chunk, False


async def _send_stream_error(websocket: WebSocket, code: str, detail: str) -> None:
    await websocket.send_json({"type": "error", "code": code, "detail": detail})
