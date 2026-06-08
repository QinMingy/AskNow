from functools import lru_cache

from fastapi import Depends, FastAPI, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, get_settings
from .assistant import UnderstandingAssistant
from .schemas import AssistRequest, AssistResponse, HealthResponse, TranscriptionResponse, VideoUrlRequest
from .sources import SourceRegistry, create_default_registry
from .transcriber import WhisperTranscriber

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


@lru_cache
def get_transcriber() -> WhisperTranscriber:
    return WhisperTranscriber(get_settings())


@lru_cache
def get_source_registry() -> SourceRegistry:
    return create_default_registry(get_settings())


@lru_cache
def get_understanding_assistant() -> UnderstandingAssistant:
    return UnderstandingAssistant()


@app.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        api_version=app.version,
        asr_engine="faster-whisper",
        device=settings.whisper_device,
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
