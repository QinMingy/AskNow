import logging
import shutil
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from fastapi import HTTPException, status

from .schemas import (
    SourceMetadata,
    TaskCreatedResponse,
    TaskStage,
    TaskStatusResponse,
    TranscriptionResponse,
)
from .sources.registry import SourceRegistry
from .transcriber import TranscriptionCancelled, WhisperTranscriber

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TaskRecord:
    task_id: str
    stage: TaskStage = "queued"
    progress: int = 0
    message: str = "Task queued"
    cancel_requested: bool = False
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    result: TranscriptionResponse | None = None
    future: Future | None = None

    def status(self) -> TaskStatusResponse:
        return TaskStatusResponse(
            task_id=self.task_id,
            stage=self.stage,
            progress=self.progress,
            message=self.message,
            cancel_requested=self.cancel_requested,
            created_at=self.created_at,
            updated_at=self.updated_at,
            started_at=self.started_at,
            completed_at=self.completed_at,
            error=self.error,
        )


class TaskManager:
    def __init__(
        self,
        *,
        worker_count: int = 4,
        gpu_concurrency: int = 1,
        retention_seconds: int = 3600,
    ):
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, worker_count),
            thread_name_prefix="transcription-task",
        )
        self._gpu_slots = threading.Semaphore(max(1, gpu_concurrency))
        self._retention = timedelta(seconds=max(60, retention_seconds))
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = threading.RLock()

    def submit_upload(
        self,
        source_path: Path,
        transcriber: WhisperTranscriber,
    ) -> TaskCreatedResponse:
        task = self._create_task()
        task.future = self._executor.submit(
            self._run_upload,
            task.task_id,
            source_path,
            transcriber,
        )
        return self._created_response(task.task_id)

    def submit_url(
        self,
        url: str,
        browser: str | None,
        transcriber: WhisperTranscriber,
        source_registry: SourceRegistry,
    ) -> TaskCreatedResponse:
        task = self._create_task()
        task.future = self._executor.submit(
            self._run_url,
            task.task_id,
            url,
            browser,
            transcriber,
            source_registry,
        )
        return self._created_response(task.task_id)

    def get_status(self, task_id: str) -> TaskStatusResponse:
        task = self._get_task(task_id)
        with self._lock:
            return task.status()

    def get_result(self, task_id: str) -> TranscriptionResponse:
        task = self._get_task(task_id)
        with self._lock:
            if task.stage == "completed" and task.result is not None:
                return task.result
            if task.stage == "failed":
                raise HTTPException(status_code=500, detail=task.error or "Task failed.")
            if task.stage == "cancelled":
                raise HTTPException(status_code=409, detail="Task was cancelled.")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Task is not complete. Current stage: {task.stage}.",
            )

    def cancel(self, task_id: str) -> TaskStatusResponse:
        task = self._get_task(task_id)
        with self._lock:
            if task.stage in {"completed", "failed", "cancelled"}:
                return task.status()
            task.cancel_requested = True
            task.message = "Cancellation requested"
            task.updated_at = utc_now()
            if task.future and task.future.cancel():
                self._mark_cancelled(task)
            return task.status()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _create_task(self) -> TaskRecord:
        self._cleanup_expired()
        task = TaskRecord(task_id=uuid.uuid4().hex)
        with self._lock:
            self._tasks[task.task_id] = task
        logger.info("task.created task_id=%s", task.task_id)
        return task

    @staticmethod
    def _created_response(task_id: str) -> TaskCreatedResponse:
        return TaskCreatedResponse(
            task_id=task_id,
            status_url=f"/api/tasks/{task_id}",
            result_url=f"/api/tasks/{task_id}/result",
        )

    def _get_task(self, task_id: str) -> TaskRecord:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        return task

    def _update(
        self,
        task_id: str,
        stage: TaskStage,
        progress: int,
        message: str,
    ) -> None:
        task = self._get_task(task_id)
        with self._lock:
            task.stage = stage
            task.progress = max(task.progress, min(100, progress))
            task.message = message
            task.updated_at = utc_now()
            if task.started_at is None and stage != "queued":
                task.started_at = task.updated_at
        logger.info(
            "task.progress task_id=%s stage=%s progress=%s message=%s",
            task_id,
            stage,
            progress,
            message,
        )

    def _cancel_check(self, task_id: str) -> Callable[[], bool]:
        return lambda: self._get_task(task_id).cancel_requested

    def _progress_callback(self, task_id: str):
        return lambda stage, progress, message: self._update(
            task_id,
            stage,
            progress,
            message,
        )

    def _run_upload(
        self,
        task_id: str,
        source_path: Path,
        transcriber: WhisperTranscriber,
    ) -> None:
        try:
            self._run_gpu_transcription(task_id, source_path, transcriber)
        finally:
            shutil.rmtree(source_path.parent, ignore_errors=True)

    def _run_url(
        self,
        task_id: str,
        url: str,
        browser: str | None,
        transcriber: WhisperTranscriber,
        source_registry: SourceRegistry,
    ) -> None:
        try:
            self._raise_if_cancelled(task_id)
            self._update(task_id, "downloading", 5, "Downloading source media")
            with TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
                media = source_registry.resolve(url, Path(tmpdir), browser=browser)
                self._update(task_id, "downloading", 20, "Source media ready")
                response = self._run_gpu_transcription(
                    task_id,
                    media.media_path,
                    transcriber,
                    complete=False,
                )
                response.source = SourceMetadata(
                    provider=media.provider,
                    title=media.title,
                    webpage_url=media.webpage_url,
                )
                self._complete(task_id, response)
        except Exception as exc:
            self._handle_failure(task_id, exc)

    def _run_gpu_transcription(
        self,
        task_id: str,
        source_path: Path,
        transcriber: WhisperTranscriber,
        *,
        complete: bool = True,
    ) -> TranscriptionResponse:
        try:
            self._raise_if_cancelled(task_id)
            self._update(task_id, "waiting_for_gpu", 20, "Waiting for GPU slot")
            with self._gpu_slots:
                self._raise_if_cancelled(task_id)
                response = transcriber.transcribe_path(
                    source_path,
                    progress=self._progress_callback(task_id),
                    cancel_check=self._cancel_check(task_id),
                )
            if complete:
                self._complete(task_id, response)
            return response
        except Exception as exc:
            self._handle_failure(task_id, exc)
            raise

    def _complete(self, task_id: str, result: TranscriptionResponse) -> None:
        task = self._get_task(task_id)
        with self._lock:
            task.stage = "completed"
            task.progress = 100
            task.message = "Transcription complete"
            task.result = result
            task.updated_at = utc_now()
            task.completed_at = task.updated_at
        logger.info("task.completed task_id=%s", task_id)

    def _handle_failure(self, task_id: str, exc: Exception) -> None:
        task = self._get_task(task_id)
        if task.stage in {"failed", "cancelled", "completed"}:
            return
        if isinstance(exc, TranscriptionCancelled) or task.cancel_requested:
            self._mark_cancelled(task)
            return
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        with self._lock:
            task.stage = "failed"
            task.message = "Task failed"
            task.error = str(detail)
            task.updated_at = utc_now()
            task.completed_at = task.updated_at
        logger.error(
            "task.failed task_id=%s",
            task_id,
            exc_info=(type(exc), exc, exc.__traceback__),
        )

    def _raise_if_cancelled(self, task_id: str) -> None:
        if self._get_task(task_id).cancel_requested:
            raise TranscriptionCancelled()

    def _mark_cancelled(self, task: TaskRecord) -> None:
        with self._lock:
            task.stage = "cancelled"
            task.message = "Task cancelled"
            task.updated_at = utc_now()
            task.completed_at = task.updated_at
        logger.info("task.cancelled task_id=%s", task.task_id)

    def _cleanup_expired(self) -> None:
        cutoff = utc_now() - self._retention
        with self._lock:
            expired = [
                task_id
                for task_id, task in self._tasks.items()
                if task.completed_at is not None and task.completed_at < cutoff
            ]
            for task_id in expired:
                del self._tasks[task_id]
