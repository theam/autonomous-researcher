"""Provider usage normalization and explicit operator-rate cost estimation."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class RuntimeUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    total_tokens: int | None = None
    cost_microusd: int | None = None
    usage_source: str | None = None
    cost_source: str | None = None


@dataclass(frozen=True)
class TokenPricing:
    input_usd_per_million: Decimal
    cached_input_usd_per_million: Decimal
    output_usd_per_million: Decimal

    @classmethod
    def from_environment(cls, prefix: str) -> TokenPricing | None:
        names = {
            "input_usd_per_million": f"{prefix}_INPUT_USD_PER_MILLION_TOKENS",
            "cached_input_usd_per_million": f"{prefix}_CACHED_INPUT_USD_PER_MILLION_TOKENS",
            "output_usd_per_million": f"{prefix}_OUTPUT_USD_PER_MILLION_TOKENS",
        }
        raw = {field: os.environ.get(name, "").strip() for field, name in names.items()}
        configured = {field for field, value in raw.items() if value}
        if not configured:
            return None
        if configured != set(names):
            missing = ", ".join(names[field] for field in names if not raw[field])
            raise RuntimeError(f"Configure all token-price rates together; missing: {missing}.")
        try:
            values = {field: Decimal(value) for field, value in raw.items()}
        except InvalidOperation as exc:
            raise RuntimeError("Token-price rates must be non-negative decimal numbers.") from exc
        if any(value < 0 for value in values.values()):
            raise RuntimeError("Token-price rates must be non-negative decimal numbers.")
        return cls(**values)

    def estimate_microusd(self, usage: RuntimeUsage) -> int | None:
        if usage.input_tokens is None or usage.output_tokens is None:
            return None
        cached = min(max(usage.cached_input_tokens or 0, 0), usage.input_tokens)
        uncached = usage.input_tokens - cached
        # tokens * USD-per-million is numerically micro-USD because both scales are 1e6.
        estimate = (
            Decimal(uncached) * self.input_usd_per_million
            + Decimal(cached) * self.cached_input_usd_per_million
            + Decimal(usage.output_tokens) * self.output_usd_per_million
        )
        return int(estimate.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def usage_from_result(result: Any, *, pricing: TokenPricing | None = None) -> RuntimeUsage | None:
    raw_usage = getattr(result, "usage", None)
    # Codex ThreadTokenUsage.total is cumulative across resumed turns. `last` is the current turn
    # delta and is the only safe value for a per-run row.
    if raw_usage is not None and hasattr(raw_usage, "last"):
        raw_usage = raw_usage.last
    if raw_usage is None:
        raw_usage = {}
    if not isinstance(raw_usage, dict):
        raw_usage = {
            key: getattr(raw_usage, key, None)
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cached_input_tokens",
                "reasoning_output_tokens",
                "total_tokens",
            )
        }
    cost = getattr(result, "total_cost_usd", None)
    usage = RuntimeUsage(
        input_tokens=_optional_int(raw_usage.get("input_tokens")),
        output_tokens=_optional_int(raw_usage.get("output_tokens")),
        cached_input_tokens=_optional_int(
            raw_usage.get("cache_read_input_tokens") or raw_usage.get("cached_input_tokens")
        ),
        reasoning_output_tokens=_optional_int(raw_usage.get("reasoning_output_tokens")),
        total_tokens=_optional_int(raw_usage.get("total_tokens")),
        cost_microusd=round(float(cost) * 1_000_000) if cost is not None else None,
        usage_source="provider" if raw_usage else None,
        cost_source="provider" if cost is not None else None,
    )
    if pricing is not None and usage.cost_microusd is None:
        estimated = pricing.estimate_microusd(usage)
        if estimated is not None:
            usage = replace(usage, cost_microusd=estimated, cost_source="operator_rate")
    if all(
        value is None
        for field, value in usage.__dict__.items()
        if field not in {"usage_source", "cost_source"}
    ):
        return None
    return usage


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
