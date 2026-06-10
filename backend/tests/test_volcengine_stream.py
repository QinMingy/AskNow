import gzip
import json
import struct

import pytest

from app.stream_processing import ProcessingAudioChunk
from app.volcengine_stream import (
    CLIENT_AUDIO_ONLY_REQUEST,
    CLIENT_FULL_REQUEST,
    COMPRESSION_GZIP,
    SERVER_ERROR_RESPONSE,
    SERVER_FULL_RESPONSE,
    SERIALIZATION_JSON,
    VolcengineStreamProcessor,
    decode_response,
    encode_audio_request,
    encode_full_request,
)


class FakeConnection:
    def __init__(self, responses=None):
        self.sent = []
        self.responses = list(responses or [])
        self.closed = False

    def send(self, payload):
        self.sent.append(payload)

    def recv(self, timeout):
        if not self.responses:
            raise TimeoutError()
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def response_frame(payload, *, message_type=SERVER_FULL_RESPONSE):
    encoded = gzip.compress(json.dumps(payload).encode("utf-8"))
    return (
        bytes((0x11, message_type << 4, (SERIALIZATION_JSON << 4) | COMPRESSION_GZIP, 0))
        + (struct.pack(">I", 40000000) if message_type == SERVER_ERROR_RESPONSE else b"")
        + struct.pack(">I", len(encoded))
        + encoded
    )


def test_volcengine_protocol_encodes_full_request_and_audio():
    full = encode_full_request({"request": {"model_name": "bigmodel"}})
    audio = encode_audio_request(b"\x00\x00" * 10, final=True)

    assert full[1] >> 4 == CLIENT_FULL_REQUEST
    assert audio[1] >> 4 == CLIENT_AUDIO_ONLY_REQUEST
    assert audio[1] & 0x0F == 0b0010
    assert audio[2] & 0x0F == COMPRESSION_GZIP


def test_volcengine_protocol_decodes_response_and_errors():
    payload = {"result": {"text": "课堂内容"}}

    message_type, _, decoded = decode_response(response_frame(payload))

    assert message_type == SERVER_FULL_RESPONSE
    assert decoded == payload

    with pytest.raises(ValueError, match="incomplete"):
        decode_response(b"\x11")


def test_volcengine_stream_processor_reuses_connection_and_emits_final_utterance():
    responses = [
        response_frame(
            {
                "type": "result",
                "result": {
                    "utterances": [
                        {
                            "text": "这是最终字幕",
                            "start_time": 1100,
                            "end_time": 1900,
                            "definite": True,
                        }
                    ]
                },
            }
        )
    ]
    connection = FakeConnection(responses)
    seen = {}

    def connect(endpoint, headers):
        seen["endpoint"] = endpoint
        seen["headers"] = headers
        return connection

    processor = VolcengineStreamProcessor(
        app_id="app-id",
        access_token="access-token",
        connection_factory=connect,
    )
    state = processor.create_session(
        mime_type="audio/pcm;format=s16le",
        sample_rate=16000,
        channels=1,
    )
    segments = processor.process_incremental(
        [ProcessingAudioChunk(1, 200, b"\x00\x00" * 3200)],
        state=state,
        mime_type="audio/pcm;format=s16le",
        window_start_ms=1000,
        is_final=False,
    )

    assert seen["headers"]["X-Api-App-Key"] == "app-id"
    assert seen["headers"]["X-Api-Access-Key"] == "access-token"
    assert len(connection.sent) == 2
    assert segments[0].text == "这是最终字幕"
    assert segments[0].start == 0.1
    assert segments[0].end == 0.9
    assert segments[0].speaker == "Speaker pending"


def test_volcengine_stream_processor_deduplicates_and_closes_final_session():
    final = response_frame(
        {
            "type": "final",
            "result": {
                "utterances": [
                    {
                        "text": "同一句字幕",
                        "start_time": 0,
                        "end_time": 200,
                        "definite": True,
                    }
                ]
            },
        }
    )
    connection = FakeConnection([final, final])
    processor = VolcengineStreamProcessor(
        app_id="app-id",
        access_token="access-token",
        connection_factory=lambda *_: connection,
    )
    state = processor.create_session(
        mime_type="audio/pcm;format=s16le",
        sample_rate=16000,
        channels=1,
    )

    first = processor.process_incremental(
        [ProcessingAudioChunk(1, 200, b"\x00\x00" * 3200)],
        state=state,
        mime_type="audio/pcm;format=s16le",
        window_start_ms=0,
        is_final=False,
    )
    second = processor.process_incremental(
        [ProcessingAudioChunk(2, 200, b"\x00\x00" * 3200)],
        state=state,
        mime_type="audio/pcm;format=s16le",
        window_start_ms=200,
        is_final=True,
    )

    assert len(first) == 1
    assert second == []
    assert connection.closed is True


def test_volcengine_stream_processor_finalizes_idle_session():
    connection = FakeConnection(
        [
            response_frame(
                {
                    "type": "final",
                    "result": {
                        "utterances": [
                            {
                                "text": "停止后的最后一句",
                                "start_time": 200,
                                "end_time": 600,
                                "definite": True,
                            }
                        ]
                    },
                }
            )
        ]
    )
    processor = VolcengineStreamProcessor(
        app_id="app-id",
        access_token="access-token",
        connection_factory=lambda *_: connection,
    )
    state = processor.create_session(
        mime_type="audio/pcm;format=s16le",
        sample_rate=16000,
        channels=1,
    )

    segments = processor.finalize_session(state=state)

    assert segments[0].text == "停止后的最后一句"
    assert connection.sent[-1][1] & 0x0F == 0b0010
    assert connection.closed is True


def test_volcengine_stream_processor_validates_credentials_and_audio_shape():
    with pytest.raises(ValueError, match="VOLCENGINE_APP_ID"):
        VolcengineStreamProcessor(app_id="", access_token="token")

    processor = VolcengineStreamProcessor(
        app_id="app-id",
        access_token="access-token",
        connection_factory=lambda *_: FakeConnection(),
    )
    with pytest.raises(ValueError, match="16 kHz mono"):
        processor.create_session(
            mime_type="audio/pcm;format=s16le",
            sample_rate=48000,
            channels=1,
        )


def test_volcengine_stream_processor_raises_server_error():
    connection = FakeConnection(
        [response_frame({"message": "denied"}, message_type=SERVER_ERROR_RESPONSE)]
    )
    processor = VolcengineStreamProcessor(
        app_id="app-id",
        access_token="access-token",
        connection_factory=lambda *_: connection,
    )
    state = processor.create_session(
        mime_type="audio/pcm;format=s16le",
        sample_rate=16000,
        channels=1,
    )

    with pytest.raises(RuntimeError, match="denied"):
        processor.process_incremental(
            [ProcessingAudioChunk(1, 200, b"\x00\x00" * 3200)],
            state=state,
            mime_type="audio/pcm;format=s16le",
            window_start_ms=0,
            is_final=False,
        )
    assert connection.closed is True
