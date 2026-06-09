from datetime import datetime
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


TaskStage = Literal[
    "queued",
    "uploading",
    "downloading",
    "waiting_for_gpu",
    "transcribing",
    "diarizing",
    "completed",
    "failed",
    "cancelled",
]


class TaskCreatedResponse(BaseModel):
    task_id: str
    status_url: str
    result_url: str


class TaskStatusResponse(BaseModel):
    task_id: str
    stage: TaskStage
    progress: int
    message: str
    cancel_requested: bool
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


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
    provider: str
    title: str
    summary: str
    bullets: list[str]
    caution: str


class AssistProviderStatus(BaseModel):
    provider: str
    ready: bool
    mode: str
    required: list[str]
    missing: list[str]
    details: list[str]
    next_step: str


class HealthResponse(BaseModel):
    status: str
    service: str
    api_version: str
    asr_engine: str
    device: str
    diarization_provider: str
    assist_provider: str
    supported_video_sources: list[str]
    browser_cookie_sources: list[str]
