"""Materialized attention episodes and atomic human resolution commands.

The service deliberately accepts explicit challenge IDs.  Authorization remains a
transport concern; this module only guarantees that a caller cannot accidentally
read or mutate outside the scope it has already authorized.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Database
from .errors import (
    AttentionActionNotAllowedError,
    ConflictError,
    InvariantError,
    NotFoundError,
)
from .models import (
    Artifact,
    ArtifactReview,
    ArtifactRevision,
    AttentionDisposition,
    AttentionEpisode,
    AttentionRequest,
    Challenge,
    CommandReceipt,
    CoordinatorState,
    Event,
    InboxMessage,
    RuntimeRun,
    new_uuid,
    utcnow,
)
from .redaction import redact_secret_shapes

SEVERITY_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
REQUEST_KINDS = {"QUESTION", "APPROVAL", "REVIEW", "BLOCKER"}
RESPONSE_ACTIONS: dict[str, tuple[str, ...]] = {
    "TEXT": ("ANSWER",),
    "CHOICE": ("SELECT",),
    "CONFIRMATION": ("CONFIRM", "REJECT"),
    "ARTIFACT_REVIEW": ("REVIEW",),
}
INTERACTION_SURFACES = {"TODAY", "PROJECT_DETAIL", "KNOWLEDGE"}
AUTO_CLEAR_ITEM_TYPES = {
    "agent_request",
    "finding_review",
    "project_complete",
    "stalled_project",
    "preflight_issue",
    "run_failure",
    "unattended_run",
}
MAX_SNOOZE = timedelta(hours=24)


@dataclass(frozen=True)
class _EpisodeSpec:
    challenge_id: str
    item_type: str
    source_key: str
    severity: str
    title: str
    body: str
    source_ref: dict[str, Any]
    allowed_actions: list[str]
    resolution_semantics: str
    attention_request_id: str | None = None


def _now(value: datetime | None = None) -> datetime:
    return _aware(value or utcnow())


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    return _aware(value).astimezone(UTC).isoformat() if value is not None else None


def _required_text(label: str, value: Any) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise InvariantError(f"{label.capitalize()} cannot be empty.", field=label)
    return text


def _severity(value: Any, *, default: str = "MEDIUM") -> str:
    normalized = str(value or default).strip().upper()
    return normalized if normalized in SEVERITY_RANK else default


def _choice_records(raw_choices: Any) -> list[dict[str, str]]:
    if raw_choices is None:
        return []
    if isinstance(raw_choices, (str, bytes)) or not isinstance(raw_choices, Sequence):
        raise InvariantError("Attention request choices must be a list.")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in raw_choices:
        if isinstance(raw, Mapping):
            choice_id = _required_text(
                "choice ID", raw.get("id") or raw.get("value") or raw.get("label")
            )
            label = _required_text(
                "choice label", raw.get("label") or raw.get("value") or choice_id
            )
        else:
            choice_id = _required_text("choice", raw)
            label = choice_id
        if len(choice_id) > 160 or len(label) > 500:
            raise InvariantError("Attention request choices are too long.")
        if choice_id in seen:
            raise InvariantError("Attention request choices must have unique IDs.")
        seen.add(choice_id)
        result.append({"id": choice_id, "label": label})
    return result


def _choice_labels(choices: Sequence[Any]) -> list[str]:
    labels: list[str] = []
    for value in choices:
        if isinstance(value, Mapping):
            labels.append(str(value.get("label") or value.get("value") or value.get("id") or ""))
        else:
            labels.append(str(value))
    return [label for label in labels if label]


def _choice_values(choices: Sequence[Any]) -> set[str]:
    values: set[str] = set()
    for value in choices:
        if isinstance(value, Mapping):
            values.update(
                str(item)
                for item in (value.get("id"), value.get("value"), value.get("label"))
                if item is not None
            )
        else:
            values.add(str(value))
    return values


def _fingerprint(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _child_command_id(command_id: str, suffix: str) -> str:
    digest = hashlib.sha256(f"{command_id}:{suffix}".encode()).hexdigest()
    return f"attention:{digest[:48]}"


def _materialize_episode(
    session: Session,
    spec: _EpisodeSpec,
    *,
    changed_at: datetime,
    existing_episode: AttentionEpisode | None = None,
    lookup_existing: bool = True,
    flush: bool = True,
) -> AttentionEpisode:
    source_match = and_(
        AttentionEpisode.challenge_id == spec.challenge_id,
        AttentionEpisode.item_type == spec.item_type,
        AttentionEpisode.source_key == spec.source_key,
    )
    match = (
        or_(
            source_match,
            AttentionEpisode.attention_request_id == spec.attention_request_id,
        )
        if spec.attention_request_id is not None
        else source_match
    )
    episode = (
        session.scalar(select(AttentionEpisode).where(match))
        if lookup_existing
        else existing_episode
    )
    if episode is None:
        episode = AttentionEpisode(
            challenge_id=spec.challenge_id,
            attention_request_id=spec.attention_request_id,
            item_type=spec.item_type,
            source_key=spec.source_key,
            status="OPEN",
            severity=spec.severity,
            severity_rank=SEVERITY_RANK[spec.severity],
            title=spec.title,
            body=spec.body,
            source_ref=spec.source_ref,
            allowed_actions=spec.allowed_actions,
            resolution_semantics=spec.resolution_semantics,
            opened_at=changed_at,
            updated_at=changed_at,
        )
        session.add(episode)
        if flush:
            session.flush()
        return episode

    values = {
        "attention_request_id": spec.attention_request_id,
        "item_type": spec.item_type,
        "source_key": spec.source_key,
        "severity": spec.severity,
        "severity_rank": SEVERITY_RANK[spec.severity],
        "title": spec.title,
        "body": spec.body,
        "source_ref": spec.source_ref,
        "allowed_actions": spec.allowed_actions,
        "resolution_semantics": spec.resolution_semantics,
    }
    changed = any(getattr(episode, key) != value for key, value in values.items())
    acknowledged_source = episode.resolution_semantics == "project_wide_acknowledge" and bool(
        episode.source_ref.get("acknowledged_at")
    )
    if episode.status != "OPEN" and not acknowledged_source:
        episode.status = "OPEN"
        episode.closed_at = None
        episode.opened_at = changed_at
        changed = True
    elif acknowledged_source:
        # A durable run-failure acknowledgement applies to the whole project.
        # Reconciliation may continue to observe the same failed run until a
        # later run starts; it must not reopen the acknowledged source episode.
        return episode
    if changed:
        for key, value in values.items():
            setattr(episode, key, value)
        episode.updated_at = changed_at
        episode.version += 1
    return episode


def record_checkpoint_request(
    session: Session,
    *,
    challenge: Challenge,
    checkpoint_sequence: int,
    request: dict[str, Any],
    actor: str,
) -> dict[str, str]:
    """Pin and materialize a runtime request inside the checkpoint transaction.

    Replaying the same checkpoint is harmless. Reusing a checkpoint sequence with
    different content is rejected. A later checkpoint is a new source episode even
    when its wording is identical, so an old deep link can never alias a new request.
    """

    if checkpoint_sequence < 0:
        raise InvariantError("Checkpoint sequence cannot be negative.")
    actor = _required_text("actor", actor)
    kind = str(request.get("kind", "")).strip().upper()
    response_mode = str(request.get("response_mode", "")).strip().upper()
    priority = str(request.get("priority", "")).strip().upper()
    if kind not in REQUEST_KINDS:
        raise InvariantError("Attention request kind is not supported.", kind=kind)
    if response_mode not in RESPONSE_ACTIONS:
        raise InvariantError(
            "Attention request response mode is not supported.", response_mode=response_mode
        )
    if priority not in SEVERITY_RANK:
        raise InvariantError("Attention request priority is not supported.", priority=priority)
    title = redact_secret_shapes(_required_text("attention request title", request.get("title")))
    body = redact_secret_shapes(_required_text("attention request body", request.get("body")))
    if len(title) > 300:
        raise InvariantError("Attention request title cannot exceed 300 characters.")
    if len(body) > 32_768:
        raise InvariantError("Attention request body cannot exceed 32768 characters.")
    choices = _choice_records(request.get("choices", []))
    if len(choices) > 12:
        raise InvariantError("Attention requests can include at most 12 choices.")
    if response_mode == "CHOICE" and not choices:
        raise InvariantError("A choice request must include at least one choice.")
    if response_mode != "CHOICE" and choices:
        raise InvariantError("Choices are only valid for CHOICE requests.")

    artifact_id_value = request.get("artifact_id")
    artifact_version_value = request.get("artifact_version")
    if bool(artifact_id_value) != (artifact_version_value is not None):
        raise InvariantError("Artifact ID and version must be provided together.")
    if response_mode == "ARTIFACT_REVIEW" and not artifact_id_value:
        raise InvariantError("An artifact review request must identify an artifact.")

    artifact: Artifact | None = None
    artifact_version: int | None = None
    if artifact_id_value:
        artifact = session.scalar(
            select(Artifact).where(
                Artifact.challenge_id == challenge.id,
                Artifact.artifact_id == str(artifact_id_value).strip().upper(),
            )
        )
        if artifact is None:
            raise NotFoundError("The requested artifact does not exist in this project.")
        artifact_version = (
            int(artifact_version_value) if artifact_version_value is not None else artifact.version
        )
        revision = session.scalar(
            select(ArtifactRevision).where(
                ArtifactRevision.artifact_uid == artifact.uid,
                ArtifactRevision.version == artifact_version,
            )
        )
        if revision is None:
            raise NotFoundError(
                f"Revision v{artifact_version} of '{artifact.artifact_id}' does not exist."
            )

    run_id = request.get("run_id")
    if run_id:
        run = session.scalar(
            select(RuntimeRun).where(
                RuntimeRun.id == str(run_id), RuntimeRun.challenge_id == challenge.id
            )
        )
        if run is None:
            raise NotFoundError("The attention request runtime run does not exist.")

    recommended = request.get("recommended_choice_id")
    if recommended is not None and len(str(recommended)) > 160:
        raise InvariantError("The recommended choice ID is too long.")
    if recommended is not None and str(recommended) not in _choice_values(choices):
        raise InvariantError("The recommended choice is not one of the available choices.")
    normalized = {
        "kind": kind,
        "response_mode": response_mode,
        "priority": priority,
        "title": title,
        "body": body,
        "choices": choices,
        "recommended_choice_id": str(recommended) if recommended is not None else None,
        "artifact_uid": artifact.uid if artifact else None,
        "artifact_version": artifact_version,
        "run_id": str(run_id) if run_id else None,
    }
    content_fingerprint = _fingerprint(normalized)

    existing_checkpoint = session.scalar(
        select(AttentionRequest).where(
            AttentionRequest.challenge_id == challenge.id,
            AttentionRequest.created_checkpoint_sequence == checkpoint_sequence,
        )
    )
    if existing_checkpoint is not None:
        if existing_checkpoint.content_fingerprint != content_fingerprint:
            raise ConflictError(
                "The checkpoint sequence already contains a different attention request.",
                checkpoint_sequence=checkpoint_sequence,
            )
        episode = session.scalar(
            select(AttentionEpisode).where(
                AttentionEpisode.attention_request_id == existing_checkpoint.id
            )
        )
        if episode is None:
            raise ConflictError("The persisted attention request has no materialized episode.")
        return {"request_id": existing_checkpoint.id, "episode_id": episode.id}

    changed_at = utcnow()
    attention_request = AttentionRequest(
        challenge_id=challenge.id,
        kind=kind,
        title=title,
        body=body,
        response_mode=response_mode,
        priority=priority,
        status="OPEN",
        artifact_uid=artifact.uid if artifact else None,
        artifact_version=artifact_version,
        run_id=str(run_id) if run_id else None,
        choices=choices,
        recommended_choice_id=str(recommended) if recommended is not None else None,
        created_checkpoint_sequence=checkpoint_sequence,
        content_fingerprint=content_fingerprint,
        created_at=changed_at,
        updated_at=changed_at,
    )
    session.add(attention_request)
    session.flush()
    episode = _materialize_episode(
        session,
        _EpisodeSpec(
            challenge_id=challenge.id,
            attention_request_id=attention_request.id,
            item_type="agent_request",
            source_key=f"request:{attention_request.id}",
            severity=priority,
            title=title,
            body=body,
            source_ref={
                "request_id": attention_request.id,
                "artifact_id": artifact.artifact_id if artifact else None,
                "artifact_version": artifact_version,
                "run_id": str(run_id) if run_id else None,
            },
            allowed_actions=list(RESPONSE_ACTIONS[response_mode]),
            resolution_semantics="resolve_request",
        ),
        changed_at=changed_at,
    )
    session.add(
        Event(
            challenge_id=challenge.id,
            event_type="attention.requested",
            actor=actor[:200],
            artifact_id=artifact.artifact_id if artifact else None,
            payload={
                "request_id": attention_request.id,
                "episode_id": episode.id,
                "kind": kind,
                "response_mode": response_mode,
                "priority": priority,
                "checkpoint_sequence": checkpoint_sequence,
            },
            command_id=_child_command_id(
                f"{challenge.id}:{checkpoint_sequence}:{content_fingerprint}", "requested"
            ),
            created_at=changed_at,
        )
    )
    session.flush()
    return {"request_id": attention_request.id, "episode_id": episode.id}


def expire_open_requests(
    session: Session,
    *,
    challenge_id: str,
    actor: str,
    reason: str,
    changed_at: datetime | None = None,
) -> int:
    """Expire every unresolved executor request when its lifecycle ends."""

    closed_at = _now(changed_at)
    requests = list(
        session.scalars(
            select(AttentionRequest)
            .where(
                AttentionRequest.challenge_id == challenge_id,
                AttentionRequest.status == "OPEN",
            )
            .with_for_update()
        ).all()
    )
    if not requests:
        return 0
    request_ids = {item.id for item in requests}
    episodes = {
        item.attention_request_id: item
        for item in session.scalars(
            select(AttentionEpisode)
            .where(AttentionEpisode.attention_request_id.in_(request_ids))
            .with_for_update()
        ).all()
    }
    normalized_reason = _required_text("expiration reason", reason)
    for request in requests:
        request.status = "EXPIRED"
        request.resolution = {"action": "EXPIRED", "reason": normalized_reason}
        request.resolved_at = closed_at
        request.resolved_by = actor
        request.updated_at = closed_at
        request.version += 1
        episode = episodes.get(request.id)
        if episode is not None and episode.status == "OPEN":
            episode.status = "CLOSED"
            episode.allowed_actions = []
            episode.closed_at = closed_at
            episode.updated_at = closed_at
            episode.version += 1
        session.add(
            Event(
                challenge_id=challenge_id,
                event_type="attention.request_expired",
                actor=actor[:200],
                artifact_id=None,
                payload={"request_id": request.id, "reason": normalized_reason},
                command_id=_child_command_id(
                    f"{challenge_id}:{request.id}:{normalized_reason}", "expired"
                ),
                created_at=closed_at,
            )
        )
    return len(requests)


def record_notification_failure(
    session: Session,
    *,
    challenge: Challenge,
    source_key: str,
    title: str,
    body: str,
    source_ref: dict[str, Any] | None = None,
    severity: str = "HIGH",
) -> AttentionEpisode:
    """Future notification adapters can materialize a durable, per-user failure."""

    return _materialize_episode(
        session,
        _EpisodeSpec(
            challenge_id=challenge.id,
            item_type="notification_failure",
            source_key=_required_text("notification source key", source_key),
            severity=_severity(severity, default="HIGH"),
            title=_required_text("notification failure title", title),
            body=_required_text("notification failure body", body),
            source_ref=dict(source_ref or {}),
            allowed_actions=["ACKNOWLEDGE"],
            resolution_semantics="per_user_disposition",
        ),
        changed_at=utcnow(),
    )


def clear_notification_failure(
    session: Session,
    *,
    challenge_id: str,
    source_key: str,
    changed_at: datetime | None = None,
) -> bool:
    """Close one exact notification failure episode without aliasing later failures."""

    episode = session.scalar(
        select(AttentionEpisode)
        .where(
            AttentionEpisode.challenge_id == challenge_id,
            AttentionEpisode.item_type == "notification_failure",
            AttentionEpisode.source_key == _required_text("notification source key", source_key),
        )
        .with_for_update()
    )
    if episode is None or episode.status == "CLOSED":
        return False
    closed_at = _now(changed_at)
    episode.status = "CLOSED"
    episode.allowed_actions = []
    episode.closed_at = closed_at
    episode.updated_at = closed_at
    episode.version += 1
    return True


class AttentionService:
    """Reconcile, query, and resolve the Console's durable attention queue."""

    def __init__(
        self,
        database: Database,
        *,
        unattended_after: timedelta = timedelta(hours=2),
        notification_sink: Callable[[Session, Challenge, AttentionEpisode], None] | None = None,
    ) -> None:
        if unattended_after <= timedelta(0):
            raise ValueError("unattended_after must be positive")
        self.database = database
        self.unattended_after = unattended_after
        self.notification_sink = notification_sink

    def reconcile_active(
        self,
        *,
        configured_engines: Collection[str],
        now: datetime | None = None,
    ) -> None:
        """Reconcile every non-archived project without requiring a UI read.

        The runtime calls this from its background worker so failures and other
        derived attention sources can notify operators even while no browser is
        open. Authorization is intentionally absent here: this is an internal
        materialization pass, while reads remain membership-scoped.
        """

        with self.database.session() as session:
            challenge_ids = set(
                session.scalars(select(Challenge.id).where(Challenge.status != "ARCHIVED")).all()
            )
        self.reconcile(
            allowed_challenge_ids=challenge_ids,
            configured_engines=configured_engines,
            now=now,
        )

    def reconcile(
        self,
        *,
        allowed_challenge_ids: Collection[str],
        configured_engines: Collection[str],
        now: datetime | None = None,
    ) -> None:
        challenge_ids = set(allowed_challenge_ids)
        if not challenge_ids:
            return
        changed_at = _now(now)
        configured = {value.strip().lower() for value in configured_engines}
        for attempt in range(2):
            try:
                self._reconcile_once(
                    challenge_ids=challenge_ids,
                    configured_engines=configured,
                    changed_at=changed_at,
                )
                return
            except IntegrityError as exc:
                if attempt:
                    raise ConflictError(
                        "Attention reconciliation conflicted with another write."
                    ) from exc

    def _reconcile_once(
        self,
        *,
        challenge_ids: set[str],
        configured_engines: set[str],
        changed_at: datetime,
    ) -> None:
        with self.database.session() as session, session.begin():
            projects = {
                item.id: item
                for item in session.scalars(
                    select(Challenge).where(Challenge.id.in_(challenge_ids))
                ).all()
            }
            if not projects:
                return
            project_ids = set(projects)
            specs = self._derive_specs(
                session,
                projects=projects,
                configured_engines=configured_engines,
                changed_at=changed_at,
            )
            desired = {(item.challenge_id, item.item_type, item.source_key) for item in specs}
            episodes = list(
                session.scalars(
                    select(AttentionEpisode).where(AttentionEpisode.challenge_id.in_(project_ids))
                ).all()
            )
            by_source = {
                (item.challenge_id, item.item_type, item.source_key): item for item in episodes
            }
            by_request = {
                item.attention_request_id: item
                for item in episodes
                if item.attention_request_id is not None
            }
            for spec in specs:
                existing = (
                    by_request.get(spec.attention_request_id)
                    if spec.attention_request_id is not None
                    else None
                )
                existing = existing or by_source.get(
                    (spec.challenge_id, spec.item_type, spec.source_key)
                )
                materialized = _materialize_episode(
                    session,
                    spec,
                    changed_at=changed_at,
                    existing_episode=existing,
                    lookup_existing=False,
                    flush=False,
                )
                if existing is None:
                    episodes.append(materialized)
                    # SQLAlchemy assigns the episode UUID during flush.  Notification
                    # outbox rows use it as both their foreign key and dedupe key, so
                    # make the durable identity available before invoking the sink.
                    session.flush()
                if self.notification_sink is not None:
                    self.notification_sink(session, projects[spec.challenge_id], materialized)
            session.flush()

            open_auto_clear = [
                item
                for item in episodes
                if item.status == "OPEN" and item.item_type in AUTO_CLEAR_ITEM_TYPES
            ]
            for episode in open_auto_clear:
                key = (episode.challenge_id, episode.item_type, episode.source_key)
                if key not in desired:
                    episode.status = "CLOSED"
                    episode.closed_at = changed_at
                    episode.updated_at = changed_at
                    episode.version += 1

    def list_items(
        self,
        *,
        allowed_challenge_ids: Collection[str],
        subject: str,
        cursor: str | None = None,
        limit: int = 50,
        include_closed: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if limit < 1 or limit > 100:
            raise InvariantError("Attention page size must be between 1 and 100.")
        challenge_ids = set(allowed_challenge_ids)
        synced_at = _now(now)
        if not challenge_ids:
            return {"items": [], "next_cursor": None, "last_synced_at": synced_at.isoformat()}
        scope_key = self._scope_key(subject)
        status_rank = case((AttentionEpisode.status == "OPEN", 0), else_=1)
        hidden = exists().where(
            AttentionDisposition.episode_id == AttentionEpisode.id,
            AttentionDisposition.scope_key == scope_key,
            or_(
                AttentionDisposition.action == "ACKNOWLEDGED",
                and_(
                    AttentionDisposition.action == "SNOOZE",
                    AttentionDisposition.snoozed_until.is_not(None),
                    AttentionDisposition.snoozed_until > synced_at,
                ),
            ),
        )
        statement = (
            select(AttentionEpisode, Challenge)
            .join(Challenge, Challenge.id == AttentionEpisode.challenge_id)
            .where(AttentionEpisode.challenge_id.in_(challenge_ids), ~hidden)
        )
        if not include_closed:
            statement = statement.where(AttentionEpisode.status == "OPEN")
        if cursor:
            after_status, after_severity, after_opened, after_id = self._decode_cursor(cursor)
            statement = statement.where(
                or_(
                    status_rank > after_status,
                    and_(
                        status_rank == after_status,
                        AttentionEpisode.severity_rank > after_severity,
                    ),
                    and_(
                        status_rank == after_status,
                        AttentionEpisode.severity_rank == after_severity,
                        AttentionEpisode.opened_at > after_opened,
                    ),
                    and_(
                        status_rank == after_status,
                        AttentionEpisode.severity_rank == after_severity,
                        AttentionEpisode.opened_at == after_opened,
                        AttentionEpisode.id > after_id,
                    ),
                )
            )
        statement = statement.order_by(
            status_rank,
            AttentionEpisode.severity_rank,
            AttentionEpisode.opened_at,
            AttentionEpisode.id,
        ).limit(limit + 1)
        with self.database.session() as session:
            rows = list(session.execute(statement).all())
            has_more = len(rows) > limit
            visible = rows[:limit]
            request_ids = {
                episode.attention_request_id
                for episode, _challenge in visible
                if episode.attention_request_id is not None
            }
            requests = {
                item.id: item
                for item in session.scalars(
                    select(AttentionRequest).where(AttentionRequest.id.in_(request_ids))
                ).all()
            }
            items = [
                self._public_item(
                    session,
                    episode,
                    challenge,
                    attention_request=requests.get(episode.attention_request_id),
                )
                for episode, challenge in visible
            ]
            next_cursor = None
            if has_more and visible:
                episode = visible[-1][0]
                next_cursor = self._encode_cursor(episode)
            return {
                "items": items,
                "next_cursor": next_cursor,
                "last_synced_at": synced_at.isoformat(),
            }

    def get_item(
        self,
        episode_id: str,
        *,
        allowed_challenge_ids: Collection[str],
    ) -> dict[str, Any]:
        challenge_ids = set(allowed_challenge_ids)
        with self.database.session() as session:
            row = session.execute(
                select(AttentionEpisode, Challenge)
                .join(Challenge, Challenge.id == AttentionEpisode.challenge_id)
                .where(
                    AttentionEpisode.id == episode_id,
                    AttentionEpisode.challenge_id.in_(challenge_ids),
                )
            ).one_or_none()
            if row is None:
                raise NotFoundError("Attention item does not exist.")
            return self._public_item(session, row[0], row[1])

    def resolve(
        self,
        episode_id: str,
        *,
        allowed_challenge_ids: Collection[str],
        action: str,
        expected_version: int,
        actor_subject: str,
        actor_name: str,
        command_id: str,
        response: str | None = None,
        choice: str | None = None,
        snooze_until: datetime | None = None,
        interaction_surface: str = "TODAY",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        challenge_ids = set(allowed_challenge_ids)
        action = action.strip().upper()
        actor_subject = _required_text("actor subject", actor_subject)
        actor_name = _required_text("actor name", actor_name)[:240]
        command_id = _required_text("command ID", command_id)
        if len(command_id) > 64:
            raise InvariantError("Command ID cannot exceed 64 characters.")
        interaction_surface = interaction_surface.strip().upper()
        if interaction_surface not in INTERACTION_SURFACES:
            raise InvariantError("The attention interaction surface is not supported.")
        changed_at = _now(now)

        with self.database.session() as session:
            try:
                with session.begin():
                    receipt = session.get(CommandReceipt, command_id)
                    if receipt is not None:
                        if (
                            receipt.command_type != "attention.resolve"
                            or receipt.actor != actor_subject
                        ):
                            raise ConflictError("The idempotency key was already used.")
                        return receipt.result

                    row = session.execute(
                        select(AttentionEpisode, Challenge)
                        .join(Challenge, Challenge.id == AttentionEpisode.challenge_id)
                        .where(
                            AttentionEpisode.id == episode_id,
                            AttentionEpisode.challenge_id.in_(challenge_ids),
                        )
                        .with_for_update()
                    ).one_or_none()
                    if row is None:
                        raise NotFoundError("Attention item does not exist.")
                    episode, challenge = row
                    if episode.version != expected_version:
                        raise ConflictError(
                            "Attention item changed from "
                            f"v{expected_version} to v{episode.version}.",
                            expected_version=expected_version,
                            current_version=episode.version,
                        )
                    if episode.status != "OPEN":
                        raise ConflictError("Attention item is already closed.")
                    if action not in episode.allowed_actions:
                        raise AttentionActionNotAllowedError(
                            action=action,
                            allowed_actions=list(episode.allowed_actions),
                        )

                    guidance: InboxMessage | None = None
                    if (
                        action == "ACKNOWLEDGE"
                        and episode.resolution_semantics == "project_wide_acknowledge"
                    ):
                        self._acknowledge_project_episode(
                            episode,
                            actor_subject=actor_subject,
                            actor_name=actor_name,
                            changed_at=changed_at,
                        )
                        event_type = "attention.acknowledged"
                    elif action in {"ACKNOWLEDGE", "SNOOZE"}:
                        self._record_disposition(
                            session,
                            episode=episode,
                            action=action,
                            actor_subject=actor_subject,
                            actor_name=actor_name,
                            command_id=command_id,
                            snooze_until=snooze_until,
                            interaction_surface=interaction_surface,
                            changed_at=changed_at,
                        )
                        event_type = "attention.disposition_recorded"
                    else:
                        guidance = self._resolve_request(
                            session,
                            episode=episode,
                            action=action,
                            response=response,
                            choice=choice,
                            actor_subject=actor_subject,
                            actor_name=actor_name,
                            command_id=command_id,
                            changed_at=changed_at,
                        )
                        event_type = "attention.request_resolved"

                    session.flush()
                    session.add(
                        Event(
                            challenge_id=challenge.id,
                            event_type=event_type,
                            actor=actor_name[:200],
                            artifact_id=episode.source_ref.get("artifact_id"),
                            payload={
                                "episode_id": episode.id,
                                "request_id": episode.attention_request_id,
                                "action": action,
                                "guidance_id": guidance.id if guidance else None,
                                "interaction_surface": interaction_surface,
                            },
                            command_id=command_id,
                            created_at=changed_at,
                        )
                    )
                    result = {
                        "item": self._public_item(session, episode, challenge),
                        "guidance_id": guidance.id if guidance else None,
                        "guidance_body": guidance.body if guidance else None,
                        "delivery": "QUEUED" if guidance else None,
                    }
                    session.add(
                        CommandReceipt(
                            command_id=command_id,
                            command_type="attention.resolve",
                            actor=actor_subject,
                            result=result,
                            created_at=changed_at,
                        )
                    )
                return result
            except IntegrityError as exc:
                session.rollback()
                with self.database.session() as retry:
                    receipt = retry.get(CommandReceipt, command_id)
                    if (
                        receipt is not None
                        and receipt.command_type == "attention.resolve"
                        and receipt.actor == actor_subject
                    ):
                        return receipt.result
                raise ConflictError("The attention action conflicted with another write.") from exc

    def _derive_specs(
        self,
        session: Session,
        *,
        projects: dict[str, Challenge],
        configured_engines: set[str],
        changed_at: datetime,
    ) -> list[_EpisodeSpec]:
        project_ids = set(projects)
        specs: list[_EpisodeSpec] = []
        requests = session.scalars(
            select(AttentionRequest).where(
                AttentionRequest.challenge_id.in_(project_ids),
                AttentionRequest.status == "OPEN",
            )
        ).all()
        request_projects = {item.challenge_id for item in requests}
        artifact_uids = {item.artifact_uid for item in requests if item.artifact_uid}
        request_artifacts = {
            item.uid: item
            for item in session.scalars(
                select(Artifact).where(Artifact.uid.in_(artifact_uids))
            ).all()
        }
        for item in requests:
            artifact_id = None
            if item.artifact_uid:
                artifact = request_artifacts.get(item.artifact_uid)
                artifact_id = artifact.artifact_id if artifact else None
            specs.append(
                _EpisodeSpec(
                    challenge_id=item.challenge_id,
                    attention_request_id=item.id,
                    item_type="agent_request",
                    source_key=f"request:{item.id}",
                    severity=_severity(item.priority),
                    title=item.title,
                    body=item.body,
                    source_ref={
                        "request_id": item.id,
                        "artifact_id": artifact_id,
                        "artifact_version": item.artifact_version,
                        "run_id": item.run_id,
                    },
                    allowed_actions=list(RESPONSE_ACTIONS[item.response_mode]),
                    resolution_semantics="resolve_request",
                )
            )

        latest_runs: dict[str, RuntimeRun] = {}
        for run in session.scalars(
            select(RuntimeRun)
            .where(RuntimeRun.challenge_id.in_(project_ids))
            .order_by(
                RuntimeRun.challenge_id,
                RuntimeRun.started_at.desc(),
                RuntimeRun.id.desc(),
            )
        ).all():
            latest_runs.setdefault(run.challenge_id, run)
        failed_runs = [run for run in latest_runs.values() if run.status == "FAILED"]
        failed_projects = {run.challenge_id for run in failed_runs}
        for run in failed_runs:
            detail = (
                run.error_message or run.summary or "The runtime stopped unexpectedly."
            ).strip()
            specs.append(
                _EpisodeSpec(
                    challenge_id=run.challenge_id,
                    item_type="run_failure",
                    source_key=f"run:{run.id}",
                    severity="HIGH",
                    title="Runtime run failed",
                    body=detail,
                    source_ref={"run_id": run.id},
                    allowed_actions=["ACKNOWLEDGE"],
                    resolution_semantics="project_wide_acknowledge",
                )
            )

        unreviewed_findings = session.scalars(
            select(Artifact).where(
                Artifact.challenge_id.in_(project_ids),
                Artifact.kind == "F",
                ~exists().where(
                    ArtifactReview.artifact_uid == Artifact.uid,
                    ArtifactReview.artifact_version == Artifact.version,
                ),
            )
        ).all()
        for artifact in unreviewed_findings:
            impact = _severity(
                artifact.payload.get("severity") or artifact.payload.get("impact"),
                default="MEDIUM",
            )
            summary = str(
                artifact.payload.get("summary")
                or artifact.payload.get("finding")
                or "This current finding revision has not been reviewed."
            ).strip()
            specs.append(
                _EpisodeSpec(
                    challenge_id=artifact.challenge_id,
                    item_type="finding_review",
                    source_key=f"artifact:{artifact.uid}:v{artifact.version}",
                    severity=impact,
                    title=f"Review {artifact.artifact_id}: {artifact.title}",
                    body=summary,
                    source_ref={
                        "artifact_id": artifact.artifact_id,
                        "artifact_version": artifact.version,
                    },
                    allowed_actions=["REVIEW"],
                    resolution_semantics="artifact_review",
                )
            )

        coordinators = session.scalars(
            select(CoordinatorState).where(CoordinatorState.challenge_id.in_(project_ids))
        ).all()
        running_runs: dict[str, RuntimeRun] = {}
        for run in session.scalars(
            select(RuntimeRun)
            .where(RuntimeRun.challenge_id.in_(project_ids), RuntimeRun.status == "RUNNING")
            .order_by(RuntimeRun.started_at.desc())
        ).all():
            running_runs.setdefault(run.challenge_id, run)

        unattended_cutoff = _aware(changed_at) - self.unattended_after
        for coordinator in coordinators:
            project = projects[coordinator.challenge_id]
            if project.status == "ARCHIVED":
                continue
            if coordinator.status == "COMPLETE":
                specs.append(
                    _EpisodeSpec(
                        challenge_id=project.id,
                        item_type="project_complete",
                        source_key=f"coordinator:v{coordinator.version}",
                        severity="LOW",
                        title="Research project complete",
                        body=coordinator.current_objective
                        or "The coordinator marked this project complete.",
                        source_ref={},
                        allowed_actions=["ACKNOWLEDGE"],
                        resolution_semantics="per_user_disposition",
                    )
                )
            if (
                coordinator.status == "WAITING"
                and project.id not in request_projects
                and project.id not in failed_projects
            ):
                specs.append(
                    _EpisodeSpec(
                        challenge_id=project.id,
                        item_type="stalled_project",
                        source_key=f"coordinator:v{coordinator.version}",
                        severity="HIGH",
                        title="Project is waiting without a request",
                        body=coordinator.blocker or coordinator.next_step,
                        source_ref={},
                        allowed_actions=["SNOOZE"],
                        resolution_semantics="per_user_disposition",
                    )
                )
            if (
                coordinator.status == "CREATED"
                and project.runtime_engine.strip().lower() not in configured_engines
            ):
                specs.append(
                    _EpisodeSpec(
                        challenge_id=project.id,
                        item_type="preflight_issue",
                        source_key=f"engine:{project.runtime_engine}:project-v{project.version}",
                        severity="HIGH",
                        title="Runtime engine is unavailable",
                        body=f"Configure {project.runtime_engine} before starting this project.",
                        source_ref={},
                        allowed_actions=[],
                        resolution_semantics="auto_clear",
                    )
                )
            last_activity = max(
                _aware(coordinator.updated_at),
                _aware(coordinator.heartbeat_at)
                if coordinator.heartbeat_at
                else _aware(coordinator.updated_at),
            )
            if coordinator.status == "RUNNING" and last_activity <= unattended_cutoff:
                run = running_runs.get(project.id)
                specs.append(
                    _EpisodeSpec(
                        challenge_id=project.id,
                        item_type="unattended_run",
                        source_key=f"coordinator:v{coordinator.version}",
                        severity="MEDIUM",
                        title="Running project has gone quiet",
                        body=(
                            "No coordinator activity has been recorded for "
                            f"{self.unattended_after}."
                        ),
                        source_ref={"run_id": run.id if run else None},
                        allowed_actions=["SNOOZE"],
                        resolution_semantics="per_user_disposition",
                    )
                )
        return specs

    @staticmethod
    def _acknowledge_project_episode(
        episode: AttentionEpisode,
        *,
        actor_subject: str,
        actor_name: str,
        changed_at: datetime,
    ) -> None:
        """Close a source for every project member until its source changes."""

        episode.status = "CLOSED"
        episode.closed_at = changed_at
        episode.updated_at = changed_at
        episode.allowed_actions = []
        episode.source_ref = {
            **episode.source_ref,
            "acknowledged_at": _iso(changed_at),
            "acknowledged_by": actor_subject,
            "acknowledged_by_name": actor_name,
        }
        episode.version += 1

    @staticmethod
    def _record_disposition(
        session: Session,
        *,
        episode: AttentionEpisode,
        action: str,
        actor_subject: str,
        actor_name: str,
        command_id: str,
        snooze_until: datetime | None,
        interaction_surface: str,
        changed_at: datetime,
    ) -> None:
        if action == "SNOOZE":
            if snooze_until is None:
                raise InvariantError("Snooze requires an end time.")
            if _aware(snooze_until) <= _aware(changed_at):
                raise InvariantError("Snooze end time must be in the future.")
            if _aware(snooze_until) > _aware(changed_at) + MAX_SNOOZE:
                raise InvariantError("Attention items can be snoozed for at most 24 hours.")
        elif snooze_until is not None:
            raise InvariantError("Snooze end time is only valid for SNOOZE.")

        scope_key = AttentionService._scope_key(actor_subject)
        disposition = session.scalar(
            select(AttentionDisposition)
            .where(
                AttentionDisposition.episode_id == episode.id,
                AttentionDisposition.scope_key == scope_key,
            )
            .with_for_update()
        )
        stored_action = "ACKNOWLEDGED" if action == "ACKNOWLEDGE" else action
        if disposition is None:
            session.add(
                AttentionDisposition(
                    episode_id=episode.id,
                    scope_key=scope_key,
                    action=stored_action,
                    actor_subject=actor_subject,
                    actor_name=actor_name,
                    details={},
                    snoozed_until=snooze_until,
                    interaction_surface=interaction_surface,
                    command_id=command_id,
                    created_at=changed_at,
                    updated_at=changed_at,
                )
            )
        else:
            disposition.action = stored_action
            disposition.actor_subject = actor_subject
            disposition.actor_name = actor_name
            disposition.details = {}
            disposition.snoozed_until = snooze_until
            disposition.interaction_surface = interaction_surface
            disposition.command_id = command_id
            disposition.updated_at = changed_at
            disposition.version += 1

    @staticmethod
    def _resolve_request(
        session: Session,
        *,
        episode: AttentionEpisode,
        action: str,
        response: str | None,
        choice: str | None,
        actor_subject: str,
        actor_name: str,
        command_id: str,
        changed_at: datetime,
    ) -> InboxMessage:
        if episode.item_type != "agent_request" or not episode.attention_request_id:
            raise InvariantError("Only agent requests accept this resolution action.")
        request = session.scalar(
            select(AttentionRequest)
            .where(AttentionRequest.id == episode.attention_request_id)
            .with_for_update()
        )
        if request is None or request.status != "OPEN":
            raise ConflictError("The underlying attention request is no longer open.")
        expected_actions = RESPONSE_ACTIONS.get(request.response_mode, ())
        if action not in expected_actions:
            expected_label = " or ".join(expected_actions) or "a supported action"
            raise InvariantError(
                f"{request.response_mode} requests require {expected_label}.", action=action
            )

        response_text = response.strip() if response else ""
        choice_text = choice.strip() if choice else ""
        if len(response_text) > 32_768:
            raise InvariantError("Attention responses cannot exceed 32768 characters.")
        if len(choice_text) > 500:
            raise InvariantError("Attention choices cannot exceed 500 characters.")
        if action == "SELECT":
            if not choice_text or choice_text not in _choice_values(request.choices):
                raise InvariantError("Select one of the request's available choices.")
            if response_text:
                raise InvariantError("A choice response must use the choice field.")
            guidance_body = choice_text
            resolution: dict[str, Any] = {"action": action, "choice": choice_text}
        else:
            if not response_text:
                raise InvariantError(f"{action.title()} requires a response.")
            if choice_text:
                raise InvariantError("The choice field is only valid for SELECT.")
            guidance_body = response_text
            resolution = {"action": action, "response": response_text}

        request.status = "RESOLVED"
        request.resolution = resolution
        request.resolved_at = changed_at
        request.resolved_by = actor_subject
        request.updated_at = changed_at
        request.version += 1
        episode.status = "CLOSED"
        episode.closed_at = changed_at
        episode.updated_at = changed_at
        episode.version += 1
        kind = {
            "ANSWER": "ANSWER",
            "SELECT": "ANSWER",
            "CONFIRM": "APPROVAL",
            "REJECT": "BLOCKER",
            "REVIEW": "COMMENT",
        }[action]
        guidance = InboxMessage(
            id=new_uuid(),
            challenge_id=episode.challenge_id,
            kind=kind,
            body=guidance_body,
            actor=actor_name[:200],
            status="PENDING",
            command_id=_child_command_id(command_id, "guidance"),
            created_at=changed_at,
        )
        session.add(guidance)
        session.flush()
        return guidance

    @staticmethod
    def _scope_key(subject: str) -> str:
        return f"user:{_required_text('subject', subject)}"

    @staticmethod
    def _public_item(
        session: Session,
        episode: AttentionEpisode,
        challenge: Challenge,
        *,
        attention_request: AttentionRequest | None = None,
    ) -> dict[str, Any]:
        source = {
            "request_id": episode.source_ref.get("request_id"),
            "artifact_id": episode.source_ref.get("artifact_id"),
            "artifact_version": episode.source_ref.get("artifact_version"),
            "run_id": episode.source_ref.get("run_id"),
            "event_sequence": episode.source_ref.get("event_sequence"),
        }
        result: dict[str, Any] = {
            "id": episode.id,
            "kind": episode.item_type,
            "project": {"slug": challenge.slug, "name": challenge.name},
            "severity": episode.severity,
            "title": episode.title,
            "summary": episode.body,
            "status": episode.status,
            "source": source,
            "allowed_actions": list(episode.allowed_actions),
            "version": episode.version,
            "opened_at": _iso(episode.opened_at),
            "updated_at": _iso(episode.updated_at),
            "request": None,
        }
        if episode.item_type == "agent_request":
            request = attention_request or session.get(
                AttentionRequest, episode.attention_request_id
            )
            if request is None:
                raise ConflictError("The attention episode's request no longer exists.")
            result["request"] = {
                "kind": request.kind,
                "response_mode": request.response_mode,
                "choices": _choice_labels(request.choices),
            }
        return result

    @staticmethod
    def _encode_cursor(episode: AttentionEpisode) -> str:
        payload = [
            0 if episode.status == "OPEN" else 1,
            episode.severity_rank,
            episode.opened_at.isoformat(),
            episode.id,
        ]
        return (
            base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
            .decode()
            .rstrip("=")
        )

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[int, int, datetime, str]:
        try:
            padding = "=" * (-len(cursor) % 4)
            value = json.loads(base64.urlsafe_b64decode(cursor + padding))
            if not isinstance(value, list) or len(value) != 4:
                raise ValueError
            status_rank = int(value[0])
            severity_rank = int(value[1])
            opened_at = datetime.fromisoformat(str(value[2]))
            episode_id = str(value[3])
            if status_rank not in {0, 1} or severity_rank not in SEVERITY_RANK.values():
                raise ValueError
            return status_rank, severity_rank, opened_at, episode_id
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise InvariantError("The attention cursor is invalid.") from exc
