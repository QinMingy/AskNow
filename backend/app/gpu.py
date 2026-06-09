import threading
from contextlib import contextmanager


class GpuScheduler:
    def __init__(self, concurrency: int = 1):
        self._slots = threading.Semaphore(max(1, concurrency))

    @contextmanager
    def acquire(self):
        with self._slots:
            yield
