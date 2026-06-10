import gzip
import json
import logging
import struct
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from .schemas import TranscriptSegment
from .stream_processing import ProcessingAudioChunk

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
DEFAULT_RESOURCE_ID = "volc.bigasr.sauc.duration"

CLIENT_FULL_REQUEST = 0b0001
CLIENT_AUDIO_ONLY_REQUEST = 0b0010
SERVER_FULL_RESPONSE = 0b1001
SERVER_ERROR_RESPONSE = 0b1111
FLAG_LAST_PACKET = 0b0010
SERIALIZATION_NONE = 0b0000
SERIALIZATION_JSON = 0b0001
COMPRESSION_NONE = 0b0000
COMPRESSION_GZIP = 0b0001


@dataclass
class VolcengineStreamSessionState:
    connection: object
    sample_rate: int
    channels: int
    emitted_utterances: set[tuple[int, int, str]] = field(default_factory=set)
    next_segment_id: int = 1
    finalized: bool = False


class VolcengineStreamProcessor:
    """Native Volcengine big-model streaming ASR client."""

    incremental = True
    uses_local_gpu = False

    def __init__(
        self,
        *,
        app_id: str,
        access_token: str,
        resource_id: str = DEFAULT_RESOURCE_ID,
        endpoint: str = DEFAULT_ENDPOINT,
        language: str = "zh-CN",
        receive_timeout_seconds: float = 0.15,
        final_timeout_seconds: float = 5.0,
        vad_end_window_ms: int = 800,
        connection_factory: Callable | None = None,
    ):
        if not app_id.strip():
            raise ValueError("VOLCENGINE_APP_ID is required for the Volcengine stream provider.")
        if not access_token.strip():
            raise ValueError(
                "VOLCENGINE_ACCESS_TOKEN is required for the Volcengine stream provider."
            )
        if not resource_id.strip():
            raise ValueError(
                "VOLCENGINE_RESOURCE_ID is required for the Volcengine stream provider."
            )
        self.app_id = app_id
        self.access_token = access_token
        self.resource_id = resource_id
        self.endpoint = endpoint
        self.language = language
        self.receive_timeout_seconds = max(0.01, receive_timeout_seconds)
        self.final_timeout_seconds = max(
            self.receive_timeout_seconds,
            final_timeout_seconds,
        )
        self.vad_end_window_ms = max(100, vad_end_window_ms)
        self._connection_factory = connection_factory

    @property
    def ready(self) -> bool:
        return True

    def prepare(self) -> None:
        logger.info(
            "volcengine.stream.ready endpoint=%s resource_id=%s",
            self.endpoint,
            self.resource_id,
        )

    def create_session(self, *, mime_type: str, sample_rate: int, channels: int):
        if "pcm" not in mime_type.lower():
            raise ValueError("Volcengine live ASR requires raw PCM16 audio.")
        if sample_rate != 16000 or channels != 1:
            raise ValueError("Volcengine live ASR requires 16 kHz mono audio.")
        connection_id = uuid.uuid4().hex
        headers = {
            "X-Api-App-Key": self.app_id,
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Connect-Id": connection_id,
        }
        logger.info(
            "volcengine.stream.connect.start connect_id=%s endpoint=%s",
            connection_id,
            self.endpoint,
        )
        connection = self._connect(headers)
        connection.send(
            encode_full_request(
                build_full_request(
                    sample_rate=sample_rate,
                    channels=channels,
                    language=self.language,
                    vad_end_window_ms=self.vad_end_window_ms,
                )
            )
        )
        logger.info("volcengine.stream.connect.complete connect_id=%s", connection_id)
        return VolcengineStreamSessionState(
            connection=connection,
            sample_rate=sample_rate,
            channels=channels,
        )

    def process_incremental(
        self,
        chunks: list[ProcessingAudioChunk],
        *,
        state: VolcengineStreamSessionState,
        mime_type: str,
        window_start_ms: int,
        is_final: bool,
    ) -> list[TranscriptSegment]:
        if not chunks:
            return []
        payload = b"".join(chunk.payload for chunk in chunks)
        if len(payload) % 2:
            raise ValueError("Raw PCM16 payload must contain complete 16-bit samples.")
        state.connection.send(encode_audio_request(payload, final=is_final))
        timeout = self.final_timeout_seconds if is_final else self.receive_timeout_seconds
        try:
            responses = receive_responses(
                state.connection,
                timeout=timeout,
                wait_for_final=is_final,
            )
            segments = make_segments_relative(
                extract_final_segments(responses, state),
                window_start_ms=window_start_ms,
            )
        except Exception:
            self._close(state.connection)
            raise
        logger.debug(
            "volcengine.stream.batch chunks=%s bytes=%s responses=%s segments=%s final=%s",
            len(chunks),
            len(payload),
            len(responses),
            len(segments),
            is_final,
        )
        if is_final:
            state.finalized = True
            self._close(state.connection)
        return segments

    def finalize_session(
        self,
        *,
        state: VolcengineStreamSessionState,
    ) -> list[TranscriptSegment]:
        if state.finalized:
            return []
        try:
            state.connection.send(encode_audio_request(b"", final=True))
            responses = receive_responses(
                state.connection,
                timeout=self.final_timeout_seconds,
                wait_for_final=True,
            )
            return extract_final_segments(responses, state)
        finally:
            state.finalized = True
            self._close(state.connection)

    def _connect(self, headers: dict[str, str]):
        if self._connection_factory is not None:
            return self._connection_factory(self.endpoint, headers)
        from websockets.sync.client import connect

        return connect(
            self.endpoint,
            additional_headers=headers,
            open_timeout=10,
            close_timeout=3,
        )

    @staticmethod
    def _close(connection) -> None:
        try:
            connection.close()
        except Exception:
            logger.debug("volcengine.stream.close.failed", exc_info=True)


def build_full_request(
    *,
    sample_rate: int,
    channels: int,
    language: str,
    vad_end_window_ms: int,
) -> dict:
    return {
        "user": {"uid": uuid.uuid4().hex},
        "audio": {
            "format": "pcm",
            "rate": sample_rate,
            "bits": 16,
            "channel": channels,
            "codec": "raw",
        },
        "request": {
            "model_name": "bigmodel",
            "language": language,
            "enable_itn": True,
            "enable_punc": True,
            "result_type": "full",
            "show_utterances": True,
            "vad": {
                "vad_enable": True,
                "end_window_size": vad_end_window_ms,
            },
        },
    }


def encode_full_request(payload: dict) -> bytes:
    compressed = gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return _frame(
        message_type=CLIENT_FULL_REQUEST,
        flags=0,
        serialization=SERIALIZATION_JSON,
        compression=COMPRESSION_GZIP,
        payload=compressed,
    )


def encode_audio_request(payload: bytes, *, final: bool) -> bytes:
    compressed = gzip.compress(payload)
    return _frame(
        message_type=CLIENT_AUDIO_ONLY_REQUEST,
        flags=FLAG_LAST_PACKET if final else 0,
        serialization=SERIALIZATION_NONE,
        compression=COMPRESSION_GZIP,
        payload=compressed,
    )


def _frame(
    *,
    message_type: int,
    flags: int,
    serialization: int,
    compression: int,
    payload: bytes,
) -> bytes:
    header = bytes(
        (
            0x11,
            (message_type << 4) | flags,
            (serialization << 4) | compression,
            0x00,
        )
    )
    return header + struct.pack(">I", len(payload)) + payload


def decode_response(frame: bytes) -> tuple[int, int, dict]:
    if len(frame) < 8:
        raise ValueError("Volcengine response frame is incomplete.")
    header_size = (frame[0] & 0x0F) * 4
    message_type = frame[1] >> 4
    flags = frame[1] & 0x0F
    serialization = frame[2] >> 4
    compression = frame[2] & 0x0F
    offset = header_size
    if message_type == SERVER_FULL_RESPONSE and flags & 0b0001:
        offset += 4
    if message_type == SERVER_ERROR_RESPONSE:
        offset += 4
    if len(frame) < offset + 4:
        raise ValueError("Volcengine response payload size is missing.")
    payload_size = struct.unpack(">I", frame[offset : offset + 4])[0]
    payload = frame[offset + 4 : offset + 4 + payload_size]
    if len(payload) != payload_size:
        raise ValueError("Volcengine response payload is incomplete.")
    if compression == COMPRESSION_GZIP and payload:
        payload = gzip.decompress(payload)
    if serialization == SERIALIZATION_JSON and payload:
        decoded = json.loads(payload.decode("utf-8"))
    else:
        decoded = {"raw": payload.decode("utf-8", errors="replace")}
    return message_type, flags, decoded


def receive_responses(connection, *, timeout: float, wait_for_final: bool) -> list[dict]:
    responses = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            frame = connection.recv(timeout=max(0.01, deadline - time.monotonic()))
        except TimeoutError:
            break
        if isinstance(frame, str):
            payload = json.loads(frame)
            message_type = SERVER_FULL_RESPONSE
        else:
            message_type, _, payload = decode_response(frame)
        if message_type == SERVER_ERROR_RESPONSE:
            raise RuntimeError(f"Volcengine streaming ASR error: {payload}")
        responses.append(payload)
        if wait_for_final and is_final_response(payload):
            break
        if not wait_for_final:
            continue
    return responses


def is_final_response(payload: dict) -> bool:
    return payload.get("type") == "final"


def extract_final_segments(
    responses: list[dict],
    state: VolcengineStreamSessionState,
) -> list[TranscriptSegment]:
    segments = []
    for payload in responses:
        for utterance in _utterances(payload):
            text = str(utterance.get("text", "")).strip()
            if not text or not utterance.get("definite", payload.get("type") == "final"):
                continue
            start_ms = int(utterance.get("start_time", utterance.get("start", 0)) or 0)
            end_ms = int(utterance.get("end_time", utterance.get("end", start_ms)) or start_ms)
            key = (start_ms, end_ms, text)
            if key in state.emitted_utterances:
                continue
            state.emitted_utterances.add(key)
            segments.append(
                TranscriptSegment(
                    id=state.next_segment_id,
                    start=start_ms / 1000,
                    end=max(start_ms, end_ms) / 1000,
                    speaker="Speaker pending",
                    text=text,
                )
            )
            state.next_segment_id += 1
    return segments


def _utterances(payload: dict) -> list[dict]:
    result = payload.get("result")
    if isinstance(result, dict):
        utterances = result.get("utterances")
        if isinstance(utterances, list):
            return utterances
        if result.get("text"):
            return [result]
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    return []


def make_segments_relative(
    segments: list[TranscriptSegment],
    *,
    window_start_ms: int,
) -> list[TranscriptSegment]:
    offset = window_start_ms / 1000
    return [
        segment.model_copy(
            update={
                "start": round(segment.start - offset, 3),
                "end": round(segment.end - offset, 3),
            }
        )
        for segment in segments
    ]
