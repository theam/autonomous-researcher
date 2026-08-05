"""Durable collaboration, knowledge-query, and runtime-observability services."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal
from .database import Database
from .errors import AuthorizationError, ConflictError, InvariantError, NotFoundError
from .knowledge_collaboration import KnowledgeCollaborationMixin
from .models import (
    Artifact,
    ArtifactComment,
    ArtifactTag,
    Challenge,
    CoordinatorState,
    Event,
    InboxMessage,
    KnowledgeRelation,
    LiveTicket,
    ProjectMember,
    ProjectSource,
    RuntimeRun,
    SavedKnowledgeView,
    utcnow,
)

ROLE_LEVEL = {"VIEWER": 1, "EDITOR": 2, "OWNER": 3}
SOURCE_TYPES = {"URL", "CONNECTOR", "UPLOAD"}
RELATION_TYPE_LIMIT = 80


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _page_offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        return max(0, int(base64.urlsafe_b64decode(cursor + "===").decode("ascii")))
    except (ValueError, UnicodeDecodeError):
        raise InvariantError("Pagination cursor is invalid.") from None


def _next_cursor(offset: int, count: int, total: int) -> str | None:
    next_offset = offset + count
    if next_offset >= total:
        return None
    return base64.urlsafe_b64encode(str(next_offset).encode("ascii")).decode("ascii").rstrip("=")


class CollaborationService(KnowledgeCollaborationMixin):
    """Owns team access and read/write surfaces around the research core."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def add_creator(self, slug: str, principal: Principal) -> None:
        with self.database.session() as session, session.begin():
            challenge = session.scalar(
                select(Challenge).where(Challenge.slug == slug.lower()).with_for_update()
            )
            if challenge is None:
                raise NotFoundError(f"Project '{slug}' does not exist.", project=slug)
            member_count = session.scalar(
                select(func.count())
                .select_from(ProjectMember)
                .where(ProjectMember.challenge_id == challenge.id)
            )
            if not member_count:
                session.add(
                    ProjectMember(
                        challenge_id=challenge.id,
                        subject=principal.subject,
                        role="OWNER",
                        display_name=principal.display_name,
                        email=principal.email,
                        created_by=principal.subject,
                    )
                )

    def role_for(self, slug: str, principal: Principal) -> str:
        if principal.instance_admin or principal.project_admin:
            return "OWNER"
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            member = session.get(ProjectMember, (challenge.id, principal.subject))
            if member is None:
                raise AuthorizationError(project=slug)
            return member.role

    def require_role(self, slug: str, principal: Principal, minimum: str) -> str:
        role = self.role_for(slug, principal)
        if ROLE_LEVEL[role] < ROLE_LEVEL[minimum]:
            raise AuthorizationError(
                f"Project role {minimum} or higher is required.",
                project=slug,
                required_role=minimum,
                actual_role=role,
            )
        return role

    def visible_project_slugs(self, principal: Principal) -> set[str] | None:
        if principal.instance_admin or principal.project_admin:
            return None
        with self.database.session() as session:
            return set(
                session.scalars(
                    select(Challenge.slug)
                    .join(ProjectMember, ProjectMember.challenge_id == Challenge.id)
                    .where(ProjectMember.subject == principal.subject)
                ).all()
            )

    def list_members(self, slug: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            members = session.scalars(
                select(ProjectMember)
                .where(ProjectMember.challenge_id == challenge.id)
                .order_by(ProjectMember.role.desc(), ProjectMember.display_name)
            ).all()
            return [self._member_dict(item) for item in members]

    def set_member(
        self,
        *,
        slug: str,
        subject: str,
        display_name: str,
        email: str | None,
        role: str,
        actor: str,
    ) -> dict[str, Any]:
        role = role.upper()
        if role not in ROLE_LEVEL:
            raise InvariantError("Project role must be OWNER, EDITOR, or VIEWER.")
        if not subject.strip() or not display_name.strip():
            raise InvariantError("Member subject and display name are required.")
        with self.database.session() as session, session.begin():
            challenge = self._challenge(session, slug, for_update=True)
            member = session.get(ProjectMember, (challenge.id, subject.strip()))
            if member is None:
                member = ProjectMember(
                    challenge_id=challenge.id,
                    subject=subject.strip(),
                    role=role,
                    display_name=display_name.strip(),
                    email=email.strip() if email else None,
                    created_by=actor,
                )
                session.add(member)
            else:
                if member.role == "OWNER" and role != "OWNER":
                    owner_count = session.scalar(
                        select(func.count())
                        .select_from(ProjectMember)
                        .where(
                            ProjectMember.challenge_id == challenge.id,
                            ProjectMember.role == "OWNER",
                        )
                    )
                    if owner_count == 1:
                        raise InvariantError("A project must retain at least one owner.")
                member.role = role
                member.display_name = display_name.strip()
                member.email = email.strip() if email else None
                member.updated_at = utcnow()
            session.flush()
            self._event(
                session,
                challenge,
                "project.member_set",
                actor,
                {"subject": member.subject, "role": member.role},
            )
            return self._member_dict(member)

    def remove_member(self, *, slug: str, subject: str, actor: str) -> dict[str, Any]:
        with self.database.session() as session, session.begin():
            challenge = self._challenge(session, slug, for_update=True)
            member = session.get(ProjectMember, (challenge.id, subject))
            if member is None:
                raise NotFoundError("Project member does not exist.", subject=subject)
            if member.role == "OWNER":
                owner_count = session.scalar(
                    select(func.count())
                    .select_from(ProjectMember)
                    .where(
                        ProjectMember.challenge_id == challenge.id, ProjectMember.role == "OWNER"
                    )
                )
                if owner_count == 1:
                    raise InvariantError("A project must retain at least one owner.")
            result = self._member_dict(member)
            session.delete(member)
            self._event(
                session,
                challenge,
                "project.member_removed",
                actor,
                {"subject": subject},
            )
            return result

    def update_draft(
        self,
        *,
        slug: str,
        name: str | None,
        mission: str | None,
        context: str | None,
        success_criteria: str | None,
        runtime: str | None,
        actor: str,
    ) -> dict[str, Any]:
        from .engines import normalize_runtime_engine

        with self.database.session() as session, session.begin():
            challenge = self._challenge(session, slug)
            coordinator = session.get(CoordinatorState, challenge.id)
            if coordinator is None or coordinator.status != "CREATED":
                raise InvariantError(
                    "Project kickoff fields can only change before the first start."
                )
            if name is not None:
                challenge.name = self._required("name", name)
            if mission is not None:
                challenge.objective = self._required("mission", mission)
                coordinator.current_objective = challenge.objective
            if context is not None:
                challenge.context = context.strip()
            if success_criteria is not None:
                challenge.success_criteria = self._required("success criteria", success_criteria)
            if runtime is not None:
                try:
                    challenge.runtime_engine = normalize_runtime_engine(runtime)
                except ValueError as exc:
                    raise InvariantError(str(exc)) from exc
            challenge.version += 1
            challenge.updated_at = utcnow()
            coordinator.version += 1
            coordinator.updated_at = utcnow()
            self._event(session, challenge, "project.draft_updated", actor, {})
            return self._challenge_dict(challenge, coordinator)

    def preflight(self, slug: str, *, configured_engines: set[str]) -> dict[str, Any]:
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            variables = session.scalar(
                select(func.count())
                .select_from(ProjectSource)
                .where(ProjectSource.challenge_id == challenge.id, ProjectSource.status == "ACTIVE")
            )
            checks = [
                {
                    "name": "mission",
                    "status": "PASS" if challenge.objective.strip() else "FAIL",
                    "detail": "Mission is defined."
                    if challenge.objective.strip()
                    else "Mission is empty.",
                },
                {
                    "name": "success_criteria",
                    "status": "PASS" if challenge.success_criteria.strip() else "FAIL",
                    "detail": "Success criteria are defined."
                    if challenge.success_criteria.strip()
                    else "Success criteria are empty.",
                },
                {
                    "name": "runtime",
                    "status": "PASS" if challenge.runtime_engine in configured_engines else "WARN",
                    "detail": f"{challenge.runtime_engine} is available."
                    if challenge.runtime_engine in configured_engines
                    else f"{challenge.runtime_engine} credentials were not detected at startup.",
                },
                {
                    "name": "sources",
                    "status": "PASS" if variables else "INFO",
                    "detail": f"{variables or 0} source(s) registered.",
                },
            ]
            return {"ready": not any(item["status"] == "FAIL" for item in checks), "checks": checks}

    def issue_live_ticket(
        self, slug: str, principal: Principal, role: str, *, ttl_seconds: int = 60
    ) -> dict[str, Any]:
        ttl_seconds = min(max(ttl_seconds, 15), 120)
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = utcnow() + timedelta(seconds=ttl_seconds)
        with self.database.session() as session, session.begin():
            challenge = self._challenge(session, slug)
            session.add(
                LiveTicket(
                    token_hash=token_hash,
                    challenge_id=challenge.id,
                    subject=principal.subject,
                    display_name=principal.display_name,
                    role=role,
                    instance_admin=principal.instance_admin,
                    expires_at=expires_at,
                )
            )
        return {"ticket": token, "expires_at": _iso(expires_at)}

    def consume_live_ticket(self, slug: str, ticket: str) -> tuple[Principal, str]:
        token_hash = hashlib.sha256(ticket.encode()).hexdigest()
        with self.database.session() as session, session.begin():
            challenge = self._challenge(session, slug)
            item = session.scalar(
                select(LiveTicket)
                .where(
                    LiveTicket.token_hash == token_hash,
                    LiveTicket.challenge_id == challenge.id,
                )
                .with_for_update()
            )
            if item is None or item.used_at is not None or self._aware(item.expires_at) <= utcnow():
                raise AuthorizationError("The live attachment ticket is invalid or expired.")
            item.used_at = utcnow()
            return (
                Principal(
                    subject=item.subject,
                    display_name=item.display_name,
                    instance_admin=item.instance_admin,
                    auth_mode="live-ticket",
                ),
                item.role,
            )

    def guidance(
        self,
        slug: str,
        *,
        status: str | None = None,
        tag: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        offset = _page_offset(cursor)
        limit = min(max(limit, 1), 200)
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            filters = [InboxMessage.challenge_id == challenge.id]
            if status:
                filters.append(InboxMessage.status == status.upper())
            total = (
                session.scalar(select(func.count()).select_from(InboxMessage).where(*filters)) or 0
            )
            rows = session.scalars(
                select(InboxMessage)
                .where(*filters)
                .order_by(InboxMessage.sequence.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            return {
                "items": [self._guidance_dict(item) for item in rows],
                "next_cursor": _next_cursor(offset, len(rows), total),
                "total": total,
            }

    def start_run(
        self,
        slug: str,
        *,
        runtime_engine: str,
        model: str | None,
        retry_count: int = 0,
    ) -> str:
        with self.database.session() as session, session.begin():
            challenge = self._challenge(session, slug)
            run = RuntimeRun(
                challenge_id=challenge.id,
                runtime_engine=runtime_engine,
                model=model,
                retry_count=retry_count,
            )
            session.add(run)
            session.flush()
            return run.id

    def note_run_event(self, run_id: str, *, tool_call: bool = False) -> None:
        if not tool_call:
            return
        with self.database.session() as session, session.begin():
            run = session.get(RuntimeRun, run_id)
            if run is not None:
                run.tool_calls += 1

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        summary: str = "",
        error_code: str | None = None,
        error_message: str | None = None,
        turn_id: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cached_input_tokens: int | None = None,
        reasoning_output_tokens: int | None = None,
        total_tokens: int | None = None,
        cost_microusd: int | None = None,
        usage_source: str | None = None,
        cost_source: str | None = None,
    ) -> None:
        completed_at = utcnow()
        with self.database.session() as session, session.begin():
            run = session.get(RuntimeRun, run_id)
            if run is None:
                return
            run.status = status
            run.summary = summary
            run.error_code = error_code
            run.error_message = error_message
            run.turn_id = turn_id
            run.input_tokens = input_tokens
            run.output_tokens = output_tokens
            run.cached_input_tokens = cached_input_tokens
            run.reasoning_output_tokens = reasoning_output_tokens
            run.total_tokens = total_tokens
            run.cost_microusd = cost_microusd
            run.usage_source = usage_source
            run.cost_source = cost_source
            run.completed_at = completed_at
            run.duration_ms = max(
                0, int((completed_at - self._aware(run.started_at)).total_seconds() * 1000)
            )

    def runs(
        self,
        slug: str,
        *,
        status: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        offset = _page_offset(cursor)
        limit = min(max(limit, 1), 200)
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            filters = [RuntimeRun.challenge_id == challenge.id]
            if status:
                filters.append(RuntimeRun.status == status.upper())
            total = (
                session.scalar(select(func.count()).select_from(RuntimeRun).where(*filters)) or 0
            )
            rows = session.scalars(
                select(RuntimeRun)
                .where(*filters)
                .order_by(RuntimeRun.started_at.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            return {
                "items": [self._run_dict(item) for item in rows],
                "next_cursor": _next_cursor(offset, len(rows), total),
                "total": total,
            }

    def run(self, slug: str, run_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            run = session.scalar(
                select(RuntimeRun).where(
                    RuntimeRun.challenge_id == challenge.id, RuntimeRun.id == run_id
                )
            )
            if run is None:
                raise NotFoundError("Runtime run does not exist.")
            events = session.scalars(
                select(Event)
                .where(
                    Event.challenge_id == challenge.id,
                    Event.payload["run_id"].as_string() == run_id,
                )
                .order_by(Event.sequence)
            ).all()
            return {
                **self._run_dict(run),
                "events": [self._event_dict(item) for item in events],
            }

    def next_retry_count(self, slug: str) -> int:
        """Recover the durable retry ordinal after a server restart."""
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            latest = session.scalar(
                select(RuntimeRun)
                .where(RuntimeRun.challenge_id == challenge.id)
                .order_by(RuntimeRun.started_at.desc())
                .limit(1)
            )
            if latest is None or latest.status != "FAILED":
                return 0
            return latest.retry_count + 1

    def analytics(self, slug: str, *, days: int = 30) -> dict[str, Any]:
        since = utcnow() - timedelta(days=min(max(days, 1), 365))
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            runs = session.scalars(
                select(RuntimeRun).where(
                    RuntimeRun.challenge_id == challenge.id,
                    RuntimeRun.started_at >= since,
                )
            ).all()
            artifacts = session.scalars(
                select(Artifact).where(
                    Artifact.challenge_id == challenge.id,
                    Artifact.created_at >= since,
                )
            ).all()
            guidance = session.scalars(
                select(InboxMessage).where(
                    InboxMessage.challenge_id == challenge.id,
                    InboxMessage.created_at >= since,
                )
            ).all()

        durations = sorted(item.duration_ms for item in runs if item.duration_ms is not None)
        ack_latencies = [
            int((self._aware(item.acknowledged_at) - self._aware(item.created_at)).total_seconds())
            for item in guidance
            if item.acknowledged_at is not None
        ]
        by_day: dict[str, dict[str, int]] = defaultdict(
            lambda: {
                "runs": 0,
                "completed_runs": 0,
                "failed_runs": 0,
                "artifacts": 0,
                "guidance": 0,
            }
        )
        for item in runs:
            bucket = self._aware(item.started_at).date().isoformat()
            by_day[bucket]["runs"] += 1
            if item.status == "COMPLETED":
                by_day[bucket]["completed_runs"] += 1
            elif item.status == "FAILED":
                by_day[bucket]["failed_runs"] += 1
        for item in artifacts:
            by_day[self._aware(item.created_at).date().isoformat()]["artifacts"] += 1
        for item in guidance:
            by_day[self._aware(item.created_at).date().isoformat()]["guidance"] += 1

        return {
            "window": {"days": days, "since": _iso(since)},
            "runs": {
                "total": len(runs),
                "by_status": dict(Counter(item.status for item in runs)),
                "success_rate": round(
                    sum(item.status == "COMPLETED" for item in runs) / len(runs), 4
                )
                if runs
                else None,
                "average_duration_ms": round(sum(durations) / len(durations))
                if durations
                else None,
                "p95_duration_ms": self._percentile(durations, 0.95),
                "input_tokens": self._sum_nullable(item.input_tokens for item in runs),
                "output_tokens": self._sum_nullable(item.output_tokens for item in runs),
                "reasoning_output_tokens": self._sum_nullable(
                    item.reasoning_output_tokens for item in runs
                ),
                "total_tokens": self._sum_nullable(item.total_tokens for item in runs),
                "cost_microusd": self._sum_nullable(item.cost_microusd for item in runs),
                "usage_sources": sorted({item.usage_source for item in runs if item.usage_source}),
                "cost_sources": sorted({item.cost_source for item in runs if item.cost_source}),
                "tool_calls": sum(item.tool_calls for item in runs),
            },
            "knowledge": {
                "created": len(artifacts),
                "by_kind": dict(Counter(item.kind for item in artifacts)),
                "by_status": dict(Counter(item.status for item in artifacts)),
            },
            "guidance": {
                "total": len(guidance),
                "pending": sum(item.status == "PENDING" for item in guidance),
                "average_acknowledgement_seconds": round(sum(ack_latencies) / len(ack_latencies))
                if ack_latencies
                else None,
            },
            "timeseries": [{"date": date, **values} for date, values in sorted(by_day.items())],
        }

    @staticmethod
    def _sum_nullable(values: Any) -> int | None:
        available = [item for item in values if item is not None]
        return sum(available) if available else None

    @staticmethod
    def _percentile(values: list[int], percentile: float) -> int | None:
        if not values:
            return None
        return values[min(len(values) - 1, max(0, int((len(values) - 1) * percentile)))]

    @staticmethod
    def _required(label: str, value: str) -> str:
        result = value.strip()
        if not result:
            raise InvariantError(f"{label.capitalize()} cannot be empty.")
        return result

    @staticmethod
    def _normalize_tag(value: str) -> str:
        tag = value.strip().lower().replace(" ", "-")
        if (
            not tag
            or len(tag) > 80
            or any(not (character.isalnum() or character in "-_.") for character in tag)
        ):
            raise InvariantError(
                "Knowledge tags must use letters, numbers, dots, underscores, or hyphens."
            )
        return tag

    @staticmethod
    def _validate_source_metadata(metadata: dict[str, Any]) -> None:
        if len(json.dumps(metadata, ensure_ascii=False)) > 16_384:
            raise InvariantError("Source metadata must be at most 16384 characters.")
        sensitive = {"secret", "token", "password", "credential", "api_key", "apikey"}

        def inspect(value: Any) -> None:
            if isinstance(value, dict):
                for raw_key, item in value.items():
                    key = str(raw_key).lower()
                    is_reference = key.endswith(("_env", "_secret_name", "_secret_ref"))
                    if any(fragment in key for fragment in sensitive) and not is_reference:
                        raise InvariantError(
                            "Source metadata cannot contain credential values; reference a "
                            "write-only project secret by environment-variable name."
                        )
                    inspect(item)
            elif isinstance(value, list):
                for item in value:
                    inspect(item)

        inspect(metadata)

    @staticmethod
    def _validate_source_uri(uri: str, *, require_http: bool) -> None:
        parsed = urlsplit(uri)
        if require_http and (parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname):
            raise InvariantError("URL sources must use an absolute HTTP or HTTPS URL.")
        if parsed.username or parsed.password:
            raise InvariantError(
                "Source URIs cannot embed credentials; configure a write-only project secret."
            )
        sensitive = {
            "secret",
            "token",
            "password",
            "credential",
            "api_key",
            "apikey",
            "signature",
            "sig",
            "authorization",
            "auth",
        }

        def is_sensitive_query_key(key: str) -> bool:
            normalized = key.lower().replace("-", "_")
            return normalized in sensitive or any(
                normalized.endswith(f"_{fragment}") for fragment in sensitive
            )

        if any(is_sensitive_query_key(key) for key, _value in parse_qsl(parsed.query)):
            raise InvariantError(
                "Source URIs cannot embed credential query parameters; configure a write-only "
                "project secret."
            )

    @staticmethod
    def _tags_by_artifact(
        session: Session, challenge_id: str, artifact_ids: list[str]
    ) -> dict[str, list[str]]:
        if not artifact_ids:
            return {}
        result: dict[str, list[str]] = defaultdict(list)
        for artifact_id, tag in session.execute(
            select(ArtifactTag.artifact_id, ArtifactTag.tag)
            .where(
                ArtifactTag.challenge_id == challenge_id,
                ArtifactTag.artifact_id.in_(artifact_ids),
            )
            .order_by(ArtifactTag.tag)
        ):
            result[artifact_id].append(tag)
        return dict(result)

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _challenge(session: Session, slug: str, *, for_update: bool = False) -> Challenge:
        statement = select(Challenge).where(Challenge.slug == slug.lower())
        if for_update:
            statement = statement.with_for_update()
        challenge = session.scalar(statement)
        if challenge is None:
            raise NotFoundError(f"Project '{slug}' does not exist.", project=slug)
        return challenge

    @staticmethod
    def _artifact(session: Session, challenge_id: str, artifact_id: str) -> Artifact:
        artifact = session.scalar(
            select(Artifact).where(
                Artifact.challenge_id == challenge_id,
                Artifact.artifact_id == artifact_id.upper(),
            )
        )
        if artifact is None:
            raise NotFoundError(f"Knowledge artifact '{artifact_id}' does not exist.")
        return artifact

    @staticmethod
    def _event(
        session: Session,
        challenge: Challenge,
        event_type: str,
        actor: str,
        payload: dict[str, Any],
        *,
        artifact_id: str | None = None,
        command_id: str | None = None,
    ) -> Event:
        event = Event(
            challenge_id=challenge.id,
            event_type=event_type,
            actor=actor,
            artifact_id=artifact_id,
            payload=payload,
            command_id=command_id or secrets.token_hex(16),
        )
        session.add(event)
        return event

    @staticmethod
    def _member_dict(item: ProjectMember) -> dict[str, Any]:
        return {
            "subject": item.subject,
            "display_name": item.display_name,
            "email": item.email,
            "role": item.role,
            "created_at": _iso(item.created_at),
            "updated_at": _iso(item.updated_at),
        }

    @staticmethod
    def _challenge_dict(item: Challenge, coordinator: CoordinatorState) -> dict[str, Any]:
        return {
            "id": item.id,
            "slug": item.slug,
            "name": item.name,
            "objective": item.objective,
            "context": item.context,
            "success_criteria": item.success_criteria,
            "runtime_engine": item.runtime_engine,
            "status": item.status,
            "version": item.version,
            "created_at": _iso(item.created_at),
            "updated_at": _iso(item.updated_at),
            "coordinator": {
                "status": coordinator.status,
                "current_objective": coordinator.current_objective,
                "next_step": coordinator.next_step,
                "blocker": coordinator.blocker,
                "updated_at": _iso(coordinator.updated_at),
            },
        }

    @staticmethod
    def _artifact_dict(item: Artifact, *, tags: list[str] | None = None) -> dict[str, Any]:
        return {
            "id": item.artifact_id,
            "kind": item.kind,
            "title": item.title,
            "status": item.status,
            "content": dict(item.payload),
            "hypothesis_id": item.parent_hypothesis_id,
            "experiment_id": item.parent_experiment_id,
            "created_at": _iso(item.created_at),
            "updated_at": _iso(item.updated_at),
            "tags": tags or [],
        }

    @staticmethod
    def _guidance_dict(item: InboxMessage) -> dict[str, Any]:
        return {
            "id": item.id,
            "sequence": item.sequence,
            "kind": item.kind,
            "body": item.body,
            "actor": item.actor,
            "status": item.status,
            "created_at": _iso(item.created_at),
            "acknowledged_at": _iso(item.acknowledged_at),
        }

    @staticmethod
    def _relation_dict(item: KnowledgeRelation, *, derived: bool) -> dict[str, Any]:
        return {
            "id": item.id,
            "source_id": item.source_artifact_id,
            "target_id": item.target_artifact_id,
            "type": item.relation_type,
            "description": item.description,
            "derived": derived,
            "created_by": item.created_by,
            "created_at": _iso(item.created_at),
        }

    @staticmethod
    def _derived_relation(source_id: str, target_id: str, relation_type: str) -> dict[str, Any]:
        return {
            "id": f"derived:{source_id}:{relation_type}:{target_id}",
            "source_id": source_id,
            "target_id": target_id,
            "type": relation_type,
            "description": "",
            "derived": True,
            "created_by": "Limina",
            "created_at": None,
        }

    @staticmethod
    def _comment_dict(item: ArtifactComment) -> dict[str, Any]:
        return {
            "id": item.id,
            "artifact_id": item.artifact_id,
            "body": item.body,
            "actor": item.actor,
            "created_at": _iso(item.created_at),
        }

    @classmethod
    def _validated_comment_replay(
        cls,
        item: ArtifactComment,
        *,
        challenge_id: str,
        artifact_id: str,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        if (
            item.challenge_id != challenge_id
            or item.artifact_id != artifact_id
            or item.actor != actor
        ):
            raise ConflictError(
                "The idempotency key was already used for another comment.",
                command_id=command_id,
            )
        return cls._comment_dict(item)

    @staticmethod
    def _view_dict(item: SavedKnowledgeView) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "query": dict(item.query),
            "created_by": item.created_by,
            "created_at": _iso(item.created_at),
            "updated_at": _iso(item.updated_at),
        }

    @staticmethod
    def _source_dict(item: ProjectSource) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "type": item.source_type,
            "uri": item.uri,
            "media_type": item.media_type,
            "metadata": dict(item.metadata_json),
            "status": item.status,
            "created_at": _iso(item.created_at),
            "updated_at": _iso(item.updated_at),
        }

    @staticmethod
    def _run_dict(item: RuntimeRun) -> dict[str, Any]:
        return {
            "id": item.id,
            "runtime": item.runtime_engine,
            "model": item.model,
            "status": item.status,
            "summary": item.summary,
            "error": {"code": item.error_code, "message": item.error_message}
            if item.error_code or item.error_message
            else None,
            "usage": {
                "input_tokens": item.input_tokens,
                "output_tokens": item.output_tokens,
                "cached_input_tokens": item.cached_input_tokens,
                "reasoning_output_tokens": item.reasoning_output_tokens,
                "total_tokens": item.total_tokens,
                "cost_microusd": item.cost_microusd,
                "usage_source": item.usage_source,
                "cost_source": item.cost_source,
            },
            "tool_calls": item.tool_calls,
            "retry_count": item.retry_count,
            "started_at": _iso(item.started_at),
            "completed_at": _iso(item.completed_at),
            "duration_ms": item.duration_ms,
        }

    @staticmethod
    def _event_dict(item: Event) -> dict[str, Any]:
        actor = "Limina" if item.actor.startswith("limina:") else item.actor
        return {
            "sequence": item.sequence,
            "type": item.event_type,
            "actor": actor,
            "artifact_id": item.artifact_id,
            "payload": dict(item.payload),
            "created_at": _iso(item.created_at),
        }
