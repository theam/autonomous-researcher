"""Durable, encrypted notification configuration and at-least-once delivery."""

from __future__ import annotations

import hashlib
import hmac
import http.client
import ipaddress
import json
import socket
import ssl
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any, TypeVar
from urllib.parse import quote, urlsplit, urlunsplit

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .attention_service import clear_notification_failure, record_notification_failure
from .database import Database
from .errors import ConflictError, InvariantError, NotFoundError
from .models import (
    AttentionEpisode,
    Challenge,
    CommandReceipt,
    NotificationChannel,
    NotificationDelivery,
    NotificationOutbox,
    NotificationRule,
    new_uuid,
    utcnow,
)
from .redaction import redact_secret_shapes
from .vault import SecretCipher

CHANNEL_TYPES = {"SLACK", "GENERIC_WEBHOOK"}
SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
SLACK_HOSTS = {"hooks.slack.com", "hooks.slack-gov.com"}
OUTBOX_PAYLOAD_VERSION = 1
MAX_PAYLOAD_BYTES = 16_384
MAX_BATCH_SIZE = 100
SAFE_TRANSPORT_ERRORS = {
    "TIMEOUT",
    "NETWORK_ERROR",
    "CHANNEL_DISABLED",
    "DELIVERY_CONFIG_INVALID",
}

Resolver = Callable[[str, int], Sequence[str]]
Sender = Callable[[str, dict[str, str], bytes, Sequence[str]], "TransportResult"]
Result = TypeVar("Result", bound=dict[str, Any])


@dataclass(frozen=True)
class TransportResult:
    """Transport outcome without a response body or destination details."""

    status_code: int | None
    error_code: str | None = None


def _now(value: datetime | None = None) -> datetime:
    return value or utcnow()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _required(label: str, value: Any, *, limit: int) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise InvariantError(f"{label.capitalize()} cannot be empty.", field=label)
    if len(text) > limit:
        raise InvariantError(f"{label.capitalize()} is too long.", field=label, limit=limit)
    return text


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sanitize_summary(value: str) -> str:
    single_line = " ".join(redact_secret_shapes(value).split())
    if not single_line:
        return "Attention requires review in Limina."
    return single_line[:280]


def _default_resolver(hostname: str, port: int) -> Sequence[str]:
    return sorted(
        {item[4][0] for item in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)}
    )


def _validate_public_addresses(hostname: str, port: int, resolver: Resolver) -> tuple[str, ...]:
    try:
        addresses = resolver(hostname, port)
    except OSError as exc:
        raise InvariantError("The notification destination cannot be resolved.") from exc
    if not addresses:
        raise InvariantError("The notification destination did not resolve to an address.")
    validated: set[str] = set()
    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise InvariantError("The notification destination resolved unexpectedly.") from exc
        if not address.is_global:
            raise InvariantError("Notification destinations must resolve only to public addresses.")
        validated.add(str(address))
    return tuple(sorted(validated))


def _validate_destination(
    url: str, channel_type: str, resolver: Resolver
) -> tuple[str, int, tuple[str, ...]]:
    try:
        parsed = urlsplit(url)
        port = parsed.port or 443
    except ValueError as exc:
        raise InvariantError("The notification destination URL is invalid.") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise InvariantError("Notification destinations must use HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise InvariantError("Notification destinations cannot contain credentials.")
    if parsed.fragment:
        raise InvariantError("Notification destinations cannot contain fragments.")
    hostname = parsed.hostname.rstrip(".").lower()
    if channel_type == "SLACK":
        if hostname not in SLACK_HOSTS or not parsed.path.startswith("/services/"):
            raise InvariantError("Slack channels require an approved Slack webhook URL.")
    elif channel_type != "GENERIC_WEBHOOK":
        raise InvariantError("Notification channel type is not supported.")
    addresses = _validate_public_addresses(hostname, port, resolver)
    return hostname, port, addresses


def _validate_console_url(value: str) -> str:
    url = _required("Console URL", value, limit=2_048)
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InvariantError("The Console URL must be an absolute HTTP or HTTPS URL.")
    if parsed.username is not None or parsed.password is not None:
        raise InvariantError("The Console URL cannot contain credentials.")
    return url


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Preserve the destination Host/SNI while connecting to a validated IP."""

    def __init__(self, hostname: str, port: int, pinned_address: str, *, timeout: float) -> None:
        super().__init__(hostname, port=port, timeout=timeout, context=ssl.create_default_context())
        self.pinned_address = pinned_address

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self.pinned_address, self.port),
            self.timeout,
            self.source_address,
        )
        if self._context is None:  # pragma: no cover - set in __init__
            raw_socket.close()
            raise ssl.SSLError("TLS context is unavailable")
        self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)


def _default_sender(
    url: str,
    headers: dict[str, str],
    body: bytes,
    pinned_addresses: Sequence[str],
) -> TransportResult:
    parsed = urlsplit(url)
    hostname = parsed.hostname
    if not hostname or not pinned_addresses:
        return TransportResult(status_code=None, error_code="DELIVERY_CONFIG_INVALID")
    port = parsed.port or 443
    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    request_headers = dict(headers)
    request_headers["Host"] = hostname if port == 443 else f"{hostname}:{port}"
    request_headers["Content-Length"] = str(len(body))

    saw_timeout = False
    for address in pinned_addresses:
        connection = _PinnedHTTPSConnection(hostname, port, address, timeout=10.0)
        try:
            connection.request("POST", target, body=body, headers=request_headers)
            response = connection.getresponse()
            return TransportResult(status_code=response.status)
        except TimeoutError:
            saw_timeout = True
        except (OSError, ssl.SSLError, http.client.HTTPException):
            continue
        finally:
            connection.close()
    return TransportResult(
        status_code=None,
        error_code="TIMEOUT" if saw_timeout else "NETWORK_ERROR",
    )


class NotificationService:
    """Own notification state while keeping credentials outside public data shapes."""

    def __init__(
        self,
        database: Database,
        secret_cipher: SecretCipher,
        *,
        resolver: Resolver = _default_resolver,
        sender: Sender = _default_sender,
        max_attempts: int = 5,
        failure_attention_threshold: int = 3,
        retry_base: timedelta = timedelta(seconds=30),
        retry_cap: timedelta = timedelta(hours=1),
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if failure_attention_threshold < 1:
            raise ValueError("failure_attention_threshold must be positive")
        if retry_base <= timedelta(0) or retry_cap < retry_base:
            raise ValueError("retry timing must be positive and bounded")
        self.database = database
        self.secret_cipher = secret_cipher
        self.resolver = resolver
        self.sender = sender
        self.max_attempts = max_attempts
        self.failure_attention_threshold = failure_attention_threshold
        self.retry_base = retry_base
        self.retry_cap = retry_cap

    def _execute(
        self,
        *,
        command_id: str | None,
        command_type: str,
        actor: str,
        operation: Callable[[Session], Result],
    ) -> Result:
        """Run a mutation and its optional idempotency receipt atomically."""

        if command_id is None:
            with self.database.session() as session, session.begin():
                return operation(session)
        command_id = _required("command ID", command_id, limit=64)
        actor = _required("actor", actor, limit=200)
        with self.database.session() as session:
            try:
                with session.begin():
                    receipt = session.get(CommandReceipt, command_id)
                    if receipt is not None:
                        if receipt.actor != actor or receipt.command_type != command_type:
                            raise ConflictError(
                                "The idempotency key was already used for another operation."
                            )
                        return receipt.result  # type: ignore[return-value]
                    result = operation(session)
                    session.add(
                        CommandReceipt(
                            command_id=command_id,
                            command_type=command_type,
                            actor=actor,
                            result=result,
                        )
                    )
                return result
            except IntegrityError as exc:
                session.rollback()
                with self.database.session() as retry:
                    receipt = retry.get(CommandReceipt, command_id)
                    if (
                        receipt is not None
                        and receipt.actor == actor
                        and receipt.command_type == command_type
                    ):
                        return receipt.result  # type: ignore[return-value]
                raise ConflictError(
                    "The notification command conflicted with another concurrent write."
                ) from exc

    def create_channel(
        self,
        *,
        challenge_id: str,
        channel_type: str,
        display_name: str,
        destination: str,
        signing_secret: str | None,
        actor: str,
        trust_delegation_confirmed: bool,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_type = str(channel_type).strip().upper()
        if normalized_type not in CHANNEL_TYPES:
            raise InvariantError("Notification channel type is not supported.")
        if not trust_delegation_confirmed:
            raise InvariantError(
                "Confirm the external attention-summary trust delegation before saving."
            )
        display_name = _required("channel name", display_name, limit=160)
        actor = _required("actor", actor, limit=200)
        destination = _required("destination", destination, limit=4_096)
        hostname, _port, _addresses = _validate_destination(
            destination, normalized_type, self.resolver
        )
        secret_value: dict[str, str] = {"url": destination}
        if normalized_type == "GENERIC_WEBHOOK":
            secret_value["signing_secret"] = _required(
                "signing secret", signing_secret, limit=4_096
            )
        elif signing_secret:
            raise InvariantError("Slack channels do not accept a separate signing secret.")

        def operation(session: Session) -> dict[str, Any]:
            challenge = session.get(Challenge, challenge_id)
            if challenge is None:
                raise NotFoundError("The notification project does not exist.")
            channel_id = new_uuid()
            ciphertext = self.secret_cipher.encrypt(
                project=challenge.slug,
                name=self._secret_name(channel_id),
                value=_canonical_json(secret_value).decode(),
            )
            channel = NotificationChannel(
                id=channel_id,
                challenge_id=challenge.id,
                channel_type=normalized_type,
                display_name=display_name,
                destination_metadata={"scheme": "https", "host": hostname},
                secret_ciphertext=ciphertext,
                enabled=True,
                health="UNKNOWN",
                trust_confirmed_by=actor,
                trust_confirmed_at=utcnow(),
                created_by=actor,
            )
            session.add(channel)
            session.flush()
            return self._public_channel(channel)

        return self._execute(
            command_id=command_id,
            command_type="notification.channel.create",
            actor=actor,
            operation=operation,
        )

    def create_rule(
        self,
        *,
        challenge_id: str,
        channel_id: str,
        display_name: str,
        attention_types: Sequence[str],
        severities: Sequence[str],
        cooldown_seconds: int,
        actor: str,
        command_id: str | None = None,
    ) -> dict[str, Any]:
        if cooldown_seconds < 0 or cooldown_seconds > 86_400:
            raise InvariantError("Notification cooldown must be between 0 and 86400 seconds.")
        normalized_types = sorted(
            {_required("attention type", item, limit=32) for item in attention_types}
        )
        normalized_severities = sorted({str(item).strip().upper() for item in severities})
        if any(item not in SEVERITIES for item in normalized_severities):
            raise InvariantError("Notification rule severity is not supported.")
        actor = _required("actor", actor, limit=200)

        def operation(session: Session) -> dict[str, Any]:
            channel = session.get(NotificationChannel, channel_id)
            if channel is None or channel.challenge_id != challenge_id:
                raise NotFoundError("The notification channel does not exist in this project.")
            rule = NotificationRule(
                challenge_id=challenge_id,
                channel_id=channel_id,
                display_name=_required("rule name", display_name, limit=160),
                attention_types=normalized_types,
                severities=normalized_severities,
                cooldown_seconds=cooldown_seconds,
                enabled=True,
                created_by=actor,
            )
            session.add(rule)
            session.flush()
            return self._public_rule(rule)

        return self._execute(
            command_id=command_id,
            command_type="notification.rule.create",
            actor=actor,
            operation=operation,
        )

    def set_channel_enabled(
        self,
        *,
        channel_id: str,
        enabled: bool,
        changed_at: datetime | None = None,
        actor: str = "limina",
        command_id: str | None = None,
    ) -> dict[str, Any]:
        changed_at = _now(changed_at)

        def operation(session: Session) -> dict[str, Any]:
            channel = session.scalar(
                select(NotificationChannel)
                .where(NotificationChannel.id == channel_id)
                .with_for_update()
            )
            if channel is None:
                raise NotFoundError("The notification channel does not exist.")
            if channel.enabled == enabled:
                return self._public_channel(channel)
            channel.enabled = enabled
            channel.health = "UNKNOWN" if enabled else "DISABLED"
            channel.consecutive_failures = 0
            if channel.failure_started_delivery_id:
                clear_notification_failure(
                    session,
                    challenge_id=channel.challenge_id,
                    source_key=self._failure_source_key(channel),
                    changed_at=changed_at,
                )
            channel.failure_started_delivery_id = None
            channel.updated_at = changed_at
            channel.version += 1
            return self._public_channel(channel)

        return self._execute(
            command_id=command_id,
            command_type="notification.channel.state",
            actor=actor,
            operation=operation,
        )

    def list_channels(self, challenge_id: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            channels = session.scalars(
                select(NotificationChannel)
                .where(NotificationChannel.challenge_id == challenge_id)
                .order_by(NotificationChannel.display_name, NotificationChannel.id)
            ).all()
            return [self._public_channel(item) for item in channels]

    def list_rules(self, challenge_id: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            rules = session.scalars(
                select(NotificationRule)
                .where(NotificationRule.challenge_id == challenge_id)
                .order_by(NotificationRule.display_name, NotificationRule.id)
            ).all()
            return [self._public_rule(item) for item in rules]

    def enqueue_attention(
        self,
        session: Session,
        *,
        challenge: Challenge,
        episode: AttentionEpisode,
        console_url: str,
        event_type: str = "attention.opened",
        changed_at: datetime | None = None,
    ) -> list[str]:
        """Append matching outbox rows inside the caller's state-change transaction."""

        if episode.challenge_id != challenge.id:
            raise InvariantError("The attention episode belongs to another project.")
        changed_at = _now(changed_at)
        console_url = _validate_console_url(console_url)
        rules = session.scalars(
            select(NotificationRule)
            .join(NotificationChannel, NotificationChannel.id == NotificationRule.channel_id)
            .where(
                NotificationRule.challenge_id == challenge.id,
                NotificationRule.enabled.is_(True),
                NotificationChannel.enabled.is_(True),
            )
            .order_by(NotificationRule.id)
            .with_for_update()
        ).all()
        delivery_ids: list[str] = []
        for rule in rules:
            if rule.attention_types and episode.item_type not in rule.attention_types:
                continue
            if rule.severities and episode.severity not in rule.severities:
                continue
            dedupe_key = hashlib.sha256(f"{event_type}\0{episode.id}".encode()).hexdigest()
            existing = session.scalar(
                select(NotificationOutbox.delivery_id).where(
                    NotificationOutbox.rule_id == rule.id,
                    NotificationOutbox.dedupe_key == dedupe_key,
                )
            )
            if existing is not None:
                delivery_ids.append(existing)
                continue
            if rule.last_enqueued_at is not None and _aware(changed_at) - _aware(
                rule.last_enqueued_at
            ) < timedelta(seconds=rule.cooldown_seconds):
                continue
            delivery_id = new_uuid()
            session.add(
                NotificationOutbox(
                    id=new_uuid(),
                    delivery_id=delivery_id,
                    challenge_id=challenge.id,
                    rule_id=rule.id,
                    channel_id=rule.channel_id,
                    attention_episode_id=episode.id,
                    event_type=event_type,
                    payload_version=OUTBOX_PAYLOAD_VERSION,
                    payload=self._attention_payload(
                        challenge=challenge,
                        episode=episode,
                        console_url=console_url,
                        delivery_id=delivery_id,
                        changed_at=changed_at,
                    ),
                    dedupe_key=dedupe_key,
                    status="PENDING",
                    next_attempt_at=changed_at,
                    created_at=changed_at,
                    updated_at=changed_at,
                )
            )
            rule.last_enqueued_at = changed_at
            rule.updated_at = changed_at
            rule.version += 1
            delivery_ids.append(delivery_id)
        session.flush()
        return delivery_ids

    def enqueue_test(
        self,
        *,
        channel_id: str,
        console_url: str,
        changed_at: datetime | None = None,
        actor: str = "limina",
        command_id: str | None = None,
    ) -> str:
        changed_at = _now(changed_at)
        console_url = _validate_console_url(console_url)

        def operation(session: Session) -> dict[str, Any]:
            channel = session.get(NotificationChannel, channel_id)
            if channel is None:
                raise NotFoundError("The notification channel does not exist.")
            challenge = session.get(Challenge, channel.challenge_id)
            if challenge is None:
                raise NotFoundError("The notification project does not exist.")
            delivery_id = new_uuid()
            payload = {
                "schema_version": OUTBOX_PAYLOAD_VERSION,
                "delivery_id": delivery_id,
                "project": {"slug": challenge.slug, "name": challenge.name},
                "attention": {
                    "type": "delivery_test",
                    "severity": "LOW",
                    "summary": "Limina notification delivery test.",
                    "age_seconds": 0,
                },
                "console_url": console_url,
            }
            session.add(
                NotificationOutbox(
                    id=new_uuid(),
                    delivery_id=delivery_id,
                    challenge_id=challenge.id,
                    rule_id=None,
                    channel_id=channel.id,
                    event_type="notification.test",
                    payload_version=OUTBOX_PAYLOAD_VERSION,
                    payload=payload,
                    dedupe_key=hashlib.sha256(f"test\0{delivery_id}".encode()).hexdigest(),
                    status="PENDING",
                    next_attempt_at=changed_at,
                    is_test=True,
                    created_at=changed_at,
                    updated_at=changed_at,
                )
            )
            channel.last_tested_at = changed_at
            channel.updated_at = changed_at
            channel.version += 1
            return {"delivery_id": delivery_id}

        return self._execute(
            command_id=command_id,
            command_type="notification.channel.test",
            actor=actor,
            operation=operation,
        )["delivery_id"]

    def claim_batch(
        self,
        *,
        worker_id: str,
        limit: int = 25,
        lease: timedelta = timedelta(minutes=2),
        changed_at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        worker_id = _required("worker ID", worker_id, limit=200)
        if limit < 1 or limit > MAX_BATCH_SIZE:
            raise InvariantError(f"Notification claim limit must be 1 to {MAX_BATCH_SIZE}.")
        if lease <= timedelta(0):
            raise InvariantError("Notification claim lease must be positive.")
        changed_at = _now(changed_at)
        eligible = or_(
            and_(
                NotificationOutbox.status.in_(("PENDING", "RETRY")),
                NotificationOutbox.next_attempt_at <= changed_at,
            ),
            and_(
                NotificationOutbox.status == "CLAIMED",
                NotificationOutbox.claim_expires_at <= changed_at,
            ),
        )
        with self.database.session() as session, session.begin():
            statement = (
                select(NotificationOutbox)
                .where(eligible)
                .order_by(
                    NotificationOutbox.next_attempt_at,
                    NotificationOutbox.created_at,
                    NotificationOutbox.id,
                )
            )
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                candidates = session.scalars(
                    statement.limit(limit).with_for_update(skip_locked=True)
                ).all()
            else:
                candidate_ids = list(
                    session.scalars(
                        statement.with_only_columns(NotificationOutbox.id).limit(
                            min(MAX_BATCH_SIZE, limit * 4)
                        )
                    )
                )
                candidates = []
                for candidate_id in candidate_ids:
                    claimed = session.execute(
                        update(NotificationOutbox)
                        .where(NotificationOutbox.id == candidate_id, eligible)
                        .values(
                            status="CLAIMED",
                            claimed_by=worker_id,
                            claimed_at=changed_at,
                            claim_expires_at=changed_at + lease,
                            updated_at=changed_at,
                            version=NotificationOutbox.version + 1,
                        )
                    )
                    if claimed.rowcount == 1:
                        candidates.append(session.get(NotificationOutbox, candidate_id))
                    if len(candidates) >= limit:
                        break
            result: list[dict[str, Any]] = []
            for item in candidates:
                if item is None:
                    continue
                if item.status != "CLAIMED" or item.claimed_by != worker_id:
                    item.status = "CLAIMED"
                    item.claimed_by = worker_id
                    item.claimed_at = changed_at
                    item.claim_expires_at = changed_at + lease
                    item.updated_at = changed_at
                    item.version += 1
                result.append(self._public_job(item))
            return result

    def deliver_claimed(
        self,
        *,
        outbox_id: str,
        worker_id: str,
        changed_at: datetime | None = None,
    ) -> dict[str, Any]:
        worker_id = _required("worker ID", worker_id, limit=200)
        changed_at = _now(changed_at)
        with self.database.session() as session:
            outbox = session.get(NotificationOutbox, outbox_id)
            if outbox is None:
                raise NotFoundError("The notification delivery does not exist.")
            if outbox.status != "CLAIMED" or outbox.claimed_by != worker_id:
                raise ConflictError("The notification delivery is not claimed by this worker.")
            channel = session.get(NotificationChannel, outbox.channel_id)
            challenge = session.get(Challenge, outbox.challenge_id)
            if channel is None or challenge is None:
                raise ConflictError("The notification delivery configuration no longer exists.")
            channel_snapshot = {
                "id": channel.id,
                "type": channel.channel_type,
                "enabled": channel.enabled,
                "ciphertext": channel.secret_ciphertext,
            }
            payload = dict(outbox.payload)
            delivery_id = outbox.delivery_id
            attempt_number = outbox.attempts + 1
            is_test = outbox.is_test

        started = monotonic()
        try:
            result = self._send(
                challenge_slug=challenge.slug,
                channel=channel_snapshot,
                payload=payload,
                delivery_id=delivery_id,
                is_test=is_test,
                changed_at=changed_at,
            )
        except InvariantError:
            result = TransportResult(status_code=None, error_code="DELIVERY_CONFIG_INVALID")
        if result.error_code not in SAFE_TRANSPORT_ERRORS:
            result = TransportResult(
                status_code=result.status_code,
                error_code="TRANSPORT_ERROR" if result.error_code else None,
            )
        completed_at = utcnow()
        duration_ms = max(0, int((monotonic() - started) * 1_000))
        response_class, retryable, success = self._classify(result)

        with self.database.session() as session, session.begin():
            outbox = session.scalar(
                select(NotificationOutbox)
                .where(NotificationOutbox.id == outbox_id)
                .with_for_update()
            )
            if outbox is None or outbox.status != "CLAIMED" or outbox.claimed_by != worker_id:
                raise ConflictError("The notification delivery claim changed during delivery.")
            channel = session.scalar(
                select(NotificationChannel)
                .where(NotificationChannel.id == outbox.channel_id)
                .with_for_update()
            )
            challenge = session.get(Challenge, outbox.challenge_id)
            if channel is None or challenge is None:
                raise ConflictError("The notification delivery configuration no longer exists.")
            outbox.attempts = attempt_number
            outbox.last_http_status = result.status_code
            outbox.last_error_class = result.error_code
            outbox.claimed_by = None
            outbox.claimed_at = None
            outbox.claim_expires_at = None
            outbox.updated_at = completed_at
            outbox.version += 1

            if success:
                outcome = "DELIVERED"
                outbox.status = "DELIVERED"
                outbox.delivered_at = completed_at
                channel.health = "HEALTHY" if channel.enabled else "DISABLED"
                channel.consecutive_failures = 0
                channel.last_success_at = completed_at
                if channel.failure_started_delivery_id:
                    clear_notification_failure(
                        session,
                        challenge_id=channel.challenge_id,
                        source_key=self._failure_source_key(channel),
                        changed_at=completed_at,
                    )
                channel.failure_started_delivery_id = None
            elif result.error_code == "CHANNEL_DISABLED":
                outcome = "DEAD_LETTER"
                outbox.status = "DEAD_LETTER"
                outbox.dead_lettered_at = completed_at
                channel.health = "DISABLED"
                channel.consecutive_failures = 0
                if channel.failure_started_delivery_id:
                    clear_notification_failure(
                        session,
                        challenge_id=channel.challenge_id,
                        source_key=self._failure_source_key(channel),
                        changed_at=completed_at,
                    )
                channel.failure_started_delivery_id = None
            else:
                channel.consecutive_failures += 1
                channel.last_failure_at = completed_at
                channel.health = "DEGRADED"
                if channel.failure_started_delivery_id is None:
                    channel.failure_started_delivery_id = outbox.delivery_id
                if retryable and attempt_number < self.max_attempts:
                    outcome = "RETRY"
                    outbox.status = "RETRY"
                    outbox.next_attempt_at = completed_at + self._retry_delay(
                        outbox.delivery_id, attempt_number
                    )
                else:
                    outcome = "DEAD_LETTER"
                    outbox.status = "DEAD_LETTER"
                    outbox.dead_lettered_at = completed_at
                if (
                    channel.consecutive_failures >= self.failure_attention_threshold
                    or outcome == "DEAD_LETTER"
                ):
                    record_notification_failure(
                        session,
                        challenge=challenge,
                        source_key=self._failure_source_key(channel),
                        title=f"Notification delivery failing: {channel.display_name}",
                        body="Limina could not deliver a notification. Review channel health.",
                        source_ref={
                            "channel_id": channel.id,
                            "delivery_id": channel.failure_started_delivery_id,
                        },
                    )
            channel.updated_at = completed_at
            channel.version += 1
            session.add(
                NotificationDelivery(
                    id=new_uuid(),
                    outbox_id=outbox.id,
                    delivery_id=outbox.delivery_id,
                    challenge_id=outbox.challenge_id,
                    channel_id=outbox.channel_id,
                    attempt_number=attempt_number,
                    outcome=outcome,
                    response_class=response_class,
                    http_status=result.status_code,
                    error_code=result.error_code,
                    worker_id=worker_id,
                    started_at=changed_at,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                )
            )
            return {
                "delivery_id": outbox.delivery_id,
                "status": outbox.status,
                "attempt": attempt_number,
                "response_class": response_class,
                "http_status": result.status_code,
                "next_attempt_at": (
                    outbox.next_attempt_at.isoformat() if outbox.status == "RETRY" else None
                ),
            }

    def run_once(
        self,
        *,
        worker_id: str,
        limit: int = 25,
        changed_at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        jobs = self.claim_batch(worker_id=worker_id, limit=limit, changed_at=changed_at)
        return [
            self.deliver_claimed(outbox_id=item["id"], worker_id=worker_id, changed_at=changed_at)
            for item in jobs
        ]

    def delivery_history(self, channel_id: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            rows = session.scalars(
                select(NotificationDelivery)
                .where(NotificationDelivery.channel_id == channel_id)
                .order_by(NotificationDelivery.completed_at.desc(), NotificationDelivery.id.desc())
            ).all()
            return [
                {
                    "delivery_id": item.delivery_id,
                    "attempt": item.attempt_number,
                    "outcome": item.outcome,
                    "response_class": item.response_class,
                    "http_status": item.http_status,
                    "error_code": item.error_code,
                    "completed_at": item.completed_at.isoformat(),
                }
                for item in rows
            ]

    def _send(
        self,
        *,
        challenge_slug: str,
        channel: dict[str, Any],
        payload: dict[str, Any],
        delivery_id: str,
        is_test: bool,
        changed_at: datetime,
    ) -> TransportResult:
        if not channel["enabled"] and not is_test:
            return TransportResult(status_code=None, error_code="CHANNEL_DISABLED")
        plaintext = self.secret_cipher.decrypt(
            project=challenge_slug,
            name=self._secret_name(channel["id"]),
            ciphertext=channel["ciphertext"],
        )
        try:
            secret = json.loads(plaintext)
        except json.JSONDecodeError as exc:
            raise InvariantError("The notification channel credential is invalid.") from exc
        if not isinstance(secret, dict) or not isinstance(secret.get("url"), str):
            raise InvariantError("The notification channel credential is invalid.")
        destination = secret["url"]
        _hostname, _port, pinned_addresses = _validate_destination(
            destination, channel["type"], self.resolver
        )

        if channel["type"] == "SLACK":
            body = self._slack_body(payload)
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "Limina-Notifications/1",
                "X-Limina-Delivery": delivery_id,
            }
        else:
            signing_secret = secret.get("signing_secret")
            if not isinstance(signing_secret, str) or not signing_secret:
                raise InvariantError("The webhook signing credential is invalid.")
            body = _canonical_json(payload)
            timestamp = str(int(_aware(changed_at).timestamp()))
            signature = hmac.new(
                signing_secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
            ).hexdigest()
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "Limina-Notifications/1",
                "X-Limina-Delivery": delivery_id,
                "X-Limina-Timestamp": timestamp,
                "X-Limina-Signature": f"v1={signature}",
            }
        if len(body) > MAX_PAYLOAD_BYTES:
            raise InvariantError("The notification payload exceeds the delivery size limit.")
        sensitive_values = [
            value for value in secret.values() if isinstance(value, str) and len(value) >= 8
        ]
        if any(value.encode() in body for value in sensitive_values):
            raise InvariantError("A notification payload contains channel credentials.")
        return self.sender(destination, headers, body, pinned_addresses)

    @staticmethod
    def _classify(result: TransportResult) -> tuple[str, bool, bool]:
        status = result.status_code
        if status is None:
            response_class = result.error_code or "TRANSPORT_ERROR"
            retryable = response_class not in {
                "CHANNEL_DISABLED",
                "DELIVERY_CONFIG_INVALID",
            }
            return response_class, retryable, False
        if 200 <= status < 300:
            return "HTTP_2XX", False, True
        if status in {408, 425, 429} or status >= 500:
            return f"HTTP_{status}", True, False
        return f"HTTP_{status}", False, False

    def _retry_delay(self, delivery_id: str, attempt_number: int) -> timedelta:
        exponential = self.retry_base.total_seconds() * (2 ** max(0, attempt_number - 1))
        bounded = min(exponential, self.retry_cap.total_seconds())
        digest = hashlib.sha256(f"{delivery_id}:{attempt_number}".encode()).digest()
        jitter = int.from_bytes(digest[:2], "big") / 65_535 * min(bounded * 0.25, 60)
        return timedelta(seconds=bounded + jitter)

    @staticmethod
    def _attention_payload(
        *,
        challenge: Challenge,
        episode: AttentionEpisode,
        console_url: str,
        delivery_id: str,
        changed_at: datetime,
    ) -> dict[str, Any]:
        age_seconds = max(0, int((_aware(changed_at) - _aware(episode.opened_at)).total_seconds()))
        parsed_console = urlsplit(console_url)
        attention_path = f"{parsed_console.path.rstrip('/')}/attention/{quote(episode.id, safe='')}"
        attention_url = urlunsplit(
            (
                parsed_console.scheme,
                parsed_console.netloc,
                attention_path,
                "",
                "",
            )
        )
        return {
            "schema_version": OUTBOX_PAYLOAD_VERSION,
            "delivery_id": delivery_id,
            "project": {"slug": challenge.slug, "name": challenge.name},
            "attention": {
                "type": episode.item_type,
                "severity": episode.severity,
                "summary": _sanitize_summary(episode.body),
                "age_seconds": age_seconds,
            },
            "console_url": attention_url,
        }

    @staticmethod
    def _slack_body(payload: dict[str, Any]) -> bytes:
        project = payload["project"]
        attention = payload["attention"]
        text = (
            f"[{NotificationService._slack_escape(attention['severity'])}] "
            f"{NotificationService._slack_escape(project['name'])} — "
            f"{NotificationService._slack_escape(attention['type'])}: "
            f"{NotificationService._slack_escape(attention['summary'])} "
            f"({int(attention['age_seconds'])}s old) "
            f"<{NotificationService._slack_escape(payload['console_url'])}|Open in Limina>"
        )
        return _canonical_json(
            {
                "text": text,
                "blocks": [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": text},
                    }
                ],
            }
        )

    @staticmethod
    def _slack_escape(value: Any) -> str:
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    @staticmethod
    def _secret_name(channel_id: str) -> str:
        return f"notification:{channel_id}"

    @staticmethod
    def _failure_source_key(channel: NotificationChannel) -> str:
        if channel.failure_started_delivery_id is None:
            raise InvariantError("The notification channel has no active failure episode.")
        return f"channel:{channel.id}:failure:{channel.failure_started_delivery_id}"

    @staticmethod
    def _public_channel(channel: NotificationChannel) -> dict[str, Any]:
        return {
            "id": channel.id,
            "project_id": channel.challenge_id,
            "type": channel.channel_type,
            "display_name": channel.display_name,
            "destination": dict(channel.destination_metadata),
            "configured": bool(channel.secret_ciphertext),
            "enabled": channel.enabled,
            "health": channel.health,
            "consecutive_failures": channel.consecutive_failures,
            "last_success_at": (
                channel.last_success_at.isoformat() if channel.last_success_at else None
            ),
            "last_failure_at": (
                channel.last_failure_at.isoformat() if channel.last_failure_at else None
            ),
            "last_tested_at": (
                channel.last_tested_at.isoformat() if channel.last_tested_at else None
            ),
            "version": channel.version,
        }

    @staticmethod
    def _public_rule(rule: NotificationRule) -> dict[str, Any]:
        return {
            "id": rule.id,
            "project_id": rule.challenge_id,
            "channel_id": rule.channel_id,
            "display_name": rule.display_name,
            "attention_types": list(rule.attention_types),
            "severities": list(rule.severities),
            "cooldown_seconds": rule.cooldown_seconds,
            "enabled": rule.enabled,
            "version": rule.version,
        }

    @staticmethod
    def _public_job(item: NotificationOutbox) -> dict[str, Any]:
        return {
            "id": item.id,
            "delivery_id": item.delivery_id,
            "project_id": item.challenge_id,
            "channel_id": item.channel_id,
            "event_type": item.event_type,
            "status": item.status,
            "attempts": item.attempts,
            "is_test": item.is_test,
        }
