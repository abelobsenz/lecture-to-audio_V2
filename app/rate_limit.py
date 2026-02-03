from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict


class SimpleRateLimiter:
    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: Dict[str, Deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        window_start = now - self.window_seconds
        queue = self._hits.setdefault(key, deque())
        while queue and queue[0] < window_start:
            queue.popleft()
        if len(queue) >= self.max_requests:
            return False
        queue.append(now)
        return True
