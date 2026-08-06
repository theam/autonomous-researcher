from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from fastapi import Depends, FastAPI

from limina_cloud.auth import Principal
from limina_cloud.database import Database
from limina_cloud.event_broker import (
    EventBroker,
    Heartbeat,
    ResyncEnvelope,
    StreamEventEnvelope,
    encode_sse,
)
from limina_cloud.models import Challenge, Event, ProjectMember
from limina_cloud.stream_api import register_stream_routes


class CloudStreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "stream.db"
        self.database = Database(f"sqlite:///{database_path}")
        self.database.initialize()
        self.brokers: list[EventBroker] = []

    async def asyncTearDown(self) -> None:
        for broker in self.brokers:
            await broker.stop()
        self.database.dispose()
        self.temp_dir.cleanup()

    def broker(self, **options: object) -> EventBroker:
        broker = EventBroker(
            self.database,
            poll_interval=60,
            heartbeat_interval=0.2,
            **options,
        )
        self.brokers.append(broker)
        return broker

    def add_project(self, slug: str) -> str:
        with self.database.session() as session, session.begin():
            project = Challenge(
                slug=slug,
                name=slug.title(),
                objective="Keep operators aware of runtime progress.",
                context="Ambient stream test.",
                success_criteria="Authorized events arrive once and in order.",
            )
            session.add(project)
            session.flush()
            return project.id

    def add_member(self, project_id: str, subject: str) -> None:
        with self.database.session() as session, session.begin():
            session.add(
                ProjectMember(
                    challenge_id=project_id,
                    subject=subject,
                    role="VIEWER",
                    display_name=subject,
                    created_by="test",
                )
            )

    def remove_member(self, project_id: str, subject: str) -> None:
        with self.database.session() as session, session.begin():
            member = session.get(ProjectMember, (project_id, subject))
            self.assertIsNotNone(member)
            session.delete(member)

    def add_event(
        self,
        project_id: str,
        event_type: str = "runtime.progress",
        *,
        payload: dict[str, str] | None = None,
    ) -> int:
        with self.database.session() as session, session.begin():
            event = Event(
                challenge_id=project_id,
                event_type=event_type,
                actor="limina:supervisor",
                payload=payload or {"summary": "A typed update", "thread_id": "private"},
                command_id=f"test:{project_id}:{event_type}",
            )
            session.add(event)
            session.flush()
            return event.sequence

    @staticmethod
    def principal(subject: str = "user-1") -> Principal:
        return Principal(subject=subject, display_name=subject, auth_mode="workos")

    async def next_frame(self, subscription) -> StreamEventEnvelope | ResyncEnvelope | Heartbeat:
        return await asyncio.wait_for(anext(subscription), timeout=1)

    async def test_last_event_id_replays_then_crosses_to_live_without_duplicates(self) -> None:
        project_id = self.add_project("replay")
        self.add_member(project_id, "user-1")
        first = self.add_event(project_id)
        second = self.add_event(project_id)
        broker = self.broker()

        subscription = await broker.subscribe(self.principal(), last_event_id=0)
        replayed_first = await self.next_frame(subscription)
        replayed_second = await self.next_frame(subscription)
        third = self.add_event(project_id)
        await broker.poll_once()
        live = await self.next_frame(subscription)

        self.assertEqual(
            [replayed_first.sequence, replayed_second.sequence, live.sequence],
            [first, second, third],
        )
        self.assertTrue(
            all(
                isinstance(item, StreamEventEnvelope)
                for item in [
                    replayed_first,
                    replayed_second,
                    live,
                ]
            )
        )
        self.assertEqual(live.project_id, project_id)
        self.assertNotIn("thread_id", live.detail)
        await subscription.aclose()

    async def test_large_replay_gap_requires_explicit_resync(self) -> None:
        project_id = self.add_project("large-gap")
        self.add_member(project_id, "user-1")
        latest = 0
        for _ in range(3):
            latest = self.add_event(project_id)
        broker = self.broker(replay_limit=2)

        subscription = await broker.subscribe(self.principal(), last_event_id=0)
        frame = await self.next_frame(subscription)

        self.assertIsInstance(frame, ResyncEnvelope)
        self.assertEqual(frame.reason, "replay_limit_exceeded")
        self.assertEqual(frame.latest_sequence, latest)
        await subscription.aclose()

        future_cursor = await broker.subscribe(self.principal(), last_event_id=latest + 100)
        future_frame = await self.next_frame(future_cursor)
        self.assertIsInstance(future_frame, ResyncEnvelope)
        self.assertEqual(future_frame.reason, "cursor_ahead")
        self.assertEqual(future_frame.latest_sequence, latest)
        after_resync = self.add_event(project_id)
        await broker.poll_once()
        self.assertEqual((await self.next_frame(future_cursor)).sequence, after_resync)
        await future_cursor.aclose()

    async def test_authorization_filters_replay_and_revocation_within_cache_bound(self) -> None:
        project_a = self.add_project("project-a")
        project_b = self.add_project("project-b")
        self.add_member(project_a, "user-1")
        a_first = self.add_event(project_a)
        self.add_event(project_b)
        a_second = self.add_event(project_a)
        broker = self.broker(authorization_ttl=0.05)

        subscription = await broker.subscribe(self.principal(), last_event_id=0)
        replayed = [await self.next_frame(subscription), await self.next_frame(subscription)]
        self.assertEqual([item.sequence for item in replayed], [a_first, a_second])

        self.add_member(project_b, "user-1")
        await broker.invalidate_authorization("user-1")
        b_after_grant = self.add_event(project_b)
        await broker.poll_once()
        granted = await self.next_frame(subscription)
        self.assertEqual(granted.sequence, b_after_grant)

        self.remove_member(project_a, "user-1")
        self.add_event(
            project_a,
            "project.member_removed",
            payload={"subject": "user-1"},
        )
        self.add_event(project_a)
        b_after_invalidation = self.add_event(project_b)
        await broker.poll_once()
        still_authorized = await self.next_frame(subscription)
        self.assertEqual(still_authorized.sequence, b_after_invalidation)

        self.add_member(project_a, "user-1")
        await broker.invalidate_authorization("user-1")
        a_after_restore = self.add_event(project_a)
        await broker.poll_once()
        restored = await self.next_frame(subscription)
        self.assertEqual(restored.sequence, a_after_restore)

        self.remove_member(project_a, "user-1")
        await asyncio.sleep(0.07)
        self.add_event(project_a)
        b_after_ttl = self.add_event(project_b)
        await broker.poll_once()
        after_ttl_refresh = await self.next_frame(subscription)
        self.assertEqual(after_ttl_refresh.sequence, b_after_ttl)
        await subscription.aclose()

    async def test_one_tail_query_fans_out_to_multiple_subscribers(self) -> None:
        project_id = self.add_project("shared-tail")
        self.add_member(project_id, "user-1")
        broker = self.broker()
        first = await broker.subscribe(self.principal())
        second = await broker.subscribe(self.principal())
        await asyncio.sleep(0.01)  # Let the sole background tail enter its long poll wait.
        queries_before = broker.tail_query_count

        sequence = self.add_event(project_id)
        self.assertEqual(await broker.poll_once(), 1)
        first_frame, second_frame = await asyncio.gather(
            self.next_frame(first), self.next_frame(second)
        )

        self.assertEqual(broker.tail_query_count, queries_before + 1)
        self.assertEqual(broker.authorization_query_count, 1)
        self.assertEqual(broker.subscriber_count, 2)
        self.assertEqual(first_frame.sequence, sequence)
        self.assertEqual(second_frame.sequence, sequence)
        await first.aclose()
        await second.aclose()

    async def test_sse_encoding_and_route_registration_keep_the_contract_focused(self) -> None:
        project_id = self.add_project("route")
        sequence = self.add_event(project_id)
        with self.database.session() as session:
            event = session.get(Event, sequence)
            self.assertIsNotNone(event)
            envelope = StreamEventEnvelope.from_model(event)
        encoded = encode_sse(envelope)
        data_line = next(line[6:] for line in encoded.splitlines() if line.startswith("data: "))
        payload = json.loads(data_line)
        self.assertEqual(payload["sequence"], sequence)
        self.assertEqual(payload["project_id"], project_id)
        self.assertEqual(encode_sse(Heartbeat("now")), ": heartbeat now\n\n")

        broker = self.broker()
        app = FastAPI()

        def principal_dependency() -> Principal:
            return self.principal()

        register_stream_routes(
            app,
            broker,
            principal_dependency=Depends(principal_dependency),
            public_errors={},
        )
        self.assertIn("/v2/stream", {route.path for route in app.routes})
        self.assertIs(app.state.event_broker, broker)

        subscription = await broker.subscribe(self.principal())
        self.assertIsInstance(await self.next_frame(subscription), Heartbeat)
        await subscription.aclose()
        self.assertEqual(broker.subscriber_count, 0)
