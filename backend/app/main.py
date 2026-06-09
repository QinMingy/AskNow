import logging
import time
import uuid
from functools import lru_cache

from fastapi import Depends, FastAPI, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, get_settings
from .assistant import AssistProviderFactory, UnderstandingAssistant
from .diarization import create_diarizer
from .logging_config import configure_logging, request_id_var
from .provider_status import get_assist_provider_status
from .schemas import (
    AssistProviderStatus,
    AssistRequest,
    AssistResponse,
    HealthResponse,
    TranscriptionResponse,
    VideoUrlRequest,
)
from .sources import SourceRegistry, create_default_registry
from .transcriber import WhisperTranscriber

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Classroom Comprehension Assistant API",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:8]
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    logger.info("request.start method=%s path=%s", request.method, request.url.path)
    try:
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request.complete method=%s path=%s status=%s elapsed_ms=%.1f",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response
    except Exception:
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.exception(
            "request.failed method=%s path=%s elapsed_ms=%.1f",
            request.method,
            request.url.path,
            elapsed_ms,
        )
        raise
    finally:
        request_id_var.reset(token)


@lru_cache
def get_transcriber() -> WhisperTranscriber:
    settings = get_settings()
    logger.info(
        "transcriber.create whisper_model=%s whisper_device=%s diarization_provider=%s diarization_model=%s",
        settings.whisper_model,
        settings.whisper_device,
        settings.diarization_provider,
        settings.diarization_model,
    )
    diarizer = create_diarizer(
        settings.diarization_provider,
        model=settings.diarization_model,
        token=settings.huggingface_token,
        device=settings.diarization_device,
    )
    return WhisperTranscriber(settings, diarizer)


@lru_cache
def get_source_registry() -> SourceRegistry:
    return create_default_registry(get_settings())


@lru_cache
def get_understanding_assistant() -> UnderstandingAssistant:
    settings = get_settings()
    logger.info(
        "assistant.create provider=%s model=%s",
        settings.assist_provider,
        settings.assist_model or "-",
    )
    provider = AssistProviderFactory.create(
        settings.assist_provider,
        base_url=settings.assist_base_url,
        model=settings.assist_model,
        api_key=settings.assist_api_key,
        timeout_seconds=settings.assist_timeout_seconds,
    )
    return UnderstandingAssistant(provider)


@app.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        api_version=app.version,
        asr_engine="faster-whisper",
        device=settings.whisper_device,
        diarization_provider=settings.diarization_provider,
        assist_provider=settings.assist_provider,
        supported_video_sources=["YouTube", "Bilibili"],
        browser_cookie_sources=["edge", "chrome", "firefox"],
    )


@app.post("/api/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(
    file: UploadFile,
    transcriber: WhisperTranscriber = Depends(get_transcriber),
) -> TranscriptionResponse:
    return await transcriber.transcribe_upload(file)


@app.post("/api/transcribe-url", response_model=TranscriptionResponse)
def transcribe_video_url(
    request: VideoUrlRequest,
    transcriber: WhisperTranscriber = Depends(get_transcriber),
    source_registry: SourceRegistry = Depends(get_source_registry),
) -> TranscriptionResponse:
    return transcriber.transcribe_url(request.url, source_registry, browser=request.browser)


@app.post("/api/assist", response_model=AssistResponse)
def assist(
    request: AssistRequest,
    assistant: UnderstandingAssistant = Depends(get_understanding_assistant),
) -> AssistResponse:
    return assistant.assist(request)


@app.get("/api/assist/provider", response_model=AssistProviderStatus)
def assist_provider_status(
    settings: Settings = Depends(get_settings),
) -> AssistProviderStatus:
    return get_assist_provider_status(settings)
