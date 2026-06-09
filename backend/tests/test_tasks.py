import threading
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.schemas import SourceMetadata, TranscriptSegment, TranscriptionResponse
from app.sources.base import ResolvedMedia
from app.tasks import TaskManager
from app.transcriber import TranscriptionCancelled


def result(source=None):
    return TranscriptionResponse(
        language="zh",
        duration=2.0,
        segments=[
            TranscriptSegment(
                id=1,
                start=0.0,
                end=2.0,
                speaker="Speaker A",
                text="test",
            )
        ],
        source=source,
    )


def wait_for_terminal(manager: TaskManager, task_id: str, timeout: float = 3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = manager.get_status(task_id)
        if task.stage in {"completed", "failed", "cancelled"}:
            return task
        time.sleep(0.01)
    raise AssertionError("Task did not reach a terminal state.")


def test_upload_task_reports_progress_and_result(tmp_path: Path):
    class FakeTranscriber:
        def transcribe_path(self, path, progress=None, cancel_check=None):
            progress("transcribing", 50, "Halfway")
            progress("diarizing", 90, "Speakers")
            return result()

    source_dir = tmp_path / "task"
    source_dir.mkdir()
    source_path = source_dir / "sample.wav"
    source_path.write_bytes(b"audio")
    manager = TaskManager()

    created = manager.submit_upload(source_path, FakeTranscriber())
    status = wait_for_terminal(manager, created.task_id)

    assert status.stage == "completed"
    assert status.progress == 100
    assert manager.get_result(created.task_id).segments[0].speaker == "Speaker A"
    assert not source_dir.exists()
    manager.shutdown()


def test_url_task_adds_source_metadata(tmp_path: Path):
    class FakeRegistry:
        def resolve(self, url, output_dir, browser=None):
            path = output_dir / "source.m4a"
            path.write_bytes(b"audio")
            return ResolvedMedia(
                provider="BiliBili",
                title="Lesson",
                webpage_url=url,
                media_path=path,
            )

    class FakeTranscriber:
        def transcribe_path(self, path, progress=None, cancel_check=None):
            return result()

    manager = TaskManager()
    created = manager.submit_url(
        "https://example.test/video",
        None,
        FakeTranscriber(),
        FakeRegistry(),
    )
    wait_for_terminal(manager, created.task_id)

    task_result = manager.get_result(created.task_id)
    assert task_result.source == SourceMetadata(
        provider="BiliBili",
        title="Lesson",
        webpage_url="https://example.test/video",
    )
    manager.shutdown()


def test_cancelled_task_does_not_return_result(tmp_path: Path):
    started = threading.Event()
    release = threading.Event()

    class BlockingTranscriber:
        def transcribe_path(self, path, progress=None, cancel_check=None):
            started.set()
            release.wait(timeout=2)
            if cancel_check():
                raise TranscriptionCancelled()
            return result()

    source_dir = tmp_path / "task"
    source_dir.mkdir()
    source_path = source_dir / "sample.wav"
    source_path.write_bytes(b"audio")
    manager = TaskManager()
    created = manager.submit_upload(source_path, BlockingTranscriber())
    assert started.wait(timeout=1)

    manager.cancel(created.task_id)
    release.set()
    status = wait_for_terminal(manager, created.task_id)

    assert status.stage == "cancelled"
    with pytest.raises(HTTPException) as exc_info:
        manager.get_result(created.task_id)
    assert exc_info.value.status_code == 409
    manager.shutdown()


def test_gpu_concurrency_is_limited_to_one(tmp_path: Path):
    active = 0
    max_active = 0
    lock = threading.Lock()

    class CountingTranscriber:
        def transcribe_path(self, path, progress=None, cancel_check=None):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.08)
            with lock:
                active -= 1
            return result()

    manager = TaskManager(worker_count=2, gpu_concurrency=1)
    created = []
    for index in range(2):
        source_dir = tmp_path / f"task-{index}"
        source_dir.mkdir()
        source_path = source_dir / "sample.wav"
        source_path.write_bytes(b"audio")
        created.append(manager.submit_upload(source_path, CountingTranscriber()))

    for task in created:
        wait_for_terminal(manager, task.task_id)

    assert max_active == 1
    manager.shutdown()
