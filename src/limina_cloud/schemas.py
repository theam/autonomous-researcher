"""Typed public REST contracts used to generate the Limina OpenAPI document."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorDetail(StrictModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(StrictModel):
    error: ErrorDetail


class HealthResponse(StrictModel):
    ok: bool
    version: str
    runtime_owner: Literal["limina"]
    auth_mode: Literal["local", "oidc"]
    runtimes: list[Literal["codex", "claude-code"]]
    interfaces: dict[str, str]


class CodexAuthLoginRequest(StrictModel):
    method: Literal["chatgpt", "api-key", "access-token"] = "chatgpt"


class CodexAuthStatus(StrictModel):
    engine: Literal["codex"]
    configured_mode: str
    configured: bool
    active_method: Literal["chatgpt", "api-key"] | None
    account_email: str | None
    account_plan: str | None
    source: str
    error: str | None
    single_runtime_node: bool


class CodexDeviceLogin(StrictModel):
    login_id: str
    status: Literal["PENDING", "SUCCEEDED", "FAILED", "CANCELLED"]
    verification_url: str
    user_code: str | None
    error: str | None
    created_at: str
    completed_at: str | None


class ProjectResponse(StrictModel):
    slug: str
    name: str
    mission: str
    success_criteria: str
    context: str
    runtime: Literal["codex", "claude-code"]
    status: str
    current_objective: str
    next_step: str
    blocker: str
    created_at: str
    updated_at: str


class ProjectPage(StrictModel):
    items: list[ProjectResponse]
    next_cursor: str | None
    total: int


class ObservationResponse(StrictModel):
    id: str
    experiment_id: str
    body: str
    evidence_ref: str | None
    actor: str
    created_at: str


class ArtifactResponse(StrictModel):
    id: str
    kind: str
    title: str
    status: str
    content: dict[str, Any]
    hypothesis_id: str | None = None
    experiment_id: str | None = None
    created_at: str
    updated_at: str
    observations: list[ObservationResponse] | None = None
    tags: list[str] = Field(default_factory=list)


class KnowledgePage(StrictModel):
    items: list[ArtifactResponse]
    next_cursor: str | None
    total: int
    search_backend: Literal["postgresql-fts", "portable-substring"]


class EventResponse(StrictModel):
    sequence: int
    type: str
    actor: str
    artifact_id: str | None
    detail: dict[str, Any]
    created_at: str


class EventPage(StrictModel):
    events: list[EventResponse]
    cursor: int


class ResourceResponse(StrictModel):
    name: str
    type: Literal["VARIABLE", "SECRET"]
    status: str
    value: str | None = None
    configured: bool | None = None
    created_at: str
    updated_at: str


class ProjectStatusResponse(StrictModel):
    project: ProjectResponse
    knowledge: dict[str, dict[str, int]]
    active_work: list[ArtifactResponse]
    pending_guidance: int
    event_cursor: int


class ReviewResponse(ProjectStatusResponse):
    resources: list[ResourceResponse]
    hypotheses: list[ArtifactResponse]
    experiments: list[ArtifactResponse]
    findings: list[ArtifactResponse]
    recent_activity: list[EventResponse]
    knowledge_cursor: str | None
    knowledge_total: int


class SnapshotResponse(StrictModel):
    files: dict[str, str]


class CreateProjectRequest(StrictModel):
    slug: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=240)
    objective: str = Field(min_length=1)
    success_criteria: str = Field(min_length=1)
    context: str = ""
    runtime: Literal["codex", "claude-code"] = "codex"


class UpdateProjectRequest(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    mission: str | None = Field(default=None, min_length=1)
    success_criteria: str | None = Field(default=None, min_length=1)
    context: str | None = None
    runtime: Literal["codex", "claude-code"] | None = None


class SteeringRequest(StrictModel):
    body: str = Field(min_length=1)
    kind: Literal["STEER", "ANSWER", "APPROVAL", "BLOCKER", "INTERRUPT"] = "STEER"


class GuidanceReceipt(StrictModel):
    id: str
    delivery: Literal["LIVE", "QUEUED"]
    kind: str
    accepted_at: str
    status: str


class GuidanceResponse(StrictModel):
    id: str
    sequence: int
    kind: str
    body: str
    actor: str
    status: str
    created_at: str
    acknowledged_at: str | None


class GuidancePage(StrictModel):
    items: list[GuidanceResponse]
    next_cursor: str | None
    total: int


class VariableValueRequest(StrictModel):
    value: str = Field(min_length=1, max_length=32_768)


class SecretValueRequest(StrictModel):
    value: SecretStr = Field(min_length=1, max_length=32_768)


class MemberRequest(StrictModel):
    subject: str = Field(min_length=1, max_length=300)
    display_name: str = Field(min_length=1, max_length=240)
    email: str | None = Field(default=None, max_length=320)
    role: Literal["OWNER", "EDITOR", "VIEWER"]


class MemberResponse(StrictModel):
    subject: str
    display_name: str
    email: str | None
    role: Literal["OWNER", "EDITOR", "VIEWER"]
    created_at: str
    updated_at: str


class LiveTicketResponse(StrictModel):
    ticket: str
    expires_at: str


class RelationRequest(StrictModel):
    source_id: str
    target_id: str
    type: str = Field(min_length=1, max_length=80)
    description: str = ""


class RelationResponse(StrictModel):
    id: str
    source_id: str
    target_id: str
    type: str
    description: str
    derived: bool
    created_by: str
    created_at: str | None


class KnowledgeGraphResponse(StrictModel):
    nodes: list[ArtifactResponse]
    edges: list[RelationResponse]


class RevisionResponse(StrictModel):
    version: int
    status: str
    title: str
    content: dict[str, Any]
    actor: str
    created_at: str


class CommentRequest(StrictModel):
    body: str = Field(min_length=1)


class CommentResponse(StrictModel):
    id: str
    artifact_id: str
    body: str
    actor: str
    created_at: str


class TagResponse(StrictModel):
    tags: list[str]


class SavedViewRequest(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    query: dict[str, Any]


class SavedViewResponse(StrictModel):
    id: str
    name: str
    query: dict[str, Any]
    created_by: str
    created_at: str
    updated_at: str


class SourceRequest(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    type: Literal["URL", "CONNECTOR"]
    uri: str = Field(min_length=1)
    media_type: str | None = Field(default=None, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceResponse(StrictModel):
    id: str
    name: str
    type: Literal["URL", "CONNECTOR", "UPLOAD"]
    uri: str
    media_type: str | None
    metadata: dict[str, Any]
    status: str
    created_at: str
    updated_at: str


class TemplateDefaults(StrictModel):
    context: str
    success_criteria: str


class KickoffTemplate(StrictModel):
    id: str
    name: str
    description: str
    defaults: TemplateDefaults


class PreflightCheck(StrictModel):
    name: str
    status: Literal["PASS", "WARN", "FAIL", "INFO"]
    detail: str


class PreflightResponse(StrictModel):
    ready: bool
    checks: list[PreflightCheck]


class RunUsage(StrictModel):
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None
    reasoning_output_tokens: int | None
    total_tokens: int | None
    cost_microusd: int | None
    usage_source: str | None
    cost_source: str | None


class RunError(StrictModel):
    code: str | None
    message: str | None


class RuntimeRunResponse(StrictModel):
    id: str
    runtime: Literal["codex", "claude-code"]
    model: str | None
    status: str
    summary: str
    error: RunError | None
    usage: RunUsage
    tool_calls: int
    retry_count: int
    started_at: str
    completed_at: str | None
    duration_ms: int | None


class RuntimeRunDetail(RuntimeRunResponse):
    events: list[EventResponse]


class RuntimeRunPage(StrictModel):
    items: list[RuntimeRunResponse]
    next_cursor: str | None
    total: int


class AnalyticsWindow(StrictModel):
    days: int
    since: str


class RunAnalytics(StrictModel):
    total: int
    by_status: dict[str, int]
    success_rate: float | None
    average_duration_ms: int | None
    p95_duration_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    reasoning_output_tokens: int | None
    total_tokens: int | None
    cost_microusd: int | None
    usage_sources: list[str]
    cost_sources: list[str]
    tool_calls: int


class KnowledgeAnalytics(StrictModel):
    created: int
    by_kind: dict[str, int]
    by_status: dict[str, int]


class GuidanceAnalytics(StrictModel):
    total: int
    pending: int
    average_acknowledgement_seconds: int | None


class AnalyticsPoint(StrictModel):
    date: str
    runs: int
    completed_runs: int
    failed_runs: int
    artifacts: int
    guidance: int


class AnalyticsResponse(StrictModel):
    window: AnalyticsWindow
    runs: RunAnalytics
    knowledge: KnowledgeAnalytics
    guidance: GuidanceAnalytics
    timeseries: list[AnalyticsPoint]


# Internal runtime command contracts stay out of the public OpenAPI document.
class HypothesisRequest(StrictModel):
    title: str
    statement: str
    mechanism: str = ""
    generalization: str = ""
    shortcut_risks: str = ""
    test_plan: str = ""


class HypothesisDecisionRequest(StrictModel):
    status: str
    conclusion: str
    expected_version: int = Field(ge=1)


class ExperimentRequest(StrictModel):
    hypothesis_id: str
    title: str
    objective: str
    procedure: str = ""
    success_criteria: str = ""
    guardrails: str = ""


class ExperimentClaimRequest(StrictModel):
    ttl_seconds: int = Field(default=1800, ge=30, le=86_400)


class ObservationRequest(StrictModel):
    body: str
    evidence_ref: str | None = None


class ExperimentCompletionRequest(StrictModel):
    results: str
    analysis: str
    decision: str
    expected_version: int = Field(ge=1)


class FindingRequest(StrictModel):
    experiment_id: str
    title: str
    finding: str
    evidence: str
    improvement: str = ""
    remaining_debt: str = ""
    next_move: str = ""
    impact: str = "HIGH"
