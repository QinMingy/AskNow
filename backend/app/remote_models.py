import json
import logging
import time
from pathlib import Path

import httpx
from fastapi import HTTPException, status

from .schemas import TranscriptSegment, TranscriptionResponse

logger = logging.getLogger(__name__)


class RemoteModelClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout_seconds: float = 600.0,
        client: httpx.Client | None = None,
    ):
        if not base_url.strip():
            raise ValueError("Remote model API base URL is required.")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=timeout_seconds)

    def post_audio(
        self,
        path: str,
        audio_path: Path,
        *,
        data: dict[str, str] | None = None,
    ) -> dict:
        started = time.perf_counter()
        logger.info(
            "remote_model.request.start endpoint=%s bytes=%s",
            path,
            audio_path.stat().st_size,
        )
        try:
            with audio_path.open("rb") as audio:
                response = self.client.post(
                    f"{self.base_url}{path}",
                    headers=self._headers(),
                    data=data or {},
                    files={
                        "file": (
                            audio_path.name,
                            audio,
                            "application/octet-stream",
                        )
                    },
                )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.exception("remote_model.request.failed endpoint=%s", path)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Remote model API request failed for {path}: {exc}",
            ) from exc
        logger.info(
            "remote_model.request.complete endpoint=%s elapsed_ms=%.1f",
            path,
            (time.perf_counter() - started) * 1000,
        )
        return payload

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}


def parse_transcription_response(payload: dict) -> TranscriptionResponse:
    return TranscriptionResponse.model_validate(payload)


def serialize_segments(segments: list[TranscriptSegment]) -> str:
    return json.dumps(
        [segment.model_dump(mode="json") for segment in segments],
        ensure_ascii=False,
    )
