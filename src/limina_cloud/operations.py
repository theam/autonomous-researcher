"""Public project operations shared by Limina's API transports.

The database service owns research invariants and the supervisor owns managed
execution.  This layer composes the two into the project-level capabilities
that people and external agents are allowed to use.  HTTP and MCP should stay
thin adapters over this contract.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .auth import Principal
from .collaboration import CollaborationService
from .exporter import MarkdownExporter
from .runtime import ProjectSupervisor
from .service import ChallengeService

ACTOR_LIMIT = 200
# Command receipts store 64 characters; composed operations reserve room for ":resource".
PUBLIC_COMMAND_ID_LIMIT = 55


def public_project(project: dict[str, Any]) -> dict[str, Any]:
    coordinator = project["coordinator"]
    return {
        "slug": project["slug"],
        "name": project["name"],
        "mission": project["objective"],
        "success_criteria": project["success_criteria"],
        "context": project["context"],
        "runtime": project["runtime_engine"],
        "status": "ARCHIVED" if project["status"] == "ARCHIVED" else coordinator["status"],
        "current_objective": coordinator["current_objective"],
        "next_step": coordinator["next_step"],
        "blocker": coordinator["blocker"],
        "created_at": project["created_at"],
        "updated_at": coordinator["updated_at"],
    }


def public_status(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "project": public_project(status["challenge"]),
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
    if event_type in {"runtime.codex", "runtime.claude-code"} and "limina _agent" in str(
        payload.get("summary", "")
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
    ) -> None:
        self.service = service
        self.exporter = exporter
        self.supervisor = supervisor
        self.collaboration = CollaborationService(service.database)

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
        return public_project(project)

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
        projects = [
            public_project(project)
            for project in self.service.list_projects(include_archived=include_archived)
            if visible is None or project["slug"] in visible
        ]
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
        self.collaboration.require_role(slug, self._principal(principal), "VIEWER")
        return public_project(self.service.get_challenge(slug))

    def get_status(self, slug: str, *, principal: Principal | None = None) -> dict[str, Any]:
        self.collaboration.require_role(slug, self._principal(principal), "VIEWER")
        return public_status(self.service.status(slug))

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
        self.collaboration.require_role(slug, principal, minimum)
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
        return public_project(project)

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
        self.collaboration.require_role(slug, self._principal(principal), "VIEWER")
        status = self.service.status(slug)
        knowledge_page = self.collaboration.query_knowledge(slug, cursor=cursor, limit=limit)
        artifacts = knowledge_page["items"]
        events = self.service.recent_events(slug, limit=200)
        public_events = [item for event in events if (item := public_event(event)) is not None]
        return {
            **public_status(status),
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
        principal: Principal,
    ) -> dict[str, Any]:
        self.collaboration.require_role(slug, principal, "OWNER")
        project = self.collaboration.update_draft(
            slug=slug,
            name=values.get("name"),
            mission=values.get("mission"),
            context=values.get("context"),
            success_criteria=values.get("success_criteria"),
            runtime=values.get("runtime"),
            actor=principal.actor,
        )
        return public_project(project)

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
