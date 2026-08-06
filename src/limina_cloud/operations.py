"""Public project operations shared by Limina's API transports.

The database service owns research invariants and the supervisor owns managed
execution.  This layer composes the two into the project-level capabilities
that people and external agents are allowed to use.  HTTP and MCP should stay
thin adapters over this contract.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .attention_service import AttentionService
from .auth import Principal
from .capabilities import (
    PROJECT_CREATE,
    attention_action_minimum_role,
    authorized_attention_actions,
    instance_capabilities,
    lifecycle_allowed_actions,
    project_capabilities,
)
from .collaboration import CollaborationService
from .errors import AuthorizationError, NotFoundError
from .exporter import MarkdownExporter
from .models import AttentionEpisode, Challenge, ProjectMember
from .notification_service import NotificationService
from .review_service import ArtifactReviewService
from .runtime import ProjectSupervisor
from .service import ChallengeService

ACTOR_LIMIT = 200
# Command receipts store 64 characters; composed operations reserve room for ":resource".
PUBLIC_COMMAND_ID_LIMIT = 55


def public_project(project: dict[str, Any], *, role: str | None = None) -> dict[str, Any]:
    coordinator = project["coordinator"]
    status = "ARCHIVED" if project["status"] == "ARCHIVED" else coordinator["status"]
    capabilities = project_capabilities(role)
    return {
        "slug": project["slug"],
        "version": project["version"],
        "name": project["name"],
        "mission": project["objective"],
        "success_criteria": project["success_criteria"],
        "context": project["context"],
        "runtime": project["runtime_engine"],
        "status": status,
        "current_objective": coordinator["current_objective"],
        "next_step": coordinator["next_step"],
        "blocker": coordinator["blocker"],
        "role": role,
        "capabilities": list(capabilities),
        "allowed_actions": list(lifecycle_allowed_actions(status, capabilities)),
        "created_at": project["created_at"],
        "updated_at": coordinator["updated_at"],
    }


def public_status(status: dict[str, Any], *, role: str | None = None) -> dict[str, Any]:
    return {
        "project": public_project(status["challenge"], role=role),
        "knowledge": status["counts"],
        "active_work": [public_artifact(item) for item in status["running_experiments"]],
        "pending_guidance": status["pending_inbox"],
        "event_cursor": status["last_event_sequence"],
    }


def public_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    result = {
        "id": artifact["id"],
        "kind": artifact["kind"],
        "title": artifact["title"],
        "status": artifact["status"],
        "content": artifact["payload"],
        "version": artifact["version"],
        "hypothesis_id": artifact.get("hypothesis_id"),
        "experiment_id": artifact.get("experiment_id"),
        "created_at": artifact["created_at"],
        "updated_at": artifact["updated_at"],
        "tags": artifact.get("tags", []),
    }
    if "observations" in artifact:
        result["observations"] = artifact["observations"]
    return result


def public_resource(resource: dict[str, Any]) -> dict[str, Any]:
    result = {
        "name": resource["name"],
        "type": resource["type"],
        "status": resource["status"],
        "created_at": resource["created_at"],
        "updated_at": resource["updated_at"],
    }
    if resource["type"] == "VARIABLE":
        result["value"] = resource["value"]
    else:
        result["configured"] = resource["configured"]
    return result


def public_event(event: dict[str, Any]) -> dict[str, Any] | None:
    event_type = event["type"]
    if event_type in {"coordinator.claimed", "coordinator.released"}:
        return None
    aliases = {
        "challenge.created": "project.created",
        "coordinator.checkpointed": "project.checkpoint",
        "inbox.message_sent": "guidance.received",
        "inbox.message_acknowledged": "guidance.incorporated",
    }
    payload = {
        key: value
        for key, value in event["payload"].items()
        if key
        not in {
            "worker_id",
            "thread_id",
            "continuation_id",
            "turn_id",
            "version",
            "expires_at",
            "message_id",
        }
    }
    actor = event["actor"]
    if actor.startswith("limina:"):
        actor = "Limina"
    if event_type == "challenge.created" and "runtime_engine" in payload:
        payload["runtime"] = payload.pop("runtime_engine")
    summary = str(payload.get("summary", ""))
    if event_type in {"runtime.codex", "runtime.claude-code"} and any(
        marker in summary for marker in ("limina _agent", "limina_agent")
    ):
        payload["summary"] = "Updating durable project knowledge"
    return {
        "sequence": event["sequence"],
        "type": aliases.get(event_type, event_type),
        "actor": actor,
        "artifact_id": event.get("artifact_id"),
        "detail": payload,
        "created_at": event["created_at"],
    }


class ProjectOperations:
    """The stable, provider-neutral collaboration contract."""

    def __init__(
        self,
        service: ChallengeService,
        exporter: MarkdownExporter,
        supervisor: ProjectSupervisor,
        notification_service: NotificationService | None = None,
        console_url: str = "http://127.0.0.1:7433",
    ) -> None:
        self.service = service
        self.exporter = exporter
        self.supervisor = supervisor
        self.notifications = notification_service
        self.console_url = console_url
        self.collaboration = CollaborationService(service.database)
        notification_sink: Callable[[Session, Challenge, AttentionEpisode], None] | None = None
        if notification_service is not None:

            def enqueue_notification(
                session: Session, challenge: Challenge, episode: AttentionEpisode
            ) -> None:
                notification_service.enqueue_attention(
                    session,
                    challenge=challenge,
                    episode=episode,
                    console_url=console_url,
                )

            notification_sink = enqueue_notification

        self.attention = AttentionService(
            service.database,
            notification_sink=notification_sink,
        )
        self.reviews = ArtifactReviewService(service.database)

    @staticmethod
    def _principal(principal: Principal | None, actor: str = "local-admin") -> Principal:
        return principal or Principal.local(actor)

    @staticmethod
    def _command_id(principal: Principal, command_id: str) -> str:
        """Scope public idempotency receipts to the authenticated identity.

        The durable service records a human-friendly actor for audit events.  Display
        names are not identities, however, and two OIDC users may share one.  Hashing
        the signed subject together with the caller's key preserves stable retries
        without exposing the subject or allowing receipt collisions across users.
        """

        digest = hashlib.sha256(f"{principal.subject}\0{command_id}".encode()).hexdigest()
        return f"usr:{digest[:40]}"

    def _attention_challenge_ids(self, principal: Principal) -> set[str]:
        with self.service.database.session() as session:
            statement = select(Challenge.id)
            if not principal.project_admin:
                statement = statement.join(
                    ProjectMember,
                    ProjectMember.challenge_id == Challenge.id,
                ).where(ProjectMember.subject == principal.subject)
            return set(session.scalars(statement).all())

    def _attention_project_id(
        self,
        slug: str,
        principal: Principal,
        *,
        minimum_role: str,
    ) -> str:
        self.collaboration.require_role(slug, principal, minimum_role)
        with self.service.database.session() as session:
            challenge_id = session.scalar(
                select(Challenge.id).where(Challenge.slug == slug.lower())
            )
        if challenge_id is None:
            raise NotFoundError("Project does not exist.")
        return challenge_id

    def reconcile_attention(self) -> None:
        """Materialize attention for active projects from the runtime worker."""

        self.attention.reconcile_active(configured_engines=self.supervisor.configured_engines())

    def create_project(
        self,
        *,
        slug: str,
        name: str,
        mission: str,
        success_criteria: str,
        context: str,
        runtime: str,
        actor: str,
        command_id: str,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        principal = self._principal(principal, actor)
        if PROJECT_CREATE not in instance_capabilities(principal):
            raise AuthorizationError("Project creation permission is required.")
        receipt_id = self._command_id(principal, command_id)
        project = self.service.create_challenge(
            slug=slug,
            name=name,
            objective=mission,
            success_criteria=success_criteria,
            context=context,
            runtime_engine=runtime,
            actor=principal.actor,
            command_id=receipt_id,
            owner_subject=principal.subject,
            owner_display_name=principal.display_name,
            owner_email=principal.email,
        )
        return public_project(project, role="OWNER")

    def list_projects(
        self,
        *,
        include_archived: bool = False,
        principal: Principal | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        principal = self._principal(principal)
        visible = self.collaboration.visible_project_slugs(principal)
        projects = []
        for project in self.service.list_projects(include_archived=include_archived):
            if visible is not None and project["slug"] not in visible:
                continue
            role = self.collaboration.role_for(project["slug"], principal)
            projects.append(public_project(project, role=role))
        offset = 0
        if cursor:
            from .collaboration import _page_offset

            offset = _page_offset(cursor)
        limit = min(max(limit, 1), 200)
        items = projects[offset : offset + limit]
        from .collaboration import _next_cursor

        return {
            "items": items,
            "next_cursor": _next_cursor(offset, len(items), len(projects)),
            "total": len(projects),
        }

    def get_project(self, slug: str, *, principal: Principal | None = None) -> dict[str, Any]:
        principal = self._principal(principal)
        role = self.collaboration.require_role(slug, principal, "VIEWER")
        return public_project(self.service.get_challenge(slug), role=role)

    def get_status(self, slug: str, *, principal: Principal | None = None) -> dict[str, Any]:
        principal = self._principal(principal)
        role = self.collaboration.require_role(slug, principal, "VIEWER")
        return public_status(self.service.status(slug), role=role)

    def attention_items(
        self,
        *,
        principal: Principal,
        project: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
        include_closed: bool = False,
    ) -> dict[str, Any]:
        challenge_ids = self._attention_challenge_ids(principal)
        if project is not None:
            challenge_ids = {self._attention_project_id(project, principal, minimum_role="VIEWER")}
        self.attention.reconcile(
            allowed_challenge_ids=challenge_ids,
            configured_engines=self.supervisor.configured_engines(),
        )
        page = self.attention.list_items(
            allowed_challenge_ids=challenge_ids,
            subject=principal.subject,
            cursor=cursor,
            limit=limit,
            include_closed=include_closed,
        )
        page["items"] = [self._authorized_attention_item(item, principal) for item in page["items"]]
        return page

    def _authorized_attention_item(
        self, item: dict[str, Any], principal: Principal
    ) -> dict[str, Any]:
        role = self.collaboration.role_for(item["project"]["slug"], principal)
        return {
            **item,
            "allowed_actions": list(
                authorized_attention_actions(item["kind"], item["allowed_actions"], role)
            ),
        }

    def attention_item(self, item_id: str, *, principal: Principal) -> dict[str, Any]:
        challenge_ids = self._attention_challenge_ids(principal)
        self.attention.reconcile(
            allowed_challenge_ids=challenge_ids,
            configured_engines=self.supervisor.configured_engines(),
        )
        item = self.attention.get_item(
            item_id,
            allowed_challenge_ids=challenge_ids,
        )
        return self._authorized_attention_item(item, principal)

    async def resolve_attention(
        self,
        *,
        item_id: str,
        action: str,
        expected_version: int,
        response: str | None,
        choice: str | None,
        snooze_until: datetime | None,
        interaction_surface: str,
        command_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        visible_ids = self._attention_challenge_ids(principal)
        self.attention.reconcile(
            allowed_challenge_ids=visible_ids,
            configured_engines=self.supervisor.configured_engines(),
        )
        item = self.attention.get_item(item_id, allowed_challenge_ids=visible_ids)
        project_id = self._attention_project_id(
            item["project"]["slug"],
            principal,
            minimum_role=attention_action_minimum_role(item["kind"], action),
        )
        result = self.attention.resolve(
            item_id,
            allowed_challenge_ids={project_id},
            action=action,
            expected_version=expected_version,
            actor_subject=principal.subject,
            actor_name=principal.display_name,
            command_id=self._command_id(principal, command_id),
            response=response,
            choice=choice,
            snooze_until=snooze_until,
            interaction_surface=interaction_surface,
        )
        result["item"] = self._authorized_attention_item(result["item"], principal)
        if result["guidance_id"] is not None:
            await self.supervisor.ensure_running(item["project"]["slug"])
        return result

    async def apply_lifecycle(
        self,
        *,
        slug: str,
        action: str,
        actor: str,
        command_id: str,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        principal = self._principal(principal, actor)
        minimum = "OWNER" if action.lower() == "archive" else "EDITOR"
        role = self.collaboration.require_role(slug, principal, minimum)
        receipt_id = self._command_id(principal, command_id)
        project = self.service.change_project_state(
            slug=slug,
            action=action,
            actor=principal.actor,
            command_id=receipt_id,
        )
        if action.lower() in {"start", "resume"}:
            await self.supervisor.ensure_running(slug)
        elif action.lower() in {"pause", "stop", "archive"}:
            await self.supervisor.stop_runtime(slug)
        return public_project(project, role=role)

    async def steer(
        self,
        *,
        slug: str,
        body: str,
        kind: str,
        actor: str,
        command_id: str,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        principal = self._principal(principal, actor)
        self.collaboration.require_role(slug, principal, "EDITOR")
        receipt_id = self._command_id(principal, command_id)
        if kind.upper() == "INTERRUPT":
            result = await self.supervisor.interrupt(
                slug,
                actor=principal.actor,
                reason=body,
                command_id=receipt_id,
            )
        else:
            result = await self.supervisor.submit_message(
                slug=slug,
                body=body,
                kind=kind,
                actor=principal.actor,
                command_id=receipt_id,
            )
        message = result["message"]
        return {
            "id": message["id"],
            "delivery": result["delivery"],
            "kind": message["kind"],
            "accepted_at": message["created_at"],
            "status": message["status"],
        }

    def review(
        self,
        slug: str,
        *,
        principal: Principal | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        principal = self._principal(principal)
        role = self.collaboration.require_role(slug, principal, "VIEWER")
        status = self.service.status(slug)
        knowledge_page = self.collaboration.query_knowledge(slug, cursor=cursor, limit=limit)
        artifacts = knowledge_page["items"]
        events = self.service.recent_events(slug, limit=200)
        public_events = [item for event in events if (item := public_event(event)) is not None]
        return {
            **public_status(status, role=role),
            "resources": [public_resource(item) for item in self.service.list_resources(slug)],
            "hypotheses": [item for item in artifacts if item["kind"] == "H"],
            "experiments": [item for item in artifacts if item["kind"] == "E"],
            "findings": [item for item in artifacts if item["kind"] == "F"],
            "recent_activity": public_events[-50:],
            "knowledge_cursor": knowledge_page["next_cursor"],
            "knowledge_total": knowledge_page["total"],
        }

    def get_knowledge(
        self, slug: str, artifact_id: str, *, principal: Principal | None = None
    ) -> dict[str, Any]:
        self.collaboration.require_role(slug, self._principal(principal), "VIEWER")
        artifact = public_artifact(self.service.get_artifact(slug, artifact_id))
        artifact["tags"] = self.collaboration.tags(slug, artifact_id)
        return artifact

    def activity(
        self,
        slug: str,
        *,
        after: int = 0,
        limit: int = 200,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        self.collaboration.require_role(slug, self._principal(principal), "VIEWER")
        events = self.service.events(slug, after=after, limit=limit)
        visible = [item for event in events if (item := public_event(event)) is not None]
        return {"events": visible, "cursor": events[-1]["sequence"] if events else after}

    def snapshot(self, slug: str, *, principal: Principal | None = None) -> dict[str, Any]:
        self.collaboration.require_role(slug, self._principal(principal), "VIEWER")
        return {"files": self.exporter.snapshot(slug)}

    async def set_variable(
        self,
        *,
        slug: str,
        name: str,
        value: str,
        actor: str,
        command_id: str,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        principal = self._principal(principal, actor)
        self.collaboration.require_role(slug, principal, "EDITOR")
        receipt_id = self._command_id(principal, command_id)
        resource = self.service.set_variable(
            slug=slug,
            name=name,
            value=value,
            actor=principal.actor,
            command_id=receipt_id,
        )
        await self._resource_changed(
            slug=slug,
            body=f"Project variable '{resource['name']}' was set.",
            kind="ANSWER",
            actor=principal.actor,
            command_id=receipt_id,
        )
        return public_resource(resource)

    async def set_secret(
        self,
        *,
        slug: str,
        name: str,
        value: str,
        actor: str,
        command_id: str,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        principal = self._principal(principal, actor)
        self.collaboration.require_role(slug, principal, "OWNER")
        receipt_id = self._command_id(principal, command_id)
        resource = self.service.set_secret(
            slug=slug,
            name=name,
            value=value,
            actor=principal.actor,
            command_id=receipt_id,
        )
        await self._resource_changed(
            slug=slug,
            body=f"Project secret '{resource['name']}' was set.",
            kind="ANSWER",
            actor=principal.actor,
            command_id=receipt_id,
        )
        return public_resource(resource)

    def list_resources(
        self, slug: str, *, principal: Principal | None = None
    ) -> list[dict[str, Any]]:
        self.collaboration.require_role(slug, self._principal(principal), "VIEWER")
        return [public_resource(item) for item in self.service.list_resources(slug)]

    async def remove_resource(
        self,
        *,
        slug: str,
        name: str,
        actor: str,
        command_id: str,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        principal = self._principal(principal, actor)
        self.collaboration.require_role(slug, principal, "OWNER")
        receipt_id = self._command_id(principal, command_id)
        resource = self.service.remove_resource(
            slug=slug,
            name=name,
            actor=principal.actor,
            command_id=receipt_id,
        )
        await self._resource_changed(
            slug=slug,
            body=f"Resource '{resource['name']}' has been revoked.",
            kind="STEER",
            actor=principal.actor,
            command_id=receipt_id,
        )
        return public_resource(resource)

    def update_project(
        self,
        *,
        slug: str,
        values: dict[str, Any],
        expected_version: int,
        command_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        role = self.collaboration.require_role(slug, principal, "OWNER")
        project = self.service.update_project_draft(
            slug=slug,
            name=values.get("name"),
            objective=values.get("mission"),
            context=values.get("context"),
            success_criteria=values.get("success_criteria"),
            runtime_engine=values.get("runtime"),
            expected_version=expected_version,
            actor=principal.actor,
            command_id=self._command_id(principal, command_id),
        )
        return public_project(project, role=role)

    def clone_project(
        self,
        *,
        source_slug: str,
        slug: str,
        name: str,
        command_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        self.collaboration.require_role(source_slug, principal, "VIEWER")
        if PROJECT_CREATE not in instance_capabilities(principal):
            raise AuthorizationError("Project creation permission is required.")
        source = self.service.get_challenge(source_slug)
        project = self.service.create_challenge(
            slug=slug,
            name=name,
            objective=source["objective"],
            success_criteria=source["success_criteria"],
            context=source["context"],
            runtime_engine=source["runtime_engine"],
            actor=principal.actor,
            command_id=self._command_id(principal, command_id),
            owner_subject=principal.subject,
            owner_display_name=principal.display_name,
            owner_email=principal.email,
        )
        return public_project(project, role="OWNER")

    @staticmethod
    def kickoff_templates() -> list[dict[str, Any]]:
        return [
            {
                "id": "technical-investigation",
                "name": "Technical investigation",
                "description": (
                    "Resolve a technical uncertainty with a falsifiable evidence chain."
                ),
                "defaults": {
                    "context": (
                        "State the current system, strongest baseline, constraints, "
                        "and available data."
                    ),
                    "success_criteria": (
                        "A decision is supported by reproducible evidence and remaining "
                        "uncertainty is explicit."
                    ),
                },
            },
            {
                "id": "capability-evaluation",
                "name": "Capability evaluation",
                "description": (
                    "Test whether a capability is credible beyond a narrow benchmark slice."
                ),
                "defaults": {
                    "context": (
                        "Describe the capability, evaluation set, baseline, and shortcut risks."
                    ),
                    "success_criteria": (
                        "The capability beats a fair baseline with guardrails and "
                        "generalization checks."
                    ),
                },
            },
            {
                "id": "incident-learning",
                "name": "Incident learning",
                "description": (
                    "Investigate a failure mechanism and establish a durable prevention strategy."
                ),
                "defaults": {
                    "context": (
                        "Include the incident timeline, symptoms, evidence, and known "
                        "system changes."
                    ),
                    "success_criteria": (
                        "The mechanism is reproduced or bounded and a verified prevention "
                        "is identified."
                    ),
                },
            },
        ]

    def preflight(self, slug: str, *, principal: Principal) -> dict[str, Any]:
        self.collaboration.require_role(slug, principal, "VIEWER")
        return self.collaboration.preflight(
            slug, configured_engines=self.supervisor.configured_engines()
        )

    def members(self, slug: str, *, principal: Principal) -> list[dict[str, Any]]:
        self.collaboration.require_role(slug, principal, "VIEWER")
        return self.collaboration.list_members(slug)

    def set_member(
        self,
        *,
        slug: str,
        subject: str,
        display_name: str,
        email: str | None,
        role: str,
        principal: Principal,
    ) -> dict[str, Any]:
        self.collaboration.require_role(slug, principal, "OWNER")
        return self.collaboration.set_member(
            slug=slug,
            subject=subject,
            display_name=display_name,
            email=email,
            role=role,
            actor=principal.actor,
        )

    def remove_member(self, slug: str, subject: str, *, principal: Principal) -> dict[str, Any]:
        self.collaboration.require_role(slug, principal, "OWNER")
        return self.collaboration.remove_member(slug=slug, subject=subject, actor=principal.actor)

    def notification_channels(self, slug: str, *, principal: Principal) -> list[dict[str, Any]]:
        project_id = self._attention_project_id(slug, principal, minimum_role="VIEWER")
        return self._notification_service().list_channels(project_id)

    def notification_rules(self, slug: str, *, principal: Principal) -> list[dict[str, Any]]:
        project_id = self._attention_project_id(slug, principal, minimum_role="VIEWER")
        return self._notification_service().list_rules(project_id)

    def create_notification_channel(
        self,
        *,
        slug: str,
        channel_type: str,
        display_name: str,
        destination: str,
        signing_secret: str | None,
        trust_delegation_confirmed: bool,
        command_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        project_id = self._attention_project_id(slug, principal, minimum_role="OWNER")
        return self._notification_service().create_channel(
            challenge_id=project_id,
            channel_type=channel_type,
            display_name=display_name,
            destination=destination,
            signing_secret=signing_secret,
            actor=principal.subject,
            trust_delegation_confirmed=trust_delegation_confirmed,
            command_id=self._command_id(principal, command_id),
        )

    def create_notification_rule(
        self,
        *,
        slug: str,
        channel_id: str,
        display_name: str,
        attention_types: list[str],
        severities: list[str],
        cooldown_seconds: int,
        command_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        project_id = self._attention_project_id(slug, principal, minimum_role="OWNER")
        return self._notification_service().create_rule(
            challenge_id=project_id,
            channel_id=channel_id,
            display_name=display_name,
            attention_types=attention_types,
            severities=severities,
            cooldown_seconds=cooldown_seconds,
            actor=principal.subject,
            command_id=self._command_id(principal, command_id),
        )

    def set_notification_channel_enabled(
        self,
        *,
        slug: str,
        channel_id: str,
        enabled: bool,
        command_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        self._require_notification_channel(slug, channel_id, principal, minimum_role="OWNER")
        return self._notification_service().set_channel_enabled(
            channel_id=channel_id,
            enabled=enabled,
            actor=principal.subject,
            command_id=self._command_id(principal, command_id),
        )

    def test_notification_channel(
        self,
        *,
        slug: str,
        channel_id: str,
        command_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        self._require_notification_channel(slug, channel_id, principal, minimum_role="OWNER")
        delivery_id = self._notification_service().enqueue_test(
            channel_id=channel_id,
            console_url=self.console_url,
            actor=principal.subject,
            command_id=self._command_id(principal, command_id),
        )
        return {"delivery_id": delivery_id, "status": "PENDING"}

    def notification_delivery_history(
        self, *, slug: str, channel_id: str, principal: Principal
    ) -> list[dict[str, Any]]:
        self._require_notification_channel(slug, channel_id, principal, minimum_role="VIEWER")
        return self._notification_service().delivery_history(channel_id)

    def _require_notification_channel(
        self,
        slug: str,
        channel_id: str,
        principal: Principal,
        *,
        minimum_role: str,
    ) -> None:
        project_id = self._attention_project_id(slug, principal, minimum_role=minimum_role)
        if not any(
            item["id"] == channel_id
            for item in self._notification_service().list_channels(project_id)
        ):
            raise NotFoundError("The notification channel does not exist in this project.")

    def _notification_service(self) -> NotificationService:
        if self.notifications is None:
            raise AuthorizationError("Notification delivery is not configured for this instance.")
        return self.notifications

    def issue_live_ticket(self, slug: str, *, principal: Principal) -> dict[str, Any]:
        role = self.collaboration.require_role(slug, principal, "VIEWER")
        return self.collaboration.issue_live_ticket(slug, principal, role)

    def guidance(
        self,
        slug: str,
        *,
        status: str | None,
        cursor: str | None,
        limit: int,
        principal: Principal,
    ) -> dict[str, Any]:
        self.collaboration.require_role(slug, principal, "VIEWER")
        return self.collaboration.guidance(slug, status=status, cursor=cursor, limit=limit)

    def query_knowledge(
        self,
        slug: str,
        *,
        query: str | None,
        kind: str | None,
        status: str | None,
        tag: str | None,
        cursor: str | None,
        limit: int,
        principal: Principal,
    ) -> dict[str, Any]:
        self.collaboration.require_role(slug, principal, "VIEWER")
        return self.collaboration.query_knowledge(
            slug,
            query=query,
            kind=kind,
            status=status,
            tag=tag,
            cursor=cursor,
            limit=limit,
        )

    def knowledge_graph(self, slug: str, *, principal: Principal) -> dict[str, Any]:
        self.collaboration.require_role(slug, principal, "VIEWER")
        return self.collaboration.graph(slug)

    def revisions(
        self, slug: str, artifact_id: str, *, principal: Principal
    ) -> list[dict[str, Any]]:
        self.collaboration.require_role(slug, principal, "VIEWER")
        return self.collaboration.revisions(slug, artifact_id)

    def artifact_reviews(
        self, slug: str, artifact_id: str, *, principal: Principal
    ) -> list[dict[str, Any]]:
        self.collaboration.require_role(slug, principal, "VIEWER")
        return self.reviews.list_reviews(slug, artifact_id)

    async def review_artifact(
        self,
        *,
        slug: str,
        artifact_id: str,
        artifact_version: int,
        outcome: str,
        rationale: str,
        guidance: str | None,
        supersedes_id: str | None,
        interaction_surface: str,
        command_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        self.collaboration.require_role(slug, principal, "EDITOR")
        result = self.reviews.create_review(
            slug=slug,
            artifact_id=artifact_id,
            artifact_version=artifact_version,
            outcome=outcome,
            rationale=rationale,
            guidance=guidance,
            supersedes_id=supersedes_id,
            interaction_surface=interaction_surface,
            principal=principal,
            command_id=self._command_id(principal, command_id),
        )
        if result["guidance"] is not None:
            await self.supervisor.ensure_running(slug)
        return result["review"]

    def create_relation(
        self,
        *,
        slug: str,
        source_id: str,
        target_id: str,
        relation_type: str,
        description: str,
        principal: Principal,
    ) -> dict[str, Any]:
        self.collaboration.require_role(slug, principal, "EDITOR")
        return self.collaboration.create_relation(
            slug=slug,
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            description=description,
            actor=principal.actor,
        )

    def delete_relation(
        self, slug: str, relation_id: str, *, principal: Principal
    ) -> dict[str, Any]:
        self.collaboration.require_role(slug, principal, "EDITOR")
        return self.collaboration.delete_relation(slug, relation_id, actor=principal.actor)

    def comments(
        self, slug: str, artifact_id: str, *, principal: Principal
    ) -> list[dict[str, Any]]:
        self.collaboration.require_role(slug, principal, "VIEWER")
        return self.collaboration.comments(slug, artifact_id)

    def add_comment(
        self,
        *,
        slug: str,
        artifact_id: str,
        body: str,
        command_id: str,
        principal: Principal,
    ) -> dict[str, Any]:
        self.collaboration.require_role(slug, principal, "EDITOR")
        return self.collaboration.add_comment(
            slug=slug,
            artifact_id=artifact_id,
            body=body,
            actor=principal.actor,
            command_id=self._command_id(principal, command_id),
        )

    def tags(self, slug: str, artifact_id: str, *, principal: Principal) -> list[str]:
        self.collaboration.require_role(slug, principal, "VIEWER")
        return self.collaboration.tags(slug, artifact_id)

    def add_tag(self, slug: str, artifact_id: str, tag: str, *, principal: Principal) -> list[str]:
        self.collaboration.require_role(slug, principal, "EDITOR")
        return self.collaboration.add_tag(slug, artifact_id, tag, actor=principal.actor)

    def remove_tag(
        self, slug: str, artifact_id: str, tag: str, *, principal: Principal
    ) -> list[str]:
        self.collaboration.require_role(slug, principal, "EDITOR")
        return self.collaboration.remove_tag(slug, artifact_id, tag, actor=principal.actor)

    def saved_views(self, slug: str, *, principal: Principal) -> list[dict[str, Any]]:
        self.collaboration.require_role(slug, principal, "VIEWER")
        return self.collaboration.saved_views(slug)

    def save_view(
        self,
        *,
        slug: str,
        name: str,
        query: dict[str, Any],
        principal: Principal,
    ) -> dict[str, Any]:
        self.collaboration.require_role(slug, principal, "EDITOR")
        return self.collaboration.save_view(
            slug=slug, name=name, query=query, actor=principal.actor
        )

    def delete_view(self, slug: str, view_id: str, *, principal: Principal) -> dict[str, Any]:
        self.collaboration.require_role(slug, principal, "EDITOR")
        return self.collaboration.delete_view(slug, view_id, actor=principal.actor)

    def sources(self, slug: str, *, principal: Principal) -> list[dict[str, Any]]:
        self.collaboration.require_role(slug, principal, "VIEWER")
        return self.collaboration.sources(slug)

    def set_source(
        self,
        *,
        slug: str,
        name: str,
        source_type: str,
        uri: str,
        media_type: str | None,
        metadata: dict[str, Any],
        principal: Principal,
    ) -> dict[str, Any]:
        self.collaboration.require_role(slug, principal, "EDITOR")
        return self.collaboration.set_source(
            slug=slug,
            name=name,
            source_type=source_type,
            uri=uri,
            media_type=media_type,
            metadata=metadata,
            actor=principal.actor,
        )

    def remove_source(self, slug: str, source_id: str, *, principal: Principal) -> dict[str, Any]:
        self.collaboration.require_role(slug, principal, "EDITOR")
        return self.collaboration.remove_source(slug, source_id, actor=principal.actor)

    def runs(
        self,
        slug: str,
        *,
        status: str | None,
        cursor: str | None,
        limit: int,
        principal: Principal,
    ) -> dict[str, Any]:
        self.collaboration.require_role(slug, principal, "VIEWER")
        return self.collaboration.runs(slug, status=status, cursor=cursor, limit=limit)

    def run(self, slug: str, run_id: str, *, principal: Principal) -> dict[str, Any]:
        self.collaboration.require_role(slug, principal, "VIEWER")
        result = self.collaboration.run(slug, run_id)
        result["events"] = [
            visible for event in result["events"] if (visible := public_event(event)) is not None
        ]
        return result

    def analytics(self, slug: str, *, days: int, principal: Principal) -> dict[str, Any]:
        self.collaboration.require_role(slug, principal, "VIEWER")
        return self.collaboration.analytics(slug, days=days)

    async def _resource_changed(
        self,
        *,
        slug: str,
        body: str,
        kind: str,
        actor: str,
        command_id: str,
    ) -> None:
        await self.supervisor.submit_message(
            slug=slug,
            body=body,
            kind=kind,
            actor=actor,
            command_id=f"{command_id}:resource",
            live_delivery=False,
        )
        await self.supervisor.refresh_resources(slug)
        project = self.service.get_challenge(slug)
        if project["coordinator"]["status"] in {"RUNNING", "WAITING"}:
            await self.supervisor.ensure_running(slug)
