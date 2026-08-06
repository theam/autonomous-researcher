"""Concrete public contracts added for the Limina Console."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, SecretStr

from .schemas import StrictModel


class OrganizationResponse(StrictModel):
    id: str
    name: str | None = None


class MeResponse(StrictModel):
    subject: str
    display_name: str
    email: str | None
    auth_mode: Literal["local", "oidc", "workos", "dev-jwt"]
    organization: OrganizationResponse | None
    permissions: list[str]
    capabilities: list[str]
    available_runtimes: list[Literal["codex", "claude-code"]]


class AttentionProject(StrictModel):
    slug: str
    name: str


class AttentionSource(StrictModel):
    request_id: str | None = None
    artifact_id: str | None = None
    artifact_version: int | None = None
    run_id: str | None = None
    event_sequence: int | None = None


class AttentionRequestDetail(StrictModel):
    kind: Literal["QUESTION", "APPROVAL", "REVIEW", "BLOCKER"]
    response_mode: Literal["TEXT", "CHOICE", "CONFIRMATION", "ARTIFACT_REVIEW"]
    choices: list[str]


class AttentionBase(StrictModel):
    id: str
    project: AttentionProject
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    title: str
    summary: str
    status: Literal["OPEN", "CLOSED"]
    source: AttentionSource
    allowed_actions: list[str]
    version: int
    opened_at: str
    updated_at: str


class AgentRequestAttention(AttentionBase):
    kind: Literal["agent_request"]
    request: AttentionRequestDetail


class RunFailureAttention(AttentionBase):
    kind: Literal["run_failure"]
    request: None = None


class FindingReviewAttention(AttentionBase):
    kind: Literal["finding_review"]
    request: None = None


class ProjectCompleteAttention(AttentionBase):
    kind: Literal["project_complete"]
    request: None = None


class StalledProjectAttention(AttentionBase):
    kind: Literal["stalled_project"]
    request: None = None


class NotificationFailureAttention(AttentionBase):
    kind: Literal["notification_failure"]
    request: None = None


class PreflightIssueAttention(AttentionBase):
    kind: Literal["preflight_issue"]
    request: None = None


class UnattendedRunAttention(AttentionBase):
    kind: Literal["unattended_run"]
    request: None = None


AttentionItem = Annotated[
    AgentRequestAttention
    | RunFailureAttention
    | FindingReviewAttention
    | ProjectCompleteAttention
    | StalledProjectAttention
    | NotificationFailureAttention
    | PreflightIssueAttention
    | UnattendedRunAttention,
    Field(discriminator="kind"),
]


class AttentionPage(StrictModel):
    items: list[AttentionItem]
    next_cursor: str | None
    last_synced_at: str


class AttentionResolutionRequest(StrictModel):
    action: Literal[
        "ANSWER",
        "SELECT",
        "CONFIRM",
        "REJECT",
        "REVIEW",
        "ACKNOWLEDGE",
        "SNOOZE",
    ]
    expected_version: int = Field(ge=1)
    response: str | None = Field(default=None, max_length=32_768)
    choice: str | None = Field(default=None, max_length=500)
    snooze_until: datetime | None = None
    interaction_surface: Literal["TODAY", "PROJECT_DETAIL", "KNOWLEDGE"] = "TODAY"


class AttentionResolutionResponse(StrictModel):
    item: AttentionItem
    guidance_id: str | None
    delivery: Literal["LIVE", "QUEUED"] | None


class ArtifactReviewRequest(StrictModel):
    artifact_version: int = Field(ge=1)
    outcome: Literal[
        "ACCEPT",
        "ACCEPT_WITH_RESERVATIONS",
        "NEEDS_MORE_EVIDENCE",
        "REJECT",
    ]
    rationale: str = Field(default="", max_length=32_768)
    guidance: str | None = Field(default=None, max_length=32_768)
    supersedes_id: str | None = None
    interaction_surface: Literal["TODAY", "PROJECT_DETAIL", "KNOWLEDGE"] = "KNOWLEDGE"


class ArtifactReviewResponse(StrictModel):
    id: str
    artifact_id: str
    artifact_version: int
    outcome: Literal[
        "ACCEPT",
        "ACCEPT_WITH_RESERVATIONS",
        "NEEDS_MORE_EVIDENCE",
        "REJECT",
    ]
    rationale: str
    reviewer_subject: str
    reviewer_name: str
    supersedes_id: str | None
    guidance_id: str | None
    interaction_surface: Literal["TODAY", "PROJECT_DETAIL", "KNOWLEDGE"]
    created_at: str


class ProjectPolicy(StrictModel):
    role: Literal["OWNER", "EDITOR", "VIEWER"]
    capabilities: list[str]
    allowed_actions: list[str]


class NotificationChannelResponse(StrictModel):
    id: str
    project_id: str
    type: Literal["SLACK", "GENERIC_WEBHOOK"]
    display_name: str
    destination: dict[str, str]
    configured: bool
    enabled: bool
    health: str
    consecutive_failures: int
    last_success_at: str | None
    last_failure_at: str | None
    last_tested_at: str | None
    version: int


class NotificationChannelRequest(StrictModel):
    type: Literal["SLACK", "GENERIC_WEBHOOK"]
    display_name: str = Field(min_length=1, max_length=160)
    destination: SecretStr = Field(min_length=1, max_length=4_096)
    signing_secret: SecretStr | None = Field(default=None, max_length=4_096)
    trust_delegation_confirmed: bool


class NotificationRuleResponse(StrictModel):
    id: str
    project_id: str
    channel_id: str
    display_name: str
    attention_types: list[str]
    severities: list[Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]]
    cooldown_seconds: int
    enabled: bool
    version: int


class NotificationRuleRequest(StrictModel):
    channel_id: str
    display_name: str = Field(min_length=1, max_length=160)
    attention_types: list[str] = Field(default_factory=list)
    severities: list[Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]] = Field(default_factory=list)
    cooldown_seconds: int = Field(default=300, ge=0, le=86_400)


class NotificationChannelStateRequest(StrictModel):
    enabled: bool


class NotificationTestResponse(StrictModel):
    delivery_id: str
    status: Literal["PENDING"]


class NotificationDeliveryResponse(StrictModel):
    delivery_id: str
    attempt: int
    outcome: str
    response_class: str
    http_status: int | None
    error_code: str | None
    completed_at: str
