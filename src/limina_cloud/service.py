"""Transactional command service for the Limina challenge runtime.

The service owns all research graph invariants. Transports may expose these
commands over a CLI, HTTP, MCP, or a worker protocol without reimplementing
the rules.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar
from uuid import uuid4

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Database
from .errors import ConflictError, InvariantError, LeaseConflictError, NotFoundError
from .models import (
    Artifact,
    ArtifactRevision,
    Challenge,
    CommandReceipt,
    CoordinatorState,
    Event,
    InboxMessage,
    Observation,
    ProjectResource,
    WorkLease,
    utcnow,
)
from .project_service import ProjectServiceMixin
from .research_service import ResearchServiceMixin
from .runtime_environment import is_reserved_resource_name
from .vault import SecretCipher

Result = TypeVar("Result", bound=dict[str, Any])
ARTIFACT_ID_RE = re.compile(r"^(H|E|F|L|CR|SR)\d{3,}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RESOURCE_VALUE_LIMIT = 32_768
PROJECT_TRANSITIONS: dict[str, dict[str, str]] = {
    "start": {"CREATED": "RUNNING", "STOPPED": "RUNNING"},
    "pause": {"RUNNING": "PAUSED", "WAITING": "PAUSED"},
    "resume": {
        "PAUSED": "RUNNING",
        "WAITING": "RUNNING",
        "STOPPED": "RUNNING",
        "FAILED": "RUNNING",
    },
    "stop": {
        "CREATED": "STOPPED",
        "RUNNING": "STOPPED",
        "WAITING": "STOPPED",
        "PAUSED": "STOPPED",
        "FAILED": "STOPPED",
    },
}


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return _aware(value).isoformat()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class ChallengeService(ProjectServiceMixin, ResearchServiceMixin):
    def __init__(self, database: Database, secret_cipher: SecretCipher | None = None) -> None:
        self.database = database
        self.secret_cipher = secret_cipher

    def get_challenge(self, slug: str) -> dict[str, Any]:
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            coordinator = session.get(CoordinatorState, challenge.id)
            return self._challenge_dict(challenge, coordinator)

    def status(self, slug: str) -> dict[str, Any]:
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            coordinator = session.get(CoordinatorState, challenge.id)
            grouped = session.execute(
                select(Artifact.kind, Artifact.status, func.count())
                .where(Artifact.challenge_id == challenge.id)
                .group_by(Artifact.kind, Artifact.status)
            ).all()
            counts: dict[str, dict[str, int]] = {}
            for kind, status, count in grouped:
                counts.setdefault(kind, {})[status] = count
            running = session.scalars(
                select(Artifact)
                .where(
                    Artifact.challenge_id == challenge.id,
                    Artifact.kind == "E",
                    Artifact.status == "RUNNING",
                )
                .order_by(Artifact.artifact_id)
            ).all()
            pending_inbox = session.scalar(
                select(func.count())
                .select_from(InboxMessage)
                .where(
                    InboxMessage.challenge_id == challenge.id,
                    InboxMessage.status == "PENDING",
                )
            )
            last_event = session.scalar(
                select(func.max(Event.sequence)).where(Event.challenge_id == challenge.id)
            )
            return {
                "challenge": self._challenge_dict(challenge, coordinator),
                "counts": counts,
                "running_experiments": [self._artifact_dict(item) for item in running],
                "pending_inbox": pending_inbox or 0,
                "last_event_sequence": last_event or 0,
            }

    def claim_coordinator(
        self,
        *,
        slug: str,
        ttl_seconds: int,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        if ttl_seconds < 30 or ttl_seconds > 86_400:
            raise InvariantError("Lease TTL must be between 30 seconds and 24 hours.")

        def operation(session: Session) -> dict[str, Any]:
            challenge = self._challenge(session, slug)
            lease = self._acquire_lease(
                session,
                challenge_id=challenge.id,
                scope="coordinator",
                owner=actor,
                ttl_seconds=ttl_seconds,
            )
            self._record_event(
                session,
                challenge=challenge,
                event_type="coordinator.claimed",
                actor=actor,
                command_id=command_id,
                payload={"expires_at": _iso(lease["expires_at"])},
            )
            return {
                "scope": "coordinator",
                "owner": lease["owner"],
                "token": lease["token"],
                "expires_at": _iso(lease["expires_at"]),
                "version": lease["version"],
            }

        return self._execute(command_id, "coordinator.claim", actor, operation)

    def release_coordinator(
        self,
        *,
        slug: str,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        def operation(session: Session) -> dict[str, Any]:
            challenge = self._challenge(session, slug)
            result = session.execute(
                delete(WorkLease).where(
                    WorkLease.challenge_id == challenge.id,
                    WorkLease.scope == "coordinator",
                    WorkLease.owner == actor,
                )
            )
            if result.rowcount != 1:
                existing = session.get(WorkLease, (challenge.id, "coordinator"))
                raise LeaseConflictError(
                    "The coordinator lease is not owned by this worker.",
                    scope="coordinator",
                    owner=existing.owner if existing else None,
                    actor=actor,
                )
            self._record_event(
                session,
                challenge=challenge,
                event_type="coordinator.released",
                actor=actor,
                command_id=command_id,
                payload={},
            )
            return {"scope": "coordinator", "owner": actor, "released": True}

        return self._execute(command_id, "coordinator.release", actor, operation)

    def checkpoint_coordinator(
        self,
        *,
        slug: str,
        current_objective: str,
        next_step: str,
        blocker: str,
        status: str,
        worker_id: str | None,
        continuation_id: str | None,
        inbox_cursor: int,
        expected_version: int,
        actor: str,
        command_id: str,
        acknowledge_message_ids: list[str] | None = None,
        wake_at: datetime | None = None,
    ) -> dict[str, Any]:
        self._require_text("current objective", current_objective)
        self._require_text("next step", next_step)
        status = status.upper()
        if status not in {
            "CREATED",
            "RUNNING",
            "WAITING",
            "PAUSED",
            "STOPPED",
            "COMPLETE",
            "FAILED",
        }:
            raise InvariantError(
                "Runtime status must be CREATED, RUNNING, WAITING, PAUSED, STOPPED, "
                "COMPLETE, or FAILED."
            )

        def operation(session: Session) -> dict[str, Any]:
            challenge = self._challenge(session, slug)
            message_ids = set(acknowledge_message_ids or [])
            messages: list[InboxMessage] = []
            if message_ids:
                messages = list(
                    session.scalars(
                        select(InboxMessage).where(
                            InboxMessage.challenge_id == challenge.id,
                            InboxMessage.id.in_(message_ids),
                        )
                    ).all()
                )
                if len(messages) != len(message_ids):
                    found = {message.id for message in messages}
                    missing = sorted(message_ids - found)
                    raise NotFoundError(
                        "One or more inbox messages do not exist in this challenge.",
                        message_ids=missing,
                    )
            result = session.execute(
                update(CoordinatorState)
                .where(
                    CoordinatorState.challenge_id == challenge.id,
                    CoordinatorState.version == expected_version,
                )
                .values(
                    current_objective=current_objective.strip(),
                    next_step=next_step.strip(),
                    blocker=blocker.strip() or "None",
                    status=status,
                    worker_id=worker_id,
                    continuation_id=continuation_id,
                    inbox_cursor=inbox_cursor,
                    heartbeat_at=utcnow(),
                    wake_at=wake_at,
                    updated_at=utcnow(),
                    version=CoordinatorState.version + 1,
                )
            )
            if result.rowcount != 1:
                current = session.get(CoordinatorState, challenge.id)
                current_version = current.version if current else "?"
                raise ConflictError(
                    f"Coordinator state changed from v{expected_version} to v{current_version}.",
                    expected_version=expected_version,
                    current_version=current.version if current else None,
                )
            acknowledged_at = utcnow()
            for message in messages:
                message.status = "ACKNOWLEDGED"
                message.acknowledged_at = acknowledged_at
            session.flush()
            coordinator = session.get(CoordinatorState, challenge.id)
            self._record_event(
                session,
                challenge=challenge,
                event_type="coordinator.checkpointed",
                actor=actor,
                command_id=command_id,
                payload={
                    "status": status,
                    "version": coordinator.version,
                    "worker_id": worker_id,
                    "continuation_id": continuation_id,
                    "inbox_cursor": inbox_cursor,
                    "messages_acknowledged": len(messages),
                    "wake_at": _iso(wake_at),
                },
            )
            return self._coordinator_dict(coordinator)

        return self._execute(command_id, "coordinator.checkpoint", actor, operation)

    def send_message(
        self,
        *,
        slug: str,
        kind: str,
        body: str,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        kind = kind.upper()
        if kind not in {"STEER", "INTERRUPT", "ANSWER", "APPROVAL", "COMMENT", "BLOCKER"}:
            raise InvariantError(
                "Message kind must be STEER, INTERRUPT, ANSWER, APPROVAL, COMMENT, or BLOCKER."
            )
        self._require_text("message", body)
        if len(body) > 32_768:
            raise InvariantError("Message must be at most 32768 characters.")

        def operation(session: Session) -> dict[str, Any]:
            challenge = self._challenge(session, slug)
            message = InboxMessage(
                challenge_id=challenge.id,
                kind=kind,
                body=body.strip(),
                actor=actor,
                command_id=command_id,
            )
            session.add(message)
            session.flush()
            self._record_event(
                session,
                challenge=challenge,
                event_type="inbox.message_sent",
                actor=actor,
                command_id=command_id,
                payload={"message_id": message.id, "kind": kind, "sequence": message.sequence},
            )
            return self._message_dict(message)

        return self._execute(command_id, "inbox.send", actor, operation)

    def inbox(
        self, slug: str, *, after: int = 0, pending_only: bool = False
    ) -> list[dict[str, Any]]:
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            statement = select(InboxMessage).where(
                InboxMessage.challenge_id == challenge.id,
                InboxMessage.sequence > after,
            )
            if pending_only:
                statement = statement.where(InboxMessage.status == "PENDING")
            messages = session.scalars(statement.order_by(InboxMessage.sequence)).all()
            return [self._message_dict(item) for item in messages]

    def acknowledge_message(
        self,
        *,
        slug: str,
        message_id: str,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        def operation(session: Session) -> dict[str, Any]:
            challenge = self._challenge(session, slug)
            message = session.scalar(
                select(InboxMessage).where(
                    InboxMessage.challenge_id == challenge.id,
                    InboxMessage.id == message_id,
                )
            )
            if message is None:
                raise NotFoundError(f"Inbox message '{message_id}' does not exist.")
            message.status = "ACKNOWLEDGED"
            message.acknowledged_at = utcnow()
            self._record_event(
                session,
                challenge=challenge,
                event_type="inbox.message_acknowledged",
                actor=actor,
                command_id=command_id,
                payload={"message_id": message.id, "sequence": message.sequence},
            )
            return self._message_dict(message)

        return self._execute(command_id, "inbox.acknowledge", actor, operation)

    def events(self, slug: str, *, after: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            items = session.scalars(
                select(Event)
                .where(Event.challenge_id == challenge.id, Event.sequence > after)
                .order_by(Event.sequence)
                .limit(min(max(limit, 1), 1000))
            ).all()
            return [self._event_dict(item) for item in items]

    def recent_events(self, slug: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return the newest events in chronological order without a stale forward scan."""
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            items = session.scalars(
                select(Event)
                .where(Event.challenge_id == challenge.id)
                .order_by(Event.sequence.desc())
                .limit(min(max(limit, 1), 1000))
            ).all()
            return [self._event_dict(item) for item in reversed(items)]

    def record_runtime_event(
        self,
        *,
        slug: str,
        event_type: str,
        payload: dict[str, Any],
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        if not event_type.startswith("runtime."):
            raise InvariantError(
                "Internal runtime event types must start with 'runtime.'.",
                event_type=event_type,
            )

        def operation(session: Session) -> dict[str, Any]:
            challenge = self._challenge(session, slug)
            event = self._record_event(
                session,
                challenge=challenge,
                event_type=event_type,
                actor=actor,
                command_id=command_id,
                payload=payload,
            )
            session.flush()
            return self._event_dict(event)

        return self._execute(command_id, event_type, actor, operation)

    def _execute(
        self,
        command_id: str,
        command_type: str,
        actor: str,
        operation: Callable[[Session], Result],
    ) -> Result:
        if not command_id.strip():
            raise InvariantError("A command ID is required for idempotency.")
        self._require_text("actor", actor)
        with self.database.session() as session:
            try:
                with session.begin():
                    receipt = session.get(CommandReceipt, command_id)
                    if receipt is not None:
                        if receipt.actor != actor:
                            raise ConflictError(
                                f"Command ID '{command_id}' belongs to another actor.",
                                command_id=command_id,
                            )
                        if receipt.command_type != command_type:
                            raise ConflictError(
                                f"Command ID '{command_id}' was already used "
                                f"for {receipt.command_type}.",
                                command_id=command_id,
                                original_command_type=receipt.command_type,
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
                with self.database.session() as retry_session:
                    receipt = retry_session.get(CommandReceipt, command_id)
                    if (
                        receipt is not None
                        and receipt.command_type == command_type
                        and receipt.actor == actor
                    ):
                        return receipt.result  # type: ignore[return-value]
                raise ConflictError(
                    "The command conflicted with another concurrent write.",
                    command_id=command_id,
                ) from exc

    @staticmethod
    def _require_text(label: str, value: str) -> None:
        if not value or not value.strip():
            raise InvariantError(f"{label.capitalize()} cannot be empty.", field=label)

    @staticmethod
    def _resource_name(value: str) -> str:
        name = value.strip().upper()
        if not ENV_NAME_RE.fullmatch(name):
            raise InvariantError(
                "Resource names must be valid environment variable names.",
                name=value,
                suggestion="Use letters, numbers, and underscores, beginning with a letter.",
            )
        if is_reserved_resource_name(name):
            raise InvariantError(
                f"Resource name '{name}' is reserved by the managed runtime.",
                name=name,
            )
        return name

    @classmethod
    def _resource_value(cls, resource_type: str, value: str) -> str:
        cls._require_text(f"resource {resource_type}", value)
        if len(value.encode()) > RESOURCE_VALUE_LIMIT:
            raise InvariantError(
                f"Resource {resource_type} exceeds the {RESOURCE_VALUE_LIMIT}-byte limit.",
                resource_type=resource_type,
                limit=RESOURCE_VALUE_LIMIT,
            )
        return value

    @staticmethod
    def _challenge(session: Session, slug: str) -> Challenge:
        challenge = session.scalar(select(Challenge).where(Challenge.slug == slug.lower()))
        if challenge is None:
            raise NotFoundError(f"Challenge '{slug}' does not exist.", challenge=slug)
        return challenge

    @staticmethod
    def _artifact(
        session: Session,
        challenge_id: str,
        artifact_id: str,
        *,
        kind: str | None = None,
    ) -> Artifact:
        artifact = session.scalar(
            select(Artifact).where(
                Artifact.challenge_id == challenge_id,
                Artifact.artifact_id == artifact_id.upper(),
            )
        )
        if artifact is None or (kind is not None and artifact.kind != kind):
            raise NotFoundError(
                f"Artifact '{artifact_id}' does not exist.", artifact_id=artifact_id
            )
        return artifact

    @staticmethod
    def _allocate_artifact_id(session: Session, challenge_id: str, kind: str) -> str:
        allocated = session.execute(
            text(
                """
                INSERT INTO id_counters (challenge_id, kind, next_value)
                VALUES (:challenge_id, :kind, 2)
                ON CONFLICT(challenge_id, kind) DO UPDATE SET
                    next_value = id_counters.next_value + 1
                RETURNING next_value - 1
                """
            ),
            {"challenge_id": challenge_id, "kind": kind},
        ).scalar_one()
        return f"{kind}{allocated:03d}"

    @staticmethod
    def _record_revision(
        session: Session,
        artifact: Artifact,
        actor: str,
        command_id: str,
    ) -> None:
        session.add(
            ArtifactRevision(
                artifact_uid=artifact.uid,
                version=artifact.version,
                status=artifact.status,
                title=artifact.title,
                payload=dict(artifact.payload),
                actor=actor,
                command_id=command_id,
            )
        )

    @staticmethod
    def _record_event(
        session: Session,
        *,
        challenge: Challenge,
        event_type: str,
        actor: str,
        command_id: str,
        payload: dict[str, Any],
        artifact_id: str | None = None,
    ) -> Event:
        event = Event(
            challenge_id=challenge.id,
            event_type=event_type,
            actor=actor,
            artifact_id=artifact_id,
            payload=payload,
            command_id=command_id,
        )
        session.add(event)
        return event

    def _cas_artifact(
        self,
        session: Session,
        artifact: Artifact,
        *,
        expected_version: int,
        status: str,
        payload: dict[str, Any],
        actor: str,
        command_id: str,
    ) -> None:
        changed_at = utcnow()
        result = session.execute(
            update(Artifact)
            .where(Artifact.uid == artifact.uid, Artifact.version == expected_version)
            .values(
                status=status,
                payload=payload,
                version=Artifact.version + 1,
                updated_at=changed_at,
            )
        )
        if result.rowcount != 1:
            session.expire(artifact)
            current_version = session.scalar(
                select(Artifact.version).where(Artifact.uid == artifact.uid)
            )
            raise ConflictError(
                f"{artifact.artifact_id} changed from v{expected_version} to v{current_version}.",
                artifact_id=artifact.artifact_id,
                expected_version=expected_version,
                current_version=current_version,
            )
        session.flush()
        session.refresh(artifact)
        self._record_revision(session, artifact, actor, command_id)

    @staticmethod
    def _require_active_lease(
        session: Session,
        challenge_id: str,
        scope: str,
        actor: str,
    ) -> WorkLease:
        lease = session.get(WorkLease, (challenge_id, scope))
        if lease is None:
            raise LeaseConflictError(
                f"{scope} must be claimed before it can run.",
                artifact_id=scope,
            )
        if _aware(lease.expires_at) <= utcnow():
            raise LeaseConflictError(
                f"The lease for {scope} expired at {_iso(lease.expires_at)}.",
                artifact_id=scope,
                expires_at=_iso(lease.expires_at),
            )
        if lease.owner != actor:
            raise LeaseConflictError(
                f"{scope} is claimed by {lease.owner}; current actor is {actor}.",
                artifact_id=scope,
                owner=lease.owner,
                actor=actor,
                expires_at=_iso(lease.expires_at),
            )
        return lease

    @staticmethod
    def _acquire_lease(
        session: Session,
        *,
        challenge_id: str,
        scope: str,
        owner: str,
        ttl_seconds: int,
    ) -> dict[str, Any]:
        now = utcnow()
        expires_at = now + timedelta(seconds=ttl_seconds)
        row = (
            session.execute(
                text(
                    """
                    INSERT INTO work_leases
                        (challenge_id, scope, owner, token, expires_at, version, updated_at)
                    VALUES
                        (:challenge_id, :scope, :owner, :token, :expires_at, 1, :updated_at)
                    ON CONFLICT(challenge_id, scope) DO UPDATE SET
                        owner = excluded.owner,
                        token = excluded.token,
                        expires_at = excluded.expires_at,
                        version = work_leases.version + 1,
                        updated_at = excluded.updated_at
                    WHERE work_leases.expires_at <= :updated_at
                       OR work_leases.owner = :owner
                    RETURNING owner, token, expires_at, version
                    """
                ),
                {
                    "challenge_id": challenge_id,
                    "scope": scope,
                    "owner": owner,
                    "token": str(uuid4()),
                    "expires_at": expires_at,
                    "updated_at": now,
                },
            )
            .mappings()
            .first()
        )
        if row is None:
            existing = session.get(WorkLease, (challenge_id, scope))
            current_owner = existing.owner if existing else "another worker"
            raise LeaseConflictError(
                f"{scope} is already claimed by {current_owner}.",
                scope=scope,
                owner=existing.owner if existing else None,
                expires_at=_iso(existing.expires_at) if existing else None,
            )
        return dict(row)

    @staticmethod
    def _challenge_dict(
        challenge: Challenge,
        coordinator: CoordinatorState | None,
    ) -> dict[str, Any]:
        return {
            "id": challenge.id,
            "slug": challenge.slug,
            "name": challenge.name,
            "objective": challenge.objective,
            "context": challenge.context,
            "success_criteria": challenge.success_criteria,
            "runtime_engine": challenge.runtime_engine,
            "status": challenge.status,
            "version": challenge.version,
            "created_at": _iso(challenge.created_at),
            "updated_at": _iso(challenge.updated_at),
            "coordinator": ChallengeService._coordinator_dict(coordinator) if coordinator else None,
        }

    @staticmethod
    def _coordinator_dict(coordinator: CoordinatorState) -> dict[str, Any]:
        return {
            "status": coordinator.status,
            "current_objective": coordinator.current_objective,
            "next_step": coordinator.next_step,
            "blocker": coordinator.blocker,
            "worker_id": coordinator.worker_id,
            "continuation_id": coordinator.continuation_id,
            "inbox_cursor": coordinator.inbox_cursor,
            "version": coordinator.version,
            "heartbeat_at": _iso(coordinator.heartbeat_at),
            "wake_at": _iso(coordinator.wake_at),
            "updated_at": _iso(coordinator.updated_at),
        }

    @staticmethod
    def _artifact_dict(artifact: Artifact) -> dict[str, Any]:
        return {
            "uid": artifact.uid,
            "id": artifact.artifact_id,
            "kind": artifact.kind,
            "title": artifact.title,
            "status": artifact.status,
            "payload": dict(artifact.payload),
            "hypothesis_id": artifact.parent_hypothesis_id,
            "experiment_id": artifact.parent_experiment_id,
            "version": artifact.version,
            "created_by": artifact.created_by,
            "created_at": _iso(artifact.created_at),
            "updated_at": _iso(artifact.updated_at),
        }

    @staticmethod
    def _observation_dict(observation: Observation) -> dict[str, Any]:
        return {
            "id": observation.id,
            "experiment_id": observation.experiment_id,
            "body": observation.body,
            "evidence_ref": observation.evidence_ref,
            "actor": observation.actor,
            "created_at": _iso(observation.created_at),
        }

    @staticmethod
    def _lease_dict(lease: WorkLease) -> dict[str, Any]:
        return {
            "scope": lease.scope,
            "owner": lease.owner,
            "token": lease.token,
            "expires_at": _iso(lease.expires_at),
            "version": lease.version,
        }

    @staticmethod
    def _message_dict(message: InboxMessage) -> dict[str, Any]:
        return {
            "id": message.id,
            "sequence": message.sequence,
            "kind": message.kind,
            "body": message.body,
            "actor": message.actor,
            "status": message.status,
            "created_at": _iso(message.created_at),
            "acknowledged_at": _iso(message.acknowledged_at),
        }

    @staticmethod
    def _resource_dict(resource: ProjectResource) -> dict[str, Any]:
        return {
            "id": resource.id,
            "name": resource.name,
            "type": resource.resource_type,
            "value": resource.value if resource.resource_type == "VARIABLE" else None,
            "configured": bool(resource.secret_ciphertext)
            if resource.resource_type == "SECRET"
            else None,
            "status": resource.status,
            "created_by": resource.created_by,
            "created_at": _iso(resource.created_at),
            "updated_at": _iso(resource.updated_at),
        }

    @staticmethod
    def _event_dict(item: Event) -> dict[str, Any]:
        return {
            "sequence": item.sequence,
            "id": item.id,
            "type": item.event_type,
            "actor": item.actor,
            "artifact_id": item.artifact_id,
            "payload": dict(item.payload),
            "command_id": item.command_id,
            "created_at": _iso(item.created_at),
        }
