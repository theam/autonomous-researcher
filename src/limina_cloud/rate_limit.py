"""Small bounded failure limiter for single-node authentication surfaces."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field

from .errors import RateLimitError


@dataclass
class _Failures:
    timestamps: deque[float] = field(default_factory=deque)


class FailureRateLimiter:
    def __init__(
        self,
        *,
        limit: int = 10,
        window_seconds: int = 60,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit < 1 or window_seconds < 1 or max_keys < 1:
            raise ValueError("Rate-limit settings must be positive.")
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self.clock = clock
        self._items: OrderedDict[str, _Failures] = OrderedDict()
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return
            now = self.clock()
            self._prune(item, now)
            if len(item.timestamps) >= self.limit:
                retry_after = max(1, round(item.timestamps[0] + self.window_seconds - now))
                raise RateLimitError(retry_after_seconds=retry_after)

    def failure(self, key: str) -> None:
        with self._lock:
            now = self.clock()
            item = self._items.setdefault(key, _Failures())
            self._prune(item, now)
            item.timestamps.append(now)
            self._items.move_to_end(key)
            while len(self._items) > self.max_keys:
                self._items.popitem(last=False)

    def success(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)

    def _prune(self, item: _Failures, now: float) -> None:
        cutoff = now - self.window_seconds
        while item.timestamps and item.timestamps[0] <= cutoff:
            item.timestamps.popleft()
