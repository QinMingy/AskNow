import asyncio
import json
import logging
import queue
import threading
import time
import uuid
from contextlib import nullcontext
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, WebSocket, WebSocketDisconnect, status

from .schemas import (
    BackpressureLevel,
    IncrementalTranscriptSegment,
    StreamSessionCreateRequest,
    StreamSessionCreatedResponse,
    StreamSessionState,
    StreamSessionStatusResponse,
)
from .gpu import GpuScheduler
from .stream_processing import (
    ProcessingAudioChunk,
    StreamProcessor,
    TranscriptRevisionTracker,
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
    processed_chunks: int = 0
    processed_ms: int = 0
    history: deque[AudioChunk] = field(default_factory=deque)
    history_ms: int = 0
    recording: list[AudioChunk] = field(default_factory=list)
    events: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=100))
    wake_worker: threading.Event = field(default_factory=threading.Event)
    worker_future: Future | None = None
    transcript: TranscriptRevisionTracker | None = None
    processor_state: object | None = None
    processor_finalized: bool = False
    refinement_attempted: bool = False
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
        processor: StreamProcessor | None = None,
        finalizer=None,
        gpu_scheduler: GpuScheduler | None = None,
        window_ms: int = 20000,
        process_interval_ms: int = 1000,
        finalize_delay_ms: int = 8000,
        stable_revisions: int = 2,
        worker_count: int = 2,
        stop_timeout_seconds: float = 30.0,
        refinement_timeout_seconds: float = 600.0,
    ):
        self.max_buffer_ms = max(1000, max_buffer_ms)
        self.max_chunk_bytes = max(1, max_chunk_bytes)
        self.warning_ms = max(0, min(warning_ms, self.max_buffer_ms))
        self.degraded_ms = max(
            self.warning_ms,
            min(degraded_ms, self.max_buffer_ms),
        )
        self.retention = timedelta(seconds=max(60, retention_seconds))
        self.processor = processor
        self.finalizer = finalizer
        self.gpu_scheduler = gpu_scheduler or GpuScheduler(1)
        self.window_ms = max(1000, window_ms)
        self.process_interval_ms = max(100, process_interval_ms)
        self.finalize_delay_ms = max(0, finalize_delay_ms)
        self.stable_revisions = max(1, stable_revisions)
        self.stop_timeout_seconds = max(0.1, stop_timeout_seconds)
        self.refinement_timeout_seconds = max(
            self.stop_timeout_seconds,
            refinement_timeout_seconds,
        )
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, worker_count),
            thread_name_prefix="stream-processor",
        )
        self._sessions: dict[str, StreamSession] = {}
        self._lock = threading.RLock()
        self._warmup_future: Future | None = None

    def warm_up(self) -> None:
        if self.processor is None or not hasattr(self.processor, "prepare"):
            return
        with self._lock:
            if self._warmup_future is None:
                logger.debug("stream.processor.warmup.submitted")
                self._warmup_future = self._executor.submit(self._warm_up_processor)

    @property
    def processor_ready(self) -> bool:
        if self.processor is None:
            return True
        return bool(getattr(self.processor, "ready", True))

    def _warm_up_processor(self) -> None:
        logger.info("stream.processor.warmup.start")
        try:
            self.processor.prepare()
        except Exception:
            logger.exception("stream.processor.warmup.failed")
        else:
            logger.info("stream.processor.warmup.complete")

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
            transcript=TranscriptRevisionTracker(
                finalize_delay_ms=self.finalize_delay_ms,
                stable_revisions=self.stable_revisions,
            ),
        )
        if self.processor is not None and getattr(self.processor, "incremental", False):
            try:
                session.processor_state = self.processor.create_session(
                    mime_type=session.mime_type,
                    sample_rate=session.sample_rate,
                    channels=session.channels,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        with self._lock:
            self._sessions[session.session_id] = session
            if self.processor is not None:
                session.worker_future = self._executor.submit(
                    self._run_worker,
                    session.session_id,
                )
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
                self._mark_closed(session, "cancelled")
                self._discard_audio(session)
                session.wake_worker.set()
        logger.info(
            "stream.session.disconnected session_id=%s state=%s",
            session_id,
            session.state,
        )

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
            session.wake_worker.set()
            response = self._status(session)
        logger.debug(
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
        return self._close(session_id, "stopped", finalize=True)

    def cancel(self, session_id: str) -> StreamSessionStatusResponse:
        return self._close(session_id, "cancelled", finalize=False)

    def stop_and_wait(self, session_id: str) -> StreamSessionStatusResponse:
        status_response = self.stop(session_id)
        session = self._get(session_id)
        if session.worker_future is not None:
            try:
                timeout = (
                    self.refinement_timeout_seconds
                    if self.finalizer is not None
                    else self.stop_timeout_seconds
                )
                session.worker_future.result(timeout=timeout)
            except FutureTimeoutError:
                logger.warning(
                    "stream.session.stop_timeout session_id=%s timeout_seconds=%s",
                    session_id,
                    timeout,
                )
        return self.get_status(session_id) if status_response.state == "stopped" else status_response

    def get_status(self, session_id: str) -> StreamSessionStatusResponse:
        session = self._get(session_id)
        with self._lock:
            return self._status(session)

    def shutdown(self) -> None:
        with self._lock:
            for session in self._sessions.values():
                if session.state not in {"stopped", "cancelled"}:
                    self._mark_closed(session, "cancelled")
                    session.wake_worker.set()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def wait_for_event(self, session_id: str, timeout: float = 0.5) -> dict | None:
        session = self._get(session_id)
        try:
            return session.events.get(timeout=timeout)
        except queue.Empty:
            return None

    def acknowledge_event(self, session_id: str) -> None:
        self._get(session_id).events.task_done()

    def wait_for_events_sent(self, session_id: str) -> None:
        session = self._get(session_id)
        deadline = time.monotonic() + self.stop_timeout_seconds
        while session.events.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)

    def _close(
        self,
        session_id: str,
        state: StreamSessionState,
        *,
        finalize: bool,
    ) -> StreamSessionStatusResponse:
        session = self._get(session_id)
        with self._lock:
            if session.state not in {"stopped", "cancelled"}:
                if finalize and session.transcript is not None:
                    finalized = session.transcript.finalize_all()
                    if finalized:
                        self._publish(
                            session,
                            "transcript_final",
                            revision=session.transcript.revision,
                            segments=[item.model_dump(mode="json") for item in finalized],
                        )
                self._mark_closed(session, state)
                if state == "cancelled":
                    self._discard_audio(session)
                session.wake_worker.set()
            response = self._status(session)
        logger.info("stream.session.%s session_id=%s", response.state, session_id)
        return response

    @staticmethod
    def _mark_closed(session: StreamSession, state: StreamSessionState) -> None:
        now = utc_now()
        session.state = state
        session.updated_at = now
        session.stopped_at = now

    @staticmethod
    def _discard_audio(session: StreamSession) -> None:
        session.chunks.clear()
        session.queued_ms = 0
        session.history.clear()
        session.history_ms = 0
        session.recording.clear()

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
            processed_chunks=session.processed_chunks,
            processed_ms=session.processed_ms,
            revision=session.transcript.revision if session.transcript else 0,
            final_segments=len(session.transcript.final_segments) if session.transcript else 0,
            partial_segments=len(session.transcript.partial_segments) if session.transcript else 0,
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

    def _run_worker(self, session_id: str) -> None:
        session = self._get(session_id)
        while True:
            session.wake_worker.wait(timeout=0.5)
            session.wake_worker.clear()
            try:
                consumed = self._consume_available(session)
                if consumed:
                    self._publish(
                        session,
                        "buffer_status",
                        session=self.get_status(session.session_id).model_dump(mode="json"),
                    )
                    self._process_window(session, consumed)
            except Exception as exc:
                logger.exception("stream.worker.failed session_id=%s", session_id)
                self._publish(session, "processing_error", detail=str(exc))
            with self._lock:
                should_close = session.state in {"stopped", "cancelled"} and not session.chunks
                should_refine = (
                    session.state == "stopped"
                    and self.finalizer is not None
                    and not session.refinement_attempted
                )
                should_finalize_processor = (
                    session.state == "stopped"
                    and self.processor is not None
                    and hasattr(self.processor, "finalize_session")
                    and not session.processor_finalized
                )
                if should_finalize_processor:
                    session.processor_finalized = True
                if should_refine:
                    session.refinement_attempted = True
            if should_finalize_processor:
                self._finalize_processor_session(session)
            if should_refine:
                self._refine_complete_recording(session)
            if should_close:
                return

    def _consume_available(self, session: StreamSession) -> list[AudioChunk]:
        consumed = []
        with self._lock:
            if session.state not in {"stopped", "cancelled"} and session.queued_ms < self.process_interval_ms:
                return consumed
            incremental = self.processor is not None and getattr(
                self.processor,
                "incremental",
                False,
            )
            while session.chunks:
                chunk = session.chunks.popleft()
                consumed.append(chunk)
                session.queued_ms = max(0, session.queued_ms - chunk.duration_ms)
                session.processed_chunks += 1
                session.processed_ms += chunk.duration_ms
                session.history.append(chunk)
                session.history_ms += chunk.duration_ms
                session.recording.append(chunk)
                if (
                    incremental
                    and session.state not in {"stopped", "cancelled"}
                    and sum(item.duration_ms for item in consumed) >= self.process_interval_ms
                ):
                    break
            if session.chunks:
                session.wake_worker.set()
            while session.history and session.history_ms > self.window_ms:
                removed = session.history.popleft()
                session.history_ms -= removed.duration_ms
            session.updated_at = utc_now()
        return consumed

    def _process_window(self, session: StreamSession, consumed: list[AudioChunk]) -> None:
        if self.processor is None or session.transcript is None:
            return
        incremental = getattr(self.processor, "incremental", False)
        source_chunks = consumed if incremental else session.history
        chunks = [
            ProcessingAudioChunk(chunk.sequence, chunk.duration_ms, chunk.payload)
            for chunk in source_chunks
        ]
        window_start_ms = (
            max(0, session.processed_ms - sum(chunk.duration_ms for chunk in consumed))
            if incremental
            else max(0, session.processed_ms - session.history_ms)
        )
        processor_ready = getattr(self.processor, "ready", True)
        self._publish(
            session,
            "processing_status",
            state="processing" if processor_ready else "initializing",
        )
        try:
            scheduler = (
                self.gpu_scheduler.acquire()
                if bool(getattr(self.processor, "uses_local_gpu", True))
                else nullcontext()
            )
            with scheduler:
                if incremental:
                    segments = self.processor.process_incremental(
                        chunks,
                        state=session.processor_state,
                        mime_type=session.mime_type,
                        window_start_ms=window_start_ms,
                        is_final=session.state == "stopped",
                    )
                else:
                    segments = self.processor.process(
                        chunks,
                        mime_type=session.mime_type,
                        window_start_ms=window_start_ms,
                    )
            if incremental:
                newly_final = session.transcript.commit(
                    segments,
                    window_start_ms=window_start_ms,
                )
                partial = []
            else:
                newly_final, partial = session.transcript.update(
                    segments,
                    window_start_ms=window_start_ms,
                    audio_end_ms=session.processed_ms,
                )
            with self._lock:
                stopped = session.state == "stopped"
                cancelled = session.state == "cancelled"
            if cancelled:
                return
            if stopped:
                newly_final.extend(session.transcript.finalize_all())
                partial = []
            if newly_final:
                self._publish(
                    session,
                    "transcript_final",
                    revision=session.transcript.revision,
                    segments=[item.model_dump(mode="json") for item in newly_final],
                )
            self._publish(
                session,
                "transcript_partial",
                revision=session.transcript.revision,
                segments=[item.model_dump(mode="json") for item in partial],
            )
        except Exception as exc:
            logger.exception("stream.processing.failed session_id=%s", session.session_id)
            self._publish(session, "processing_error", detail=str(exc))
        finally:
            self._publish(session, "processing_status", state="idle")

    def _finalize_processor_session(self, session: StreamSession) -> None:
        if session.transcript is None:
            return
        logger.info("stream.processor.finalize.start session_id=%s", session.session_id)
        try:
            segments = self.processor.finalize_session(state=session.processor_state)
            newly_final = session.transcript.commit(segments, window_start_ms=0)
            if newly_final:
                self._publish(
                    session,
                    "transcript_final",
                    revision=session.transcript.revision,
                    segments=[item.model_dump(mode="json") for item in newly_final],
                )
        except Exception as exc:
            logger.exception("stream.processor.finalize.failed session_id=%s", session.session_id)
            self._publish(session, "processing_error", detail=str(exc))
        else:
            logger.info(
                "stream.processor.finalize.complete session_id=%s segments=%s",
                session.session_id,
                len(segments),
            )

    def _refine_complete_recording(self, session: StreamSession) -> None:
        if "pcm" not in session.mime_type.lower():
            logger.warning(
                "stream.refinement.skipped session_id=%s reason=unsupported_mime mime_type=%s",
                session.session_id,
                session.mime_type,
            )
            session.recording.clear()
            return
        chunks = [
            ProcessingAudioChunk(chunk.sequence, chunk.duration_ms, chunk.payload)
            for chunk in session.recording
        ]
        if not chunks:
            return
        logger.info(
            "stream.refinement.start session_id=%s duration_ms=%s",
            session.session_id,
            session.processed_ms,
        )
        self._publish(session, "refinement_status", state="processing")
        try:
            scheduler = (
                self.gpu_scheduler.acquire()
                if bool(getattr(self.finalizer, "uses_local_gpu", True))
                else nullcontext()
            )
            with scheduler:
                refined = self.finalizer.finalize(
                    chunks,
                    sample_rate=session.sample_rate,
                    channels=session.channels,
                )
        except Exception as exc:
            logger.exception("stream.refinement.failed session_id=%s", session.session_id)
            self._publish(session, "refinement_error", detail=str(exc))
            self._publish(session, "refinement_status", state="failed")
            session.recording.clear()
            return
        session.transcript.revision += 1
        session.transcript.final_segments = [
            IncrementalTranscriptSegment(
                id=f"refined-{segment.id}",
                start=segment.start,
                end=segment.end,
                speaker=segment.speaker,
                text=segment.text,
                revision=session.transcript.revision,
                final=True,
            )
            for segment in refined
        ]
        session.transcript.partial_segments = []
        self._publish(
            session,
            "transcript_revision",
            revision=session.transcript.revision,
            replace_all=True,
            segments=[
                item.model_dump(mode="json") for item in session.transcript.final_segments
            ],
        )
        self._publish(session, "refinement_status", state="complete")
        logger.info(
            "stream.refinement.complete session_id=%s segments=%s speakers=%s",
            session.session_id,
            len(refined),
            len({segment.speaker for segment in refined}),
        )
        session.recording.clear()

    @staticmethod
    def _publish(record: StreamSession, event_type: str, **payload) -> None:
        event = {"type": event_type, **payload}
        try:
            record.events.put_nowait(event)
        except queue.Full:
            try:
                record.events.get_nowait()
                record.events.task_done()
            except queue.Empty:
                pass
            record.events.put_nowait(event)


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
    event_task = asyncio.create_task(_pump_stream_events(websocket, session_id, manager))

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
        event_task.cancel()
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
        stopped = await asyncio.to_thread(manager.stop_and_wait, session_id)
        await asyncio.to_thread(manager.wait_for_events_sent, session_id)
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


async def _pump_stream_events(
    websocket: WebSocket,
    session_id: str,
    manager: StreamSessionManager,
) -> None:
    while True:
        event = await asyncio.to_thread(manager.wait_for_event, session_id, 0.5)
        if event is not None:
            try:
                await websocket.send_json(event)
            finally:
                manager.acknowledge_event(session_id)
