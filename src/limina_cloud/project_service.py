"""Project kickoff, lifecycle, and resource commands."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .attention_service import expire_open_requests
from .engines import normalize_runtime_engine
from .errors import ConflictError, InvariantError, NotFoundError
from .models import Challenge, CoordinatorState, ProjectMember, ProjectResource, utcnow

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
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


class ProjectServiceMixin:
    def create_challenge(
        self,
        *,
        slug: str,
        name: str,
        objective: str,
        success_criteria: str,
        context: str,
        runtime_engine: str = "codex",
        actor: str,
        command_id: str,
        owner_subject: str | None = None,
        owner_display_name: str | None = None,
        owner_email: str | None = None,
    ) -> dict[str, Any]:
        slug = slug.strip().lower()
        if not SLUG_RE.fullmatch(slug):
            raise InvariantError(
                "Challenge slug must contain lowercase letters, numbers, and single hyphens.",
                slug=slug,
            )
        self._require_text("name", name)
        self._require_text("objective", objective)
        self._require_text("success criteria", success_criteria)
        try:
            runtime_engine = normalize_runtime_engine(runtime_engine)
        except ValueError as exc:
            raise InvariantError(str(exc), runtime_engine=runtime_engine) from exc

        def operation(session: Session) -> dict[str, Any]:
            if session.scalar(select(Challenge).where(Challenge.slug == slug)) is not None:
                raise ConflictError(f"Challenge '{slug}' already exists.", challenge=slug)
            challenge = Challenge(
                slug=slug,
                name=name.strip(),
                objective=objective.strip(),
                context=context.strip(),
                success_criteria=success_criteria.strip(),
                runtime_engine=runtime_engine,
            )
            session.add(challenge)
            session.flush()
            coordinator = CoordinatorState(
                challenge_id=challenge.id,
                status="CREATED",
                current_objective=challenge.objective,
                next_step="Frame the first falsifiable hypothesis.",
                blocker="None",
            )
            session.add(coordinator)
            if owner_subject is not None:
                session.add(
                    ProjectMember(
                        challenge_id=challenge.id,
                        subject=owner_subject,
                        role="OWNER",
                        display_name=owner_display_name or owner_subject,
                        email=owner_email,
                        created_by=owner_subject,
                    )
                )
            self._record_event(
                session,
                challenge=challenge,
                event_type="challenge.created",
                actor=actor,
                command_id=command_id,
                payload={
                    "slug": slug,
                    "name": challenge.name,
                    "runtime_engine": runtime_engine,
                },
            )
            session.flush()
            return self._challenge_dict(challenge, coordinator)

        return self._execute(command_id, "challenge.create", actor, operation)

    def list_projects(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        with self.database.session() as session:
            statement = select(Challenge).order_by(Challenge.created_at, Challenge.slug)
            if not include_archived:
                statement = statement.where(Challenge.status != "ARCHIVED")
            projects = session.scalars(statement).all()
            coordinator_by_id = {
                item.challenge_id: item for item in session.scalars(select(CoordinatorState)).all()
            }
            return [
                self._challenge_dict(project, coordinator_by_id.get(project.id))
                for project in projects
            ]

    def update_project_draft(
        self,
        *,
        slug: str,
        name: str | None,
        objective: str | None,
        context: str | None,
        success_criteria: str | None,
        runtime_engine: str | None,
        expected_version: int,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        """Update mutable kickoff fields with revision and retry protection."""

        if expected_version < 1:
            raise InvariantError("Expected project version must be positive.")
        if name is not None:
            self._require_text("name", name)
        if objective is not None:
            self._require_text("objective", objective)
        if success_criteria is not None:
            self._require_text("success criteria", success_criteria)
        if runtime_engine is not None:
            try:
                runtime_engine = normalize_runtime_engine(runtime_engine)
            except ValueError as exc:
                raise InvariantError(str(exc), runtime_engine=runtime_engine) from exc

        def operation(session: Session) -> dict[str, Any]:
            challenge = session.scalar(
                select(Challenge).where(Challenge.slug == slug.lower()).with_for_update()
            )
            if challenge is None:
                raise NotFoundError(f"Project '{slug}' does not exist.")
            coordinator = session.get(CoordinatorState, challenge.id)
            if coordinator is None or coordinator.status != "CREATED":
                raise InvariantError(
                    "Project kickoff fields can only change before the first start."
                )
            if challenge.version != expected_version:
                raise ConflictError(
                    "The project draft changed. Refresh before saving again.",
                    expected_version=expected_version,
                    current_version=challenge.version,
                )
            changed_fields = [
                field
                for field, value in {
                    "name": name,
                    "objective": objective,
                    "context": context,
                    "success_criteria": success_criteria,
                    "runtime": runtime_engine,
                }.items()
                if value is not None
            ]
            if not changed_fields:
                return self._challenge_dict(challenge, coordinator)
            if name is not None:
                challenge.name = name.strip()
            if objective is not None:
                challenge.objective = objective.strip()
                coordinator.current_objective = challenge.objective
            if context is not None:
                challenge.context = context.strip()
            if success_criteria is not None:
                challenge.success_criteria = success_criteria.strip()
            if runtime_engine is not None:
                challenge.runtime_engine = runtime_engine
            changed_at = utcnow()
            challenge.version += 1
            challenge.updated_at = changed_at
            coordinator.version += 1
            coordinator.updated_at = changed_at
            self._record_event(
                session,
                challenge=challenge,
                event_type="project.draft_updated",
                actor=actor,
                command_id=command_id,
                payload={"fields": sorted(changed_fields)},
            )
            session.flush()
            return self._challenge_dict(challenge, coordinator)

        return self._execute(command_id, "project.draft.update", actor, operation)

    def change_project_state(
        self,
        *,
        slug: str,
        action: str,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        action = action.lower()
        if action not in {*PROJECT_TRANSITIONS, "archive"}:
            raise InvariantError(
                "Project action must be start, pause, resume, stop, or archive.",
                action=action,
            )

        def operation(session: Session) -> dict[str, Any]:
            challenge = self._challenge(session, slug)
            coordinator = session.scalar(
                select(CoordinatorState)
                .where(CoordinatorState.challenge_id == challenge.id)
                .with_for_update()
            )
            if coordinator is None:
                raise NotFoundError(f"Project '{slug}' has no runtime state.")

            if challenge.status == "ARCHIVED":
                if action == "archive":
                    return self._challenge_dict(challenge, coordinator)
                raise InvariantError(
                    "An archived project cannot be restarted.",
                    action=action,
                    status="ARCHIVED",
                )

            if action == "archive":
                if coordinator.status in {"RUNNING", "WAITING"}:
                    raise InvariantError(
                        "Pause or stop the project before archiving it.",
                        status=coordinator.status,
                    )
                challenge.status = "ARCHIVED"
                coordinator.status = "STOPPED"
                expire_open_requests(
                    session,
                    challenge_id=challenge.id,
                    actor=actor,
                    reason="project_archived",
                )
                target = "ARCHIVED"
            else:
                target = PROJECT_TRANSITIONS[action].get(coordinator.status)
                if target is None:
                    if (
                        (action in {"start", "resume"} and coordinator.status == "RUNNING")
                        or (action == "pause" and coordinator.status == "PAUSED")
                        or (action == "stop" and coordinator.status == "STOPPED")
                    ):
                        return self._challenge_dict(challenge, coordinator)
                    raise InvariantError(
                        f"Cannot {action} a project while it is {coordinator.status}.",
                        action=action,
                        status=coordinator.status,
                    )
                coordinator.status = target

            coordinator.worker_id = None
            coordinator.wake_at = None
            coordinator.heartbeat_at = utcnow()
            coordinator.updated_at = utcnow()
            coordinator.version += 1
            challenge.updated_at = utcnow()
            self._record_event(
                session,
                challenge=challenge,
                event_type={
                    "start": "project.started",
                    "pause": "project.paused",
                    "resume": "project.resumed",
                    "stop": "project.stopped",
                    "archive": "project.archived",
                }[action],
                actor=actor,
                command_id=command_id,
                payload={"action": action, "status": target},
            )
            session.flush()
            return self._challenge_dict(challenge, coordinator)

        return self._execute(command_id, f"project.{action}", actor, operation)

    def set_variable(
        self,
        *,
        slug: str,
        name: str,
        value: str,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        name = self._resource_name(name)
        value = self._resource_value("variable", value)
        return self._set_resource(
            slug=slug,
            name=name,
            resource_type="VARIABLE",
            value=value,
            secret_ciphertext=None,
            actor=actor,
            command_id=command_id,
        )

    def set_secret(
        self,
        *,
        slug: str,
        name: str,
        value: str,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        name = self._resource_name(name)
        value = self._resource_value("secret", value)
        if self.secret_cipher is None:
            raise InvariantError("This Limina instance has no secret-encryption provider.")
        ciphertext = self.secret_cipher.encrypt(project=slug.lower(), name=name, value=value)
        return self._set_resource(
            slug=slug,
            name=name,
            resource_type="SECRET",
            value=None,
            secret_ciphertext=ciphertext,
            actor=actor,
            command_id=command_id,
        )

    def _set_resource(
        self,
        *,
        slug: str,
        name: str,
        resource_type: str,
        value: str | None,
        secret_ciphertext: str | None,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:

        def operation(session: Session) -> dict[str, Any]:
            challenge = self._challenge(session, slug)
            existing = session.scalar(
                select(ProjectResource).where(
                    ProjectResource.challenge_id == challenge.id,
                    ProjectResource.name == name,
                )
            )
            if existing is not None:
                existing.resource_type = resource_type
                existing.value = value
                existing.secret_ciphertext = secret_ciphertext
                existing.status = "ACTIVE"
                existing.created_by = actor
                existing.updated_at = utcnow()
                resource = existing
            else:
                resource = ProjectResource(
                    challenge_id=challenge.id,
                    name=name,
                    resource_type=resource_type,
                    value=value,
                    secret_ciphertext=secret_ciphertext,
                    created_by=actor,
                )
                session.add(resource)
            session.flush()
            self._record_event(
                session,
                challenge=challenge,
                event_type=f"resource.{resource_type.lower()}_set",
                actor=actor,
                command_id=command_id,
                payload={"resource_id": resource.id, "name": name, "type": resource_type},
            )
            return self._resource_dict(resource)

        return self._execute(
            command_id,
            f"resource.{resource_type.lower()}.set",
            actor,
            operation,
        )

    def list_resources(self, slug: str, *, active_only: bool = True) -> list[dict[str, Any]]:
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            statement = select(ProjectResource).where(ProjectResource.challenge_id == challenge.id)
            if active_only:
                statement = statement.where(ProjectResource.status == "ACTIVE")
            resources = session.scalars(statement.order_by(ProjectResource.name)).all()
            return [self._resource_dict(resource) for resource in resources]

    def resource_environment(self, slug: str) -> dict[str, str]:
        with self.database.session() as session:
            challenge = self._challenge(session, slug)
            resources = session.scalars(
                select(ProjectResource).where(
                    ProjectResource.challenge_id == challenge.id,
                    ProjectResource.status == "ACTIVE",
                )
            ).all()
            environment: dict[str, str] = {}
            for resource in resources:
                if resource.resource_type == "VARIABLE":
                    if resource.value is None:
                        raise InvariantError(f"Variable '{resource.name}' has no value.")
                    environment[resource.name] = resource.value
                    continue
                if resource.resource_type != "SECRET" or not resource.secret_ciphertext:
                    raise InvariantError(f"Resource '{resource.name}' has invalid secret state.")
                if self.secret_cipher is None:
                    raise InvariantError("This Limina instance has no secret-encryption provider.")
                environment[resource.name] = self.secret_cipher.decrypt(
                    project=challenge.slug,
                    name=resource.name,
                    ciphertext=resource.secret_ciphertext,
                )
            return environment

    def remove_resource(
        self,
        *,
        slug: str,
        name: str,
        actor: str,
        command_id: str,
    ) -> dict[str, Any]:
        name = self._resource_name(name)

        def operation(session: Session) -> dict[str, Any]:
            challenge = self._challenge(session, slug)
            resource = session.scalar(
                select(ProjectResource).where(
                    ProjectResource.challenge_id == challenge.id,
                    ProjectResource.name == name,
                    ProjectResource.status == "ACTIVE",
                )
            )
            if resource is None:
                raise NotFoundError(f"Active resource '{name}' does not exist.")
            resource.status = "REMOVED"
            resource.value = None
            resource.secret_ciphertext = None
            resource.updated_at = utcnow()
            self._record_event(
                session,
                challenge=challenge,
                event_type="resource.removed",
                actor=actor,
                command_id=command_id,
                payload={"resource_id": resource.id, "name": resource.name},
            )
            return self._resource_dict(resource)

        return self._execute(command_id, "resource.remove", actor, operation)
