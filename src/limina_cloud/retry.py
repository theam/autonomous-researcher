"""Durable managed-turn retry policy."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .errors import LiminaError


@dataclass(frozen=True)
class RetryPolicy:
    delays_seconds: tuple[float, ...] = (30.0, 120.0, 600.0)

    @classmethod
    def from_environment(cls) -> RetryPolicy:
        raw = os.environ.get("LIMINA_RUNTIME_RETRY_DELAYS_SECONDS", "30,120,600")
        try:
            delays = tuple(float(item.strip()) for item in raw.split(",") if item.strip())
        except ValueError as exc:
            raise RuntimeError("Runtime retry delays must be comma-separated seconds.") from exc
        if not delays or any(item < 0 for item in delays):
            raise RuntimeError("Runtime retry delays must contain non-negative seconds.")
        return cls(delays)

    @property
    def max_attempts(self) -> int:
        return len(self.delays_seconds) + 1

    def delay_after(self, retry_count: int) -> float | None:
        if retry_count < 0 or retry_count >= len(self.delays_seconds):
            return None
        return self.delays_seconds[retry_count]

    @staticmethod
    def is_retryable(exc: BaseException) -> bool:
        return isinstance(exc, LiminaError) and bool(exc.details.get("retryable"))
