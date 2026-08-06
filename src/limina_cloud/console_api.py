"""Focused HTTP routes that exist specifically for the Console contract."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Query

from .auth import Principal
from .capabilities import instance_capabilities
from .console_schemas import (
    ArtifactReviewRequest,
    ArtifactReviewResponse,
    AttentionItem,
    AttentionPage,
    AttentionResolutionRequest,
    AttentionResolutionResponse,
    MeResponse,
    NotificationChannelRequest,
    NotificationChannelResponse,
    NotificationChannelStateRequest,
    NotificationDeliveryResponse,
    NotificationRuleRequest,
    NotificationRuleResponse,
    NotificationTestResponse,
)


def register_console_routes(
    app: FastAPI,
    runtime: Any,
    *,
    principal_dependency: Any,
    command_dependency: Any,
    public_errors: dict[int, dict[str, Any]],
) -> None:
    """Register Console-only projections without duplicating domain policy."""

    @app.get("/v2/me", response_model=MeResponse, responses=public_errors)
    def current_principal(principal: Principal = principal_dependency) -> dict[str, Any]:
        organization = (
            {"id": principal.organization, "name": None} if principal.organization else None
        )
        available = sorted(runtime.supervisor.configured_engines())
        return {
            "subject": principal.subject,
            "display_name": principal.display_name,
            "email": principal.email,
            "auth_mode": principal.auth_mode,
            "organization": organization,
            "permissions": sorted(principal.permissions),
            "capabilities": list(instance_capabilities(principal)),
            "available_runtimes": available,
        }

    @app.get("/v2/attention", response_model=AttentionPage, responses=public_errors)
    def list_attention(
        principal: Principal = principal_dependency,
        project: str | None = Query(default=None),
        cursor: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=100),
    ) -> dict[str, Any]:
        return runtime.operations.attention_items(
            principal=principal,
            project=project,
            cursor=cursor,
            limit=limit,
        )

    @app.get(
        "/v2/attention/{item_id}",
        response_model=AttentionItem,
        responses=public_errors,
    )
    def get_attention(
        item_id: str,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return runtime.operations.attention_item(item_id, principal=principal)

    @app.post(
        "/v2/attention/{item_id}/resolve",
        response_model=AttentionResolutionResponse,
        responses=public_errors,
    )
    async def resolve_attention(
        item_id: str,
        body: AttentionResolutionRequest,
        command_id: str = command_dependency,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        result = await runtime.operations.resolve_attention(
            item_id=item_id,
            action=body.action,
            expected_version=body.expected_version,
            response=body.response,
            choice=body.choice,
            snooze_until=body.snooze_until,
            interaction_surface=body.interaction_surface,
            command_id=command_id,
            principal=principal,
        )
        return {
            "item": result["item"],
            "guidance_id": result["guidance_id"],
            "delivery": result["delivery"],
        }

    @app.get(
        "/v2/projects/{slug}/attention",
        response_model=AttentionPage,
        responses=public_errors,
    )
    def project_attention(
        slug: str,
        principal: Principal = principal_dependency,
        cursor: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=100),
    ) -> dict[str, Any]:
        return runtime.operations.attention_items(
            principal=principal,
            project=slug,
            cursor=cursor,
            limit=limit,
            include_closed=True,
        )

    @app.get(
        "/v2/projects/{slug}/knowledge/{artifact_id}/reviews",
        response_model=list[ArtifactReviewResponse],
        responses=public_errors,
    )
    def list_artifact_reviews(
        slug: str,
        artifact_id: str,
        principal: Principal = principal_dependency,
    ) -> list[dict[str, Any]]:
        return runtime.operations.artifact_reviews(slug, artifact_id, principal=principal)

    @app.post(
        "/v2/projects/{slug}/knowledge/{artifact_id}/reviews",
        status_code=201,
        response_model=ArtifactReviewResponse,
        responses=public_errors,
    )
    async def create_artifact_review(
        slug: str,
        artifact_id: str,
        body: ArtifactReviewRequest,
        command_id: str = command_dependency,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return await runtime.operations.review_artifact(
            slug=slug,
            artifact_id=artifact_id,
            artifact_version=body.artifact_version,
            outcome=body.outcome,
            rationale=body.rationale,
            guidance=body.guidance,
            supersedes_id=body.supersedes_id,
            interaction_surface=body.interaction_surface,
            command_id=command_id,
            principal=principal,
        )

    @app.get(
        "/v2/projects/{slug}/notifications/channels",
        response_model=list[NotificationChannelResponse],
        responses=public_errors,
    )
    def list_notification_channels(
        slug: str, principal: Principal = principal_dependency
    ) -> list[dict[str, Any]]:
        return runtime.operations.notification_channels(slug, principal=principal)

    @app.post(
        "/v2/projects/{slug}/notifications/channels",
        status_code=201,
        response_model=NotificationChannelResponse,
        responses=public_errors,
    )
    def create_notification_channel(
        slug: str,
        body: NotificationChannelRequest,
        command_id: str = command_dependency,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return runtime.operations.create_notification_channel(
            slug=slug,
            channel_type=body.type,
            display_name=body.display_name,
            destination=body.destination.get_secret_value(),
            signing_secret=(
                body.signing_secret.get_secret_value() if body.signing_secret else None
            ),
            trust_delegation_confirmed=body.trust_delegation_confirmed,
            command_id=command_id,
            principal=principal,
        )

    @app.get(
        "/v2/projects/{slug}/notifications/rules",
        response_model=list[NotificationRuleResponse],
        responses=public_errors,
    )
    def list_notification_rules(
        slug: str, principal: Principal = principal_dependency
    ) -> list[dict[str, Any]]:
        return runtime.operations.notification_rules(slug, principal=principal)

    @app.post(
        "/v2/projects/{slug}/notifications/rules",
        status_code=201,
        response_model=NotificationRuleResponse,
        responses=public_errors,
    )
    def create_notification_rule(
        slug: str,
        body: NotificationRuleRequest,
        command_id: str = command_dependency,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return runtime.operations.create_notification_rule(
            slug=slug,
            channel_id=body.channel_id,
            display_name=body.display_name,
            attention_types=body.attention_types,
            severities=body.severities,
            cooldown_seconds=body.cooldown_seconds,
            command_id=command_id,
            principal=principal,
        )

    @app.post(
        "/v2/projects/{slug}/notifications/channels/{channel_id}/state",
        response_model=NotificationChannelResponse,
        responses=public_errors,
    )
    def set_notification_channel_state(
        slug: str,
        channel_id: str,
        body: NotificationChannelStateRequest,
        command_id: str = command_dependency,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return runtime.operations.set_notification_channel_enabled(
            slug=slug,
            channel_id=channel_id,
            enabled=body.enabled,
            command_id=command_id,
            principal=principal,
        )

    @app.post(
        "/v2/projects/{slug}/notifications/channels/{channel_id}/test",
        status_code=202,
        response_model=NotificationTestResponse,
        responses=public_errors,
    )
    def test_notification_channel(
        slug: str,
        channel_id: str,
        command_id: str = command_dependency,
        principal: Principal = principal_dependency,
    ) -> dict[str, Any]:
        return runtime.operations.test_notification_channel(
            slug=slug,
            channel_id=channel_id,
            command_id=command_id,
            principal=principal,
        )

    @app.get(
        "/v2/projects/{slug}/notifications/channels/{channel_id}/deliveries",
        response_model=list[NotificationDeliveryResponse],
        responses=public_errors,
    )
    def notification_delivery_history(
        slug: str,
        channel_id: str,
        principal: Principal = principal_dependency,
    ) -> list[dict[str, Any]]:
        return runtime.operations.notification_delivery_history(
            slug=slug, channel_id=channel_id, principal=principal
        )
