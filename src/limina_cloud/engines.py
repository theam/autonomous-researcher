"""Stable project-level runtime engine identifiers."""

from __future__ import annotations

from typing import Literal, cast

RuntimeEngine = Literal["codex", "claude-code"]
SUPPORTED_RUNTIME_ENGINES: tuple[RuntimeEngine, ...] = ("codex", "claude-code")


def normalize_runtime_engine(value: str) -> RuntimeEngine:
    """Normalize an engine name without silently accepting unknown providers."""
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_RUNTIME_ENGINES:
        choices = ", ".join(sorted(SUPPORTED_RUNTIME_ENGINES))
        raise ValueError(f"Runtime engine must be one of: {choices}.")
    return cast(RuntimeEngine, normalized)


def runtime_engine_label(value: str) -> str:
    """Return the user-facing product name for a persisted engine identifier."""
    labels: dict[RuntimeEngine, str] = {"codex": "Codex", "claude-code": "Claude Code"}
    return labels[normalize_runtime_engine(value)]
