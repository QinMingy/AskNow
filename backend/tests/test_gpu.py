import threading
import time

from app.gpu import GpuScheduler


def test_gpu_scheduler_serializes_shared_work():
    scheduler = GpuScheduler(1)
    active = 0
    max_active = 0
    lock = threading.Lock()

    def work():
        nonlocal active, max_active
        with scheduler.acquire():
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.04)
            with lock:
                active -= 1

    threads = [threading.Thread(target=work) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max_active == 1
