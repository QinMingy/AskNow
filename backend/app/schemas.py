from typing import Literal

from pydantic import BaseModel


class TranscriptSegment(BaseModel):
    id: int
    start: float
    end: float
    speaker: str
    text: str


class SourceMetadata(BaseModel):
    provider: str
    title: str | None = None
    webpage_url: str


class TranscriptionResponse(BaseModel):
    language: str
    duration: float
    segments: list[TranscriptSegment]
    source: SourceMetadata | None = None


class VideoUrlRequest(BaseModel):
    url: str
    browser: Literal["edge", "chrome", "firefox"] | None = None


AssistAction = Literal[
    "explain",
    "conflict",
    "question",
    "catchup",
    "actions",
]


class AssistRequest(BaseModel):
    action: AssistAction
    segments: list[TranscriptSegment]
    window_seconds: int = 60


class AssistResponse(BaseModel):
    action: AssistAction
    title: str
    summary: str
    bullets: list[str]
    caution: str


class HealthResponse(BaseModel):
    status: str
    service: str
    api_version: str
    asr_engine: str
    device: str
    supported_video_sources: list[str]
    browser_cookie_sources: list[str]
