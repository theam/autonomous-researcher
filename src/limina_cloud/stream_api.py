"""SSE transport adapter for the process-scoped ambient event broker."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from .auth import Principal
from .event_broker import EventBroker, encode_sse


def register_stream_routes(
    app: FastAPI,
    broker: EventBroker,
    *,
    principal_dependency: Any,
    public_errors: dict[int, dict[str, Any]],
) -> None:
    """Register the one ambient stream without coupling it to project operations."""

    app.state.event_broker = broker

    @app.get(
        "/v2/stream",
        response_class=StreamingResponse,
        responses={
            **public_errors,
            200: {
                "description": "Authorized project events, resync instructions, and heartbeats.",
                "content": {"text/event-stream": {}},
            },
            400: {"description": "Last-Event-ID is not a non-negative integer."},
        },
    )
    async def ambient_stream(
        request: Request,
        principal: Principal = principal_dependency,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        cursor = _last_event_cursor(last_event_id)
        subscription = await broker.subscribe(principal, last_event_id=cursor)

        async def frames() -> AsyncIterator[str]:
            try:
                async for frame in subscription:
                    if await request.is_disconnected():
                        break
                    yield encode_sse(frame)
            finally:
                await subscription.aclose()

        return StreamingResponse(
            frames(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )


def _last_event_cursor(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        cursor = int(value)
    except ValueError as exc:
        raise HTTPException(400, "Last-Event-ID must be a non-negative integer.") from exc
    if cursor < 0:
        raise HTTPException(400, "Last-Event-ID must be a non-negative integer.")
    return cursor
