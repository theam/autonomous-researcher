"""Process-scoped event fan-out for the Console's ambient stream."""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Final, Literal, TypeAlias

from sqlalchemy import func, select

from .auth import Principal
from .database import Database
from .models import Challenge, Event, ProjectMember

logger = logging.getLogger(__name__)

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_PRIVATE_DETAIL_KEYS: Final = frozenset(
    {
        "worker_id",
        "thread_id",
        "continuation_id",
        "turn_id",
        "version",
        "expires_at",
        "message_id",
    }
)
_PUBLIC_EVENT_NAMES: Final = {
    "challenge.created": "project.created",
    "coordinator.checkpointed": "project.checkpoint",
    "inbox.message_sent": "guidance.received",
    "inbox.message_acknowledged": "guidance.incorporated",
}
_HIDDEN_EVENT_TYPES: Final = frozenset({"coordinator.claimed", "coordinator.released"})
_MEMBERSHIP_EVENTS: Final = frozenset({"project.member_set", "project.member_removed"})
_PROJECT_AUTHORIZATION_EVENTS: Final = frozenset({"project.archived"})


def _json_value(value: Any) -> JsonValue:
    """Normalize values read from a JSON column into the stream's closed JSON type."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Stream event details cannot contain non-finite numbers.")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Stream event detail keys must be strings.")
            normalized[key] = _json_value(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    raise ValueError(f"Unsupported stream event detail value: {type(value).__name__}.")


def _timestamp(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class StreamEventEnvelope:
    """Public, project-addressable representation of one durable runtime event."""

    sequence: int
    project_id: str
    event_type: str
    actor: str
    artifact_id: str | None
    detail: dict[str, JsonValue]
    created_at: str
    type: Literal["event"] = "event"

    @classmethod
    def from_model(cls, event: Event) -> StreamEventEnvelope:
        raw_detail = {
            key: value for key, value in event.payload.items() if key not in _PRIVATE_DETAIL_KEYS
        }
        normalized = _json_value(raw_detail)
        if not isinstance(normalized, dict):  # pragma: no cover - raw_detail is always a dict
            raise ValueError("Stream event detail must be an object.")
        event_type = _PUBLIC_EVENT_NAMES.get(event.event_type, event.event_type)
        actor = "Limina" if event.actor.startswith("limina:") else event.actor
        if event.event_type == "challenge.created" and "runtime_engine" in normalized:
            normalized["runtime"] = normalized.pop("runtime_engine")
        return cls(
            sequence=event.sequence,
            project_id=event.challenge_id,
            event_type=event_type,
            actor=actor,
            artifact_id=event.artifact_id,
            detail=normalized,
            created_at=_timestamp(event.created_at),
        )

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "type": self.type,
            "sequence": self.sequence,
            "project_id": self.project_id,
            "event_type": self.event_type,
            "actor": self.actor,
            "artifact_id": self.artifact_id,
            "detail": self.detail,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ResyncEnvelope:
    """Instruction to replace local projections after bounded replay cannot be honored."""

    latest_sequence: int
    reason: Literal["replay_limit_exceeded", "slow_consumer", "cursor_ahead"]
    type: Literal["resync"] = "resync"

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "type": self.type,
            "latest_sequence": self.latest_sequence,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Heartbeat:
    """Transport heartbeat. It is encoded as an SSE comment, not application data."""

    emitted_at: str


StreamFrame: TypeAlias = StreamEventEnvelope | ResyncEnvelope | Heartbeat


def encode_sse(frame: StreamFrame) -> str:
    """Encode a typed stream frame without allowing multiline field injection."""

    if isinstance(frame, Heartbeat):
        return f": heartbeat {frame.emitted_at}\n\n"
    event_name = "event" if isinstance(frame, StreamEventEnvelope) else "resync"
    event_id = frame.sequence if isinstance(frame, StreamEventEnvelope) else frame.latest_sequence
    data = json.dumps(frame.as_dict(), separators=(",", ":"), sort_keys=True)
    return f"id: {event_id}\nevent: {event_name}\ndata: {data}\n\n"


@dataclass(frozen=True)
class _AuthorizationSnapshot:
    project_ids: frozenset[str]
    expires_at: float
    generation: int


@dataclass(frozen=True)
class _AuthorizationInvalidated:
    subject: str


_QueuedFrame: TypeAlias = StreamEventEnvelope | ResyncEnvelope | _AuthorizationInvalidated


class EventSubscription(AsyncIterator[StreamFrame]):
    """One ordered view over replayed and newly tailed events for a principal."""

    def __init__(
        self,
        broker: EventBroker,
        principal: Principal,
        queue: asyncio.Queue[_QueuedFrame],
        replay: Sequence[StreamEventEnvelope | ResyncEnvelope],
        *,
        initial_sequence: int,
    ) -> None:
        self._broker = broker
        self.principal = principal
        self.queue = queue
        self._replay = iter(replay)
        self._authorization: _AuthorizationSnapshot | None = None
        self._last_sequence = initial_sequence
        self._next_heartbeat_at = broker.clock() + broker.heartbeat_interval
        self._closed = False

    def __aiter__(self) -> EventSubscription:
        return self

    async def __anext__(self) -> StreamFrame:
        if self._closed:
            raise StopAsyncIteration

        while True:
            try:
                replayed = next(self._replay)
            except StopIteration:
                break
            if isinstance(replayed, ResyncEnvelope):
                self._last_sequence = replayed.latest_sequence
                return replayed
            if await self._is_authorized(replayed.project_id):
                self._last_sequence = replayed.sequence
                return replayed
            self._last_sequence = max(self._last_sequence, replayed.sequence)

        while not self._closed:
            now = self._broker.clock()
            await self._refresh_authorization_if_needed(now)
            auth_deadline = (
                self._authorization.expires_at
                if self._authorization is not None
                else now + self._broker.authorization_ttl
            )
            timeout = max(0.001, min(self._next_heartbeat_at, auth_deadline) - now)
            try:
                queued = await asyncio.wait_for(self.queue.get(), timeout=timeout)
            except TimeoutError:
                now = self._broker.clock()
                await self._refresh_authorization_if_needed(now)
                if now >= self._next_heartbeat_at:
                    self._next_heartbeat_at = now + self._broker.heartbeat_interval
                    return Heartbeat(_timestamp(datetime.now(UTC)))
                continue

            if isinstance(queued, _AuthorizationInvalidated):
                self._authorization = None
                continue
            if isinstance(queued, ResyncEnvelope):
                self._last_sequence = queued.latest_sequence
                return queued
            if queued.sequence <= self._last_sequence:
                continue
            self._last_sequence = queued.sequence
            if await self._is_authorized(queued.project_id):
                return queued

        raise StopAsyncIteration

    async def _is_authorized(self, project_id: str) -> bool:
        await self._refresh_authorization_if_needed(self._broker.clock())
        return self._authorization is not None and project_id in self._authorization.project_ids

    async def _refresh_authorization_if_needed(self, now: float) -> None:
        current = self._authorization
        if (
            current is not None
            and current.expires_at > now
            and current.generation == self._broker.authorization_generation(self.principal.subject)
        ):
            return
        self._authorization = await self._broker.authorized_projects(self.principal)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._broker.unsubscribe(self)


class EventBroker:
    """Own the sole Event-table tail loop and fan out its results in-process."""

    def __init__(
        self,
        database: Database,
        *,
        poll_interval: float = 0.25,
        heartbeat_interval: float = 15.0,
        authorization_ttl: float = 30.0,
        replay_limit: int = 500,
        batch_limit: int = 500,
        subscriber_queue_size: int = 512,
        clock: Any = monotonic,
    ) -> None:
        if poll_interval <= 0 or heartbeat_interval <= 0:
            raise ValueError("Event polling and heartbeat intervals must be positive.")
        if not 0 < authorization_ttl <= 30:
            raise ValueError("Authorization cache TTL must be between 0 and 30 seconds.")
        if replay_limit < 1 or batch_limit < 1 or subscriber_queue_size < 2:
            raise ValueError("Replay, batch, and subscriber queue limits must be positive.")
        self.database = database
        self.poll_interval = poll_interval
        self.heartbeat_interval = heartbeat_interval
        self.authorization_ttl = authorization_ttl
        self.replay_limit = replay_limit
        self.batch_limit = batch_limit
        self.subscriber_queue_size = subscriber_queue_size
        self.clock = clock

        self._tail_cursor = 0
        self._tail_task: asyncio.Task[None] | None = None
        self._start_lock = asyncio.Lock()
        self._poll_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._subscribers: set[EventSubscription] = set()
        self._authorization_cache: dict[tuple[str, bool], _AuthorizationSnapshot] = {}
        self._authorization_generations: dict[str, int] = {}
        self.tail_query_count = 0
        self.authorization_query_count = 0

    @property
    def latest_sequence(self) -> int:
        return self._tail_cursor

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def start(self) -> None:
        """Start exactly one tail task; repeated and concurrent calls are harmless."""

        async with self._start_lock:
            if self._tail_task is not None and not self._tail_task.done():
                return
            self._stop.clear()
            with self.database.session() as session:
                self._tail_cursor = session.scalar(select(func.max(Event.sequence))) or 0
            self._tail_task = asyncio.create_task(self._tail_loop(), name="limina-event-tail")

    async def stop(self) -> None:
        async with self._start_lock:
            task = self._tail_task
            self._tail_task = None
            self._stop.set()
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            subscriptions = tuple(self._subscribers)
            for subscription in subscriptions:
                subscription._closed = True
            self._subscribers.clear()

    async def subscribe(
        self, principal: Principal, *, last_event_id: int | None = None
    ) -> EventSubscription:
        """Atomically join live fan-out, then replay only events preceding that join."""

        if last_event_id is not None and last_event_id < 0:
            raise ValueError("Last-Event-ID cannot be negative.")
        await self.start()
        authorization = await self.authorized_projects(principal)
        queue: asyncio.Queue[_QueuedFrame] = asyncio.Queue(self.subscriber_queue_size)
        async with self._state_lock:
            watermark = self._tail_cursor
            subscription = EventSubscription(
                self,
                principal,
                queue,
                (),
                initial_sequence=watermark if last_event_id is None else last_event_id,
            )
            subscription._authorization = authorization
            self._subscribers.add(subscription)

        replay: list[StreamEventEnvelope | ResyncEnvelope] = []
        if last_event_id is not None:
            if last_event_id > watermark:
                replay = [ResyncEnvelope(watermark, "cursor_ahead")]
            elif last_event_id < watermark:
                replay = self._replay(last_event_id, watermark, authorization.project_ids)
        subscription._replay = iter(replay)
        return subscription

    async def unsubscribe(self, subscription: EventSubscription) -> None:
        async with self._state_lock:
            self._subscribers.discard(subscription)

    async def poll_once(self) -> int:
        """Tail one database batch. Exposed for deterministic wakeups and observability."""

        async with self._poll_lock:
            events = self._tail_batch(self._tail_cursor)
            self.tail_query_count += 1
            for event in events:
                if event.event_type in _HIDDEN_EVENT_TYPES:
                    await self._advance_cursor(event.sequence)
                    continue
                envelope = StreamEventEnvelope.from_model(event)
                if event.event_type in _MEMBERSHIP_EVENTS:
                    subject = event.payload.get("subject")
                    if isinstance(subject, str) and subject:
                        await self.invalidate_authorization(subject)
                elif event.event_type in _PROJECT_AUTHORIZATION_EVENTS:
                    await self._invalidate_project_authorizations(event.challenge_id)
                await self._publish(envelope)
            return len(events)

    async def invalidate_authorization(self, subject: str | None = None) -> None:
        """Expire cached memberships and wake affected subscribers immediately."""

        if subject is None:
            subjects = {subscription.principal.subject for subscription in self._subscribers}
            subjects.update(key[0] for key in self._authorization_cache)
        else:
            subjects = {subject}
        for item in subjects:
            self._authorization_generations[item] = self.authorization_generation(item) + 1
        self._authorization_cache = {
            key: value for key, value in self._authorization_cache.items() if key[0] not in subjects
        }
        async with self._state_lock:
            for subscription in self._subscribers:
                if subscription.principal.subject in subjects:
                    self._offer(
                        subscription,
                        _AuthorizationInvalidated(subscription.principal.subject),
                    )

    def authorization_generation(self, subject: str) -> int:
        return self._authorization_generations.get(subject, 0)

    async def authorized_projects(self, principal: Principal) -> _AuthorizationSnapshot:
        key = (principal.subject, principal.project_admin)
        generation = self.authorization_generation(principal.subject)
        now = self.clock()
        cached = self._authorization_cache.get(key)
        if cached is not None and cached.expires_at > now and cached.generation == generation:
            return cached

        with self.database.session() as session:
            self.authorization_query_count += 1
            if principal.project_admin:
                ids = session.scalars(select(Challenge.id)).all()
            else:
                ids = session.scalars(
                    select(Challenge.id)
                    .join(ProjectMember, ProjectMember.challenge_id == Challenge.id)
                    .where(ProjectMember.subject == principal.subject)
                ).all()
        snapshot = _AuthorizationSnapshot(frozenset(ids), now + self.authorization_ttl, generation)
        self._authorization_cache[key] = snapshot
        return snapshot

    async def _tail_loop(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    found = await self.poll_once()
                except Exception:  # pragma: no cover - defensive process-level resilience
                    logger.exception("The ambient event tail failed; polling will retry.")
                    found = 0
                if found >= self.batch_limit:
                    continue
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval)
        except asyncio.CancelledError:
            raise

    def _tail_batch(self, after: int) -> list[Event]:
        with self.database.session() as session:
            return list(
                session.scalars(
                    select(Event)
                    .where(Event.sequence > after)
                    .order_by(Event.sequence)
                    .limit(self.batch_limit)
                ).all()
            )

    def _replay(
        self, after: int, through: int, project_ids: frozenset[str]
    ) -> list[StreamEventEnvelope | ResyncEnvelope]:
        if not project_ids:
            return []
        with self.database.session() as session:
            events = list(
                session.scalars(
                    select(Event)
                    .where(
                        Event.sequence > after,
                        Event.sequence <= through,
                        Event.challenge_id.in_(project_ids),
                        Event.event_type.notin_(_HIDDEN_EVENT_TYPES),
                    )
                    .order_by(Event.sequence)
                    .limit(self.replay_limit + 1)
                ).all()
            )
        if len(events) > self.replay_limit:
            return [ResyncEnvelope(through, "replay_limit_exceeded")]
        return [StreamEventEnvelope.from_model(event) for event in events]

    async def _publish(self, envelope: StreamEventEnvelope) -> None:
        async with self._state_lock:
            if envelope.sequence <= self._tail_cursor:
                return
            self._tail_cursor = envelope.sequence
            for subscription in self._subscribers:
                self._offer(subscription, envelope)

    async def _advance_cursor(self, sequence: int) -> None:
        async with self._state_lock:
            self._tail_cursor = max(self._tail_cursor, sequence)

    async def _invalidate_project_authorizations(self, project_id: str) -> None:
        subjects = {
            key[0]
            for key, snapshot in self._authorization_cache.items()
            if project_id in snapshot.project_ids
        }
        subjects.update(
            subscription.principal.subject
            for subscription in self._subscribers
            if subscription._authorization is not None
            and project_id in subscription._authorization.project_ids
        )
        for subject in subjects:
            await self.invalidate_authorization(subject)

    def _offer(self, subscription: EventSubscription, frame: _QueuedFrame) -> None:
        try:
            subscription.queue.put_nowait(frame)
            return
        except asyncio.QueueFull:
            pass
        while not subscription.queue.empty():
            try:
                subscription.queue.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - single-loop queue ownership
                break
        latest = (
            frame.sequence
            if isinstance(frame, StreamEventEnvelope)
            else max(self._tail_cursor, subscription._last_sequence)
        )
        subscription.queue.put_nowait(ResyncEnvelope(latest, "slow_consumer"))
