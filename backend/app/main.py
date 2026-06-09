import logging
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from tempfile import mkdtemp

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, status
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
    TaskCreatedResponse,
    TaskStatusResponse,
    TranscriptionResponse,
    VideoUrlRequest,
)
from .sources import SourceRegistry, create_default_registry
from .tasks import TaskManager
from .transcriber import WhisperTranscriber

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    if get_task_manager.cache_info().currsize:
        logger.info("task_manager.shutdown")
        get_task_manager().shutdown()


app = FastAPI(
    title="Classroom Comprehension Assistant API",
    version="0.4.0",
    lifespan=lifespan,
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


@lru_cache
def get_task_manager() -> TaskManager:
    settings = get_settings()
    return TaskManager(
        worker_count=settings.task_worker_count,
        gpu_concurrency=settings.gpu_task_concurrency,
        retention_seconds=settings.task_retention_seconds,
    )


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


@app.post(
    "/api/tasks/transcribe",
    response_model=TaskCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_audio_task(
    file: UploadFile,
    transcriber: WhisperTranscriber = Depends(get_transcriber),
    task_manager: TaskManager = Depends(get_task_manager),
    settings: Settings = Depends(get_settings),
) -> TaskCreatedResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in settings.allowed_extensions:
        allowed = ", ".join(sorted(settings.allowed_extensions))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported audio format `{suffix or 'unknown'}`. Supported formats: {allowed}.",
        )

    task_dir = Path(mkdtemp(prefix="classroom-assistant-task-"))
    source_path = task_dir / f"upload{suffix}"
    try:
        with source_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                output.write(chunk)
        return task_manager.submit_upload(source_path, transcriber)
    except Exception:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise
    finally:
        await file.close()


@app.post(
    "/api/tasks/transcribe-url",
    response_model=TaskCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_video_task(
    request: VideoUrlRequest,
    transcriber: WhisperTranscriber = Depends(get_transcriber),
    source_registry: SourceRegistry = Depends(get_source_registry),
    task_manager: TaskManager = Depends(get_task_manager),
) -> TaskCreatedResponse:
    return task_manager.submit_url(
        request.url,
        request.browser,
        transcriber,
        source_registry,
    )


@app.get("/api/tasks/{task_id}", response_model=TaskStatusResponse)
def task_status(
    task_id: str,
    task_manager: TaskManager = Depends(get_task_manager),
) -> TaskStatusResponse:
    return task_manager.get_status(task_id)


@app.get("/api/tasks/{task_id}/result", response_model=TranscriptionResponse)
def task_result(
    task_id: str,
    task_manager: TaskManager = Depends(get_task_manager),
) -> TranscriptionResponse:
    return task_manager.get_result(task_id)


@app.post("/api/tasks/{task_id}/cancel", response_model=TaskStatusResponse)
def cancel_task(
    task_id: str,
    task_manager: TaskManager = Depends(get_task_manager),
) -> TaskStatusResponse:
    return task_manager.cancel(task_id)


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
