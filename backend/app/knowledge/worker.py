from __future__ import annotations

import threading
from collections.abc import Callable


def start_background_job(job: Callable[[], None]) -> None:
    thread = threading.Thread(target=job, daemon=True)
    thread.start()
