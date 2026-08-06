export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
export type AttentionKind =
  | "agent_request"
  | "run_failure"
  | "finding_review"
  | "project_complete"
  | "stalled_project"
  | "notification_failure"
  | "preflight_issue"
  | "unattended_run";

export type Me = {
  subject: string;
  display_name: string;
  email: string | null;
  auth_mode: "local" | "oidc" | "workos" | "dev-jwt";
  organization: { id: string; name: string | null } | null;
  permissions: string[];
  capabilities: string[];
  available_runtimes: Array<"codex" | "claude-code">;
};

export type Project = {
  slug: string;
  version: number;
  name: string;
  mission: string;
  success_criteria: string;
  context: string;
  runtime: "codex" | "claude-code";
  status: string;
  current_objective: string;
  next_step: string;
  blocker: string;
  role: "OWNER" | "EDITOR" | "VIEWER" | null;
  capabilities: string[];
  allowed_actions: string[];
  created_at: string;
  updated_at: string;
};

export type ProjectPage = { items: Project[]; next_cursor: string | null; total: number };

export type AttentionItem = {
  id: string;
  kind: AttentionKind;
  project: { slug: string; name: string };
  severity: Severity;
  title: string;
  summary: string;
  status: "OPEN" | "CLOSED";
  source: {
    request_id: string | null;
    artifact_id: string | null;
    artifact_version: number | null;
    run_id: string | null;
    event_sequence: number | null;
  };
  request?: {
    kind: "QUESTION" | "APPROVAL" | "REVIEW" | "BLOCKER";
    response_mode: "TEXT" | "CHOICE" | "CONFIRMATION" | "ARTIFACT_REVIEW";
    choices: string[];
  } | null;
  allowed_actions: string[];
  version: number;
  opened_at: string;
  updated_at: string;
};

export type AttentionPage = {
  items: AttentionItem[];
  next_cursor: string | null;
  last_synced_at: string;
};

export type KnowledgeCounts = Record<string, Record<string, number>>;
export type ProjectStatus = {
  project: Project;
  knowledge: KnowledgeCounts;
  active_work: Array<{ id: string; title: string; status: string }>;
  pending_guidance: number;
  event_cursor: number;
};

export type EventItem = {
  sequence: number;
  type: string;
  actor: string;
  artifact_id: string | null;
  detail: Record<string, unknown>;
  created_at: string;
};

export type Run = {
  id: string;
  runtime: "codex" | "claude-code";
  model: string | null;
  status: string;
  summary: string;
  error: { code: string | null; message: string | null } | null;
  usage: { total_tokens: number | null; cost_microusd: number | null; usage_source: string | null };
  tool_calls: number;
  retry_count: number;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
};

export type RunPage = { items: Run[]; next_cursor: string | null; total: number };

export type ArtifactKind = "H" | "E" | "F" | string;
export type Artifact = {
  id: string;
  kind: ArtifactKind;
  title: string;
  status: string;
  content: Record<string, unknown>;
  version: number;
  hypothesis_id: string | null;
  experiment_id: string | null;
  created_at: string;
  updated_at: string;
  observations?: Array<{
    id: string;
    experiment_id: string;
    body: string;
    evidence_ref: string | null;
    actor: string;
    created_at: string;
  }> | null;
  tags: string[];
};

export type KnowledgePage = {
  items: Artifact[];
  next_cursor: string | null;
  total: number;
  search_backend: "postgresql-fts" | "portable-substring";
};

export type ArtifactRevision = {
  version: number;
  status: string;
  title: string;
  content: Record<string, unknown>;
  actor: string;
  created_at: string;
};

export type ArtifactReview = {
  id: string;
  artifact_id: string;
  artifact_version: number;
  outcome: "ACCEPT" | "ACCEPT_WITH_RESERVATIONS" | "NEEDS_MORE_EVIDENCE" | "REJECT";
  rationale: string;
  reviewer_subject: string;
  reviewer_name: string;
  supersedes_id: string | null;
  guidance_id: string | null;
  interaction_surface: "TODAY" | "PROJECT_DETAIL" | "KNOWLEDGE";
  created_at: string;
};

export type ArtifactComment = {
  id: string;
  artifact_id: string;
  body: string;
  actor: string;
  created_at: string;
};

export type SavedKnowledgeView = {
  id: string;
  name: string;
  query: Record<string, unknown>;
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type EventPage = { events: EventItem[]; cursor: number };
export type RunDetail = Run & { events: EventItem[] };

export type PreflightCheck = {
  name: string;
  status: "PASS" | "WARN" | "FAIL" | "INFO";
  detail: string;
};
export type Preflight = { ready: boolean; checks: PreflightCheck[] };

export type Resource = {
  name: string;
  type: "VARIABLE" | "SECRET";
  status: string;
  value?: string | null;
  configured?: boolean | null;
  created_at: string;
  updated_at: string;
};

export type ProjectMember = {
  subject: string;
  display_name: string;
  email: string | null;
  role: "OWNER" | "EDITOR" | "VIEWER";
  created_at: string;
  updated_at: string;
};

export type ProjectSource = {
  id: string;
  name: string;
  type: "URL" | "CONNECTOR" | "UPLOAD";
  uri: string;
  media_type: string | null;
  metadata: Record<string, unknown>;
  status: string;
  created_at: string;
  updated_at: string;
};

export type KickoffTemplate = {
  id: string;
  name: string;
  description: string;
  defaults: { context: string; success_criteria: string };
};

export type RuntimeHealth = {
  ok: boolean;
  version: string;
  runtime_owner: "limina";
  auth_mode: "local" | "oidc" | "workos" | "dev-jwt";
  runtimes: Array<"codex" | "claude-code">;
  interfaces: Record<string, string>;
};

export type AttentionResolution = {
  item: AttentionItem;
  guidance_id: string | null;
  delivery: "LIVE" | "QUEUED" | null;
};

export type GuidanceReceipt = {
  id: string;
  delivery: "LIVE" | "QUEUED";
  kind: string;
  accepted_at: string;
  status: string;
};

export type LiveTicket = { ticket: string; expires_at: string };

export type NotificationChannel = {
  id: string;
  project_id: string;
  type: "SLACK" | "GENERIC_WEBHOOK";
  display_name: string;
  destination: Record<string, string>;
  configured: boolean;
  enabled: boolean;
  health: string;
  consecutive_failures: number;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_tested_at: string | null;
  version: number;
};

export type NotificationRule = {
  id: string;
  project_id: string;
  channel_id: string;
  display_name: string;
  attention_types: AttentionKind[];
  severities: Severity[];
  cooldown_seconds: number;
  enabled: boolean;
  version: number;
};

export type NotificationDelivery = {
  delivery_id: string;
  attempt: number;
  outcome: string;
  response_class: string;
  http_status: number | null;
  error_code: string | null;
  completed_at: string;
};

export type NotificationTest = { delivery_id: string; status: "PENDING" };
