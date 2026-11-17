"""Thread-safe in-memory sliding-window rate limiter shared by app features."""

import threading
import time
from collections import deque
from typing import Hashable


class SlidingWindowLimiter:
    """Track attempts per key without duplicating window/pruning logic."""

    def __init__(self, max_keys: int = 10_000):
        self._attempts: dict[Hashable, deque[float]] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys

    @staticmethod
    def _prune(bucket: deque[float], now: float, window_seconds: int) -> None:
        while bucket and now - bucket[0] >= window_seconds:
            bucket.popleft()

    def is_allowed(self, key: Hashable, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._attempts.setdefault(key, deque())
            self._prune(bucket, now, window_seconds)
            return len(bucket) < limit

    def record(self, key: Hashable, window_seconds: int) -> None:
        now = time.monotonic()
        with self._lock:
            bucket = self._attempts.setdefault(key, deque())
            self._prune(bucket, now, window_seconds)
            bucket.append(now)
            self._cleanup(now, window_seconds)

    def allow_and_record(self, key: Hashable, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._attempts.setdefault(key, deque())
            self._prune(bucket, now, window_seconds)
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            self._cleanup(now, window_seconds)
            return True

    def retry_after(self, key: Hashable, limit: int, window_seconds: int) -> int:
        now = time.monotonic()
        with self._lock:
            bucket = self._attempts.setdefault(key, deque())
            self._prune(bucket, now, window_seconds)
            if len(bucket) < limit:
                return 0
            return max(1, int(window_seconds - (now - bucket[0])) + 1)

    def clear(self, key: Hashable) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def _cleanup(self, now: float, window_seconds: int) -> None:
        if len(self._attempts) <= self._max_keys:
            return
        stale = []
        for key, bucket in self._attempts.items():
            self._prune(bucket, now, window_seconds)
            if not bucket:
                stale.append(key)
        for key in stale:
            self._attempts.pop(key, None)
