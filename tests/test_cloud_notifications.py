from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import threading
import unittest
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import func, select

from limina_cloud.database import Database
from limina_cloud.errors import ConflictError, InvariantError
from limina_cloud.models import (
    AttentionEpisode,
    Challenge,
    NotificationChannel,
    NotificationDelivery,
    NotificationOutbox,
)
from limina_cloud.notification_service import (
    NotificationService,
    TransportResult,
    _PinnedHTTPSConnection,
)
from limina_cloud.vault import SecretCipher


def public_resolver(_hostname: str, _port: int) -> list[str]:
    return ["93.184.216.34"]


class RecordingSender:
    def __init__(self, results: list[TransportResult]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, dict[str, str], bytes, tuple[str, ...]]] = []
        self._lock = threading.Lock()

    def __call__(
        self,
        url: str,
        headers: dict[str, str],
        body: bytes,
        pinned_addresses: Sequence[str],
    ) -> TransportResult:
        with self._lock:
            self.calls.append((url, dict(headers), body, tuple(pinned_addresses)))
            return self.results.pop(0)


class NotificationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        database_path = Path(self.temp.name) / "notifications.db"
        self.database = Database(f"sqlite:///{database_path}")
        self.database.initialize()
        self.cipher = SecretCipher.ephemeral()
        with self.database.session() as session, session.begin():
            challenge = Challenge(
                slug="delivery",
                name="Delivery research",
                objective="Keep operators informed",
                context="",
                success_criteria="Reliable attention delivery",
            )
            session.add(challenge)
            session.flush()
            self.challenge_id = challenge.id

    def tearDown(self) -> None:
        self.database.dispose()
        self.temp.cleanup()

    def service(
        self,
        sender: RecordingSender | None = None,
        *,
        max_attempts: int = 3,
        failure_threshold: int = 3,
    ) -> NotificationService:
        return NotificationService(
            self.database,
            self.cipher,
            resolver=public_resolver,
            sender=sender or RecordingSender([TransportResult(200)]),
            max_attempts=max_attempts,
            failure_attention_threshold=failure_threshold,
            retry_base=timedelta(milliseconds=1),
            retry_cap=timedelta(milliseconds=10),
        )

    def create_channel_and_rule(
        self,
        service: NotificationService,
        *,
        channel_type: str = "GENERIC_WEBHOOK",
        name: str = "Operators",
    ) -> tuple[str, str]:
        channel = service.create_channel(
            challenge_id=self.challenge_id,
            channel_type=channel_type,
            display_name=name,
            destination=(
                "https://notify.example.test/limina"
                if channel_type == "GENERIC_WEBHOOK"
                else "https://hooks.slack.com/services/T000/B000/secret-value"
            ),
            signing_secret=("signing-secret-value" if channel_type == "GENERIC_WEBHOOK" else None),
            actor="owner@example.test",
            trust_delegation_confirmed=True,
        )
        rule = service.create_rule(
            challenge_id=self.challenge_id,
            channel_id=channel["id"],
            display_name=f"{name} high attention",
            attention_types=["agent_request"],
            severities=["HIGH"],
            cooldown_seconds=300,
            actor="owner@example.test",
        )
        return channel["id"], rule["id"]

    def add_episode(self, *, source_key: str, opened_at: datetime) -> AttentionEpisode:
        with self.database.session() as session, session.begin():
            episode = AttentionEpisode(
                challenge_id=self.challenge_id,
                item_type="agent_request",
                source_key=source_key,
                status="OPEN",
                severity="HIGH",
                severity_rank=1,
                title="Decision needed",
                body="Choose the safe path. sk_test-secret-value-should-not-leak",
                source_ref={},
                allowed_actions=["ANSWER"],
                resolution_semantics="resolve_request",
                opened_at=opened_at,
                updated_at=opened_at,
            )
            session.add(episode)
            session.flush()
            return episode

    def enqueue(
        self,
        service: NotificationService,
        episode_id: str,
        *,
        changed_at: datetime,
    ) -> list[str]:
        with self.database.session() as session, session.begin():
            challenge = session.get(Challenge, self.challenge_id)
            episode = session.get(AttentionEpisode, episode_id)
            assert challenge is not None and episode is not None
            return service.enqueue_attention(
                session,
                challenge=challenge,
                episode=episode,
                console_url="https://console.example.test",
                changed_at=changed_at,
            )

    def test_channel_secret_is_write_only_and_private_targets_are_rejected(self) -> None:
        sender = RecordingSender([TransportResult(200)])
        service = self.service(sender)
        channel_id, _ = self.create_channel_and_rule(service, channel_type="SLACK")
        public = service.list_channels(self.challenge_id)[0]
        serialized = json.dumps(public, sort_keys=True)
        self.assertNotIn("hooks.slack.com/services", serialized)
        self.assertNotIn("secret-value", serialized)
        self.assertEqual(public["destination"], {"scheme": "https", "host": "hooks.slack.com"})

        with self.database.session() as session:
            channel = session.get(NotificationChannel, channel_id)
            assert channel is not None
            self.assertNotIn("secret-value", channel.secret_ciphertext)

        disabled = service.set_channel_enabled(channel_id=channel_id, enabled=False)
        self.assertEqual(disabled["health"], "DISABLED")
        reenabled = service.set_channel_enabled(channel_id=channel_id, enabled=True)
        self.assertEqual(reenabled["health"], "UNKNOWN")
        started = datetime.now(UTC)
        episode = self.add_episode(source_key="request:slack", opened_at=started)
        self.enqueue(service, episode.id, changed_at=started)
        job = service.claim_batch(worker_id="worker-a", changed_at=started)[0]
        service.deliver_claimed(outbox_id=job["id"], worker_id="worker-a", changed_at=started)
        slack_body = sender.calls[0][2].decode()
        self.assertIn("Open in Limina", slack_body)
        self.assertIn(f"/attention/{episode.id}", slack_body)
        self.assertIn("agent_request", slack_body)
        self.assertIn("[redacted]", slack_body)
        self.assertNotIn("secret-value", slack_body)

        private_service = NotificationService(
            self.database,
            self.cipher,
            resolver=lambda _host, _port: ["127.0.0.1"],
        )
        with self.assertRaises(InvariantError):
            private_service.create_channel(
                challenge_id=self.challenge_id,
                channel_type="GENERIC_WEBHOOK",
                display_name="Private target",
                destination="https://internal.example.test/hook",
                signing_secret="separate-secret",
                actor="owner@example.test",
                trust_delegation_confirmed=True,
            )

    def test_configuration_and_test_commands_are_idempotent(self) -> None:
        service = self.service()
        channel_kwargs = {
            "challenge_id": self.challenge_id,
            "channel_type": "GENERIC_WEBHOOK",
            "display_name": "Idempotent operators",
            "destination": "https://notify.example.test/limina",
            "signing_secret": "signing-secret-value",
            "actor": "owner@example.test",
            "trust_delegation_confirmed": True,
            "command_id": "channel-create-command",
        }
        first = service.create_channel(**channel_kwargs)
        second = service.create_channel(**channel_kwargs)
        self.assertEqual(second, first)
        with self.database.session() as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(NotificationChannel)), 1
            )

        delivery_id = service.enqueue_test(
            channel_id=first["id"],
            console_url="https://console.example.test",
            actor="owner@example.test",
            command_id="channel-test-command",
        )
        replayed_id = service.enqueue_test(
            channel_id=first["id"],
            console_url="https://console.example.test",
            actor="owner@example.test",
            command_id="channel-test-command",
        )
        self.assertEqual(replayed_id, delivery_id)
        with self.database.session() as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(NotificationOutbox)), 1
            )

        with self.assertRaises(ConflictError):
            service.set_channel_enabled(
                channel_id=first["id"],
                enabled=False,
                actor="owner@example.test",
                command_id="channel-test-command",
            )

    def test_delivery_re_resolves_and_rejects_dns_rebinding(self) -> None:
        resolutions = iter([["93.184.216.34"], ["127.0.0.1"]])
        sender = RecordingSender([TransportResult(200)])
        service = NotificationService(
            self.database,
            self.cipher,
            resolver=lambda _host, _port: next(resolutions),
            sender=sender,
            max_attempts=1,
            failure_attention_threshold=1,
        )
        self.create_channel_and_rule(service)
        started = datetime.now(UTC)
        episode = self.add_episode(source_key="request:rebind", opened_at=started)
        self.enqueue(service, episode.id, changed_at=started)
        job = service.claim_batch(worker_id="worker-a", changed_at=started)[0]
        result = service.deliver_claimed(
            outbox_id=job["id"], worker_id="worker-a", changed_at=started
        )
        self.assertEqual(result["status"], "DEAD_LETTER")
        self.assertEqual(result["response_class"], "DELIVERY_CONFIG_INVALID")
        self.assertEqual(sender.calls, [])

    def test_delivery_pins_the_revalidated_public_address(self) -> None:
        resolutions = iter([["93.184.216.34"], ["8.8.8.8"]])
        sender = RecordingSender([TransportResult(200)])
        service = NotificationService(
            self.database,
            self.cipher,
            resolver=lambda _host, _port: next(resolutions),
            sender=sender,
            max_attempts=1,
            failure_attention_threshold=1,
        )
        self.create_channel_and_rule(service)
        started = datetime.now(UTC)
        episode = self.add_episode(source_key="request:pin", opened_at=started)
        self.enqueue(service, episode.id, changed_at=started)
        job = service.claim_batch(worker_id="worker-a", changed_at=started)[0]

        result = service.deliver_claimed(
            outbox_id=job["id"], worker_id="worker-a", changed_at=started
        )

        self.assertEqual(result["status"], "DELIVERED")
        self.assertEqual(sender.calls[0][3], ("8.8.8.8",))

    def test_real_https_transport_uses_pinned_ip_and_original_sni(self) -> None:
        raw_socket = MagicMock()
        tls_socket = MagicMock()
        context = MagicMock()
        context.wrap_socket.return_value = tls_socket
        connection = _PinnedHTTPSConnection(
            "notify.example.test", 443, "93.184.216.34", timeout=10.0
        )
        connection._context = context

        with patch(
            "limina_cloud.notification_service.socket.create_connection",
            return_value=raw_socket,
        ) as create_connection:
            connection.connect()

        create_connection.assert_called_once_with(("93.184.216.34", 443), 10.0, None)
        context.wrap_socket.assert_called_once_with(
            raw_socket, server_hostname="notify.example.test"
        )
        self.assertIs(connection.sock, tls_socket)

    def test_outbox_is_transactional_deduplicated_and_cooled_down(self) -> None:
        service = self.service()
        self.create_channel_and_rule(service)
        started = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
        first = self.add_episode(source_key="request:first", opened_at=started)

        with (
            self.assertRaisesRegex(RuntimeError, "rollback"),
            self.database.session() as session,
            session.begin(),
        ):
            challenge = session.get(Challenge, self.challenge_id)
            episode = session.get(AttentionEpisode, first.id)
            assert challenge is not None and episode is not None
            service.enqueue_attention(
                session,
                challenge=challenge,
                episode=episode,
                console_url="https://console.example.test",
                changed_at=started,
            )
            raise RuntimeError("rollback")
        with self.database.session() as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(NotificationOutbox)), 0
            )

        delivery_ids = self.enqueue(service, first.id, changed_at=started)
        self.assertEqual(self.enqueue(service, first.id, changed_at=started), delivery_ids)

        second = self.add_episode(source_key="request:second", opened_at=started)
        self.assertEqual(
            self.enqueue(service, second.id, changed_at=started + timedelta(seconds=299)), []
        )
        later = self.enqueue(service, second.id, changed_at=started + timedelta(seconds=300))
        self.assertEqual(len(later), 1)
        with self.database.session() as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(NotificationOutbox)), 2
            )

    def test_generic_webhook_is_signed_and_history_contains_no_secrets(self) -> None:
        sender = RecordingSender([TransportResult(204)])
        service = self.service(sender)
        channel_id, _ = self.create_channel_and_rule(service)
        started = datetime.now(UTC)
        episode = self.add_episode(source_key="request:signed", opened_at=started)
        self.enqueue(service, episode.id, changed_at=started)

        job = service.claim_batch(worker_id="worker-a", changed_at=started)[0]
        result = service.deliver_claimed(
            outbox_id=job["id"], worker_id="worker-a", changed_at=started
        )
        self.assertEqual(result["status"], "DELIVERED")
        destination, headers, body, pinned_addresses = sender.calls[0]
        self.assertEqual(destination, "https://notify.example.test/limina")
        self.assertEqual(pinned_addresses, ("93.184.216.34",))
        timestamp = headers["X-Limina-Timestamp"]
        expected = hmac.new(
            b"signing-secret-value",
            timestamp.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(headers["X-Limina-Signature"], f"v1={expected}")
        self.assertEqual(headers["X-Limina-Delivery"], result["delivery_id"])
        payload = json.loads(body)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(
            set(payload), {"attention", "console_url", "delivery_id", "project", "schema_version"}
        )
        self.assertNotIn("signing-secret-value", body.decode())
        self.assertNotIn("notify.example.test/limina", body.decode())
        self.assertNotIn("sk_test-secret-value-should-not-leak", body.decode())
        self.assertIn("[redacted]", body.decode())

        history = json.dumps(service.delivery_history(channel_id), sort_keys=True)
        self.assertNotIn("signing-secret-value", history)
        self.assertNotIn("notify.example.test", history)

    def test_retry_dead_letter_materializes_then_success_clears_failure(self) -> None:
        sender = RecordingSender(
            [TransportResult(503), TransportResult(503), TransportResult(503), TransportResult(200)]
        )
        service = self.service(sender, max_attempts=3, failure_threshold=3)
        channel_id, _ = self.create_channel_and_rule(service)
        started = datetime.now(UTC)
        episode = self.add_episode(source_key="request:failing", opened_at=started)
        self.enqueue(service, episode.id, changed_at=started)

        status = ""
        claim_at = started
        for attempt in range(3):
            jobs = service.claim_batch(worker_id="worker-a", changed_at=claim_at)
            self.assertEqual(len(jobs), 1)
            result = service.deliver_claimed(
                outbox_id=jobs[0]["id"], worker_id="worker-a", changed_at=claim_at
            )
            status = result["status"]
            if result["next_attempt_at"]:
                claim_at = datetime.fromisoformat(result["next_attempt_at"]) + timedelta(seconds=1)
            self.assertEqual(result["attempt"], attempt + 1)
        self.assertEqual(status, "DEAD_LETTER")

        with self.database.session() as session:
            failure = session.scalar(
                select(AttentionEpisode).where(
                    AttentionEpisode.item_type == "notification_failure",
                    AttentionEpisode.challenge_id == self.challenge_id,
                )
            )
            assert failure is not None
            self.assertEqual(failure.status, "OPEN")
            self.assertEqual(failure.source_ref["channel_id"], channel_id)
            self.assertNotIn("notify.example.test", json.dumps(failure.source_ref))

        service.enqueue_test(
            channel_id=channel_id,
            console_url="https://console.example.test/settings/notifications",
            changed_at=claim_at,
        )
        test_job = service.claim_batch(worker_id="worker-a", changed_at=claim_at)[0]
        service.deliver_claimed(outbox_id=test_job["id"], worker_id="worker-a", changed_at=claim_at)
        with self.database.session() as session:
            failure = session.scalar(
                select(AttentionEpisode).where(
                    AttentionEpisode.item_type == "notification_failure",
                    AttentionEpisode.challenge_id == self.challenge_id,
                )
            )
            channel = session.get(NotificationChannel, channel_id)
            assert failure is not None and channel is not None
            self.assertEqual(failure.status, "CLOSED")
            self.assertEqual(channel.health, "HEALTHY")
            self.assertEqual(channel.consecutive_failures, 0)
            self.assertIsNone(channel.failure_started_delivery_id)

    def test_sqlite_claim_path_does_not_double_claim(self) -> None:
        service = self.service()
        self.create_channel_and_rule(service, name="Primary")
        self.create_channel_and_rule(service, name="Secondary")
        started = datetime.now(UTC)
        episode = self.add_episode(source_key="request:concurrent", opened_at=started)
        self.assertEqual(len(self.enqueue(service, episode.id, changed_at=started)), 2)
        barrier = threading.Barrier(2)

        def claim(worker: str) -> list[dict[str, object]]:
            barrier.wait()
            return service.claim_batch(worker_id=worker, limit=1, changed_at=started)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(claim, "worker-a")
            second = pool.submit(claim, "worker-b")
            claimed = first.result() + second.result()
        self.assertEqual(len(claimed), 2)
        self.assertEqual(len({item["id"] for item in claimed}), 2)
        with self.database.session() as session:
            workers = set(
                session.scalars(
                    select(NotificationOutbox.claimed_by).where(
                        NotificationOutbox.status == "CLAIMED"
                    )
                )
            )
            self.assertEqual(workers, {"worker-a", "worker-b"})

    def test_delivery_rows_never_have_body_or_destination_columns(self) -> None:
        columns = set(NotificationDelivery.__table__.columns.keys())
        self.assertTrue({"response_body", "request_body", "destination"}.isdisjoint(columns))


if __name__ == "__main__":
    unittest.main()
