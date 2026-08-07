import "server-only";

import { cache } from "react";

import { getConsoleSession } from "@/lib/auth/server";
import { env } from "@/lib/env";
import type {
  Artifact,
  ArtifactComment,
  ArtifactReview,
  ArtifactRevision,
  AttentionPage,
  AttentionItem,
  AttentionResolution,
  EventPage,
  GuidanceReceipt,
  KickoffTemplate,
  KnowledgePage,
  LiveTicket,
  Me,
  NotificationChannel,
  NotificationDelivery,
  NotificationRule,
  Preflight,
  Project,
  ProjectMember,
  ProjectPage,
  ProjectSource,
  ProjectStatus,
  Resource,
  RunDetail,
  RunPage,
  RuntimeHealth,
  SavedKnowledgeView,
} from "@/lib/limina/types";

type ErrorEnvelope = { error?: { code?: string; message?: string } };

export class LiminaApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
    this.name = "LiminaApiError";
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const { accessToken } = await getConsoleSession();
  const response = await fetch(`${env.LIMINA_RUNTIME_URL}${path}`, {
    ...init,
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
    headers: {
      accept: "application/json",
      authorization: `Bearer ${accessToken}`,
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const value = (await response.json().catch(() => ({}))) as ErrorEnvelope;
    throw new LiminaApiError(
      value.error?.message ?? "Limina could not complete this request.",
      response.status,
      value.error?.code ?? "HTTP_ERROR",
    );
  }
  return (await response.json()) as T;
}

export const getMe = cache(function getMe(): Promise<Me> {
  return request<Me>("/v2/me");
});

export const listProjects = cache(function listProjects(): Promise<ProjectPage> {
  return request<ProjectPage>("/v2/projects?limit=200");
});

export function getProject(slug: string): Promise<Project> {
  return request<Project>(`/v2/projects/${encodeURIComponent(slug)}`);
}

export function getProjectStatus(slug: string): Promise<ProjectStatus> {
  return request<ProjectStatus>(`/v2/projects/${encodeURIComponent(slug)}/status`);
}

export function listAttention(project?: string): Promise<AttentionPage> {
  const query = project ? `?project=${encodeURIComponent(project)}` : "";
  return request<AttentionPage>(`/v2/attention${query}`);
}

export function getAttentionItem(id: string): Promise<AttentionItem> {
  return request<AttentionItem>(`/v2/attention/${encodeURIComponent(id)}`);
}

export function listRuns(slug: string): Promise<RunPage> {
  return request<RunPage>(`/v2/projects/${encodeURIComponent(slug)}/runs?limit=50`);
}

export function getRun(slug: string, runId: string): Promise<RunDetail> {
  return request<RunDetail>(
    `/v2/projects/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}`,
  );
}

export function listKnowledge(
  slug: string,
  filters: { query?: string; kind?: string; status?: string; tag?: string } = {},
): Promise<KnowledgePage> {
  const query = new URLSearchParams({ limit: "100" });
  for (const [key, value] of Object.entries(filters)) {
    if (value) query.set(key, value);
  }
  return request<KnowledgePage>(
    `/v2/projects/${encodeURIComponent(slug)}/knowledge?${query.toString()}`,
  );
}

export function getArtifact(slug: string, artifactId: string): Promise<Artifact> {
  return request<Artifact>(
    `/v2/projects/${encodeURIComponent(slug)}/knowledge/${encodeURIComponent(artifactId)}`,
  );
}

export function getArtifactRevisions(
  slug: string,
  artifactId: string,
): Promise<ArtifactRevision[]> {
  return request<ArtifactRevision[]>(
    `/v2/projects/${encodeURIComponent(slug)}/knowledge/${encodeURIComponent(artifactId)}/revisions`,
  );
}

export function getArtifactReviews(
  slug: string,
  artifactId: string,
): Promise<ArtifactReview[]> {
  return request<ArtifactReview[]>(
    `/v2/projects/${encodeURIComponent(slug)}/knowledge/${encodeURIComponent(artifactId)}/reviews`,
  );
}

export function getArtifactComments(
  slug: string,
  artifactId: string,
): Promise<ArtifactComment[]> {
  return request<ArtifactComment[]>(
    `/v2/projects/${encodeURIComponent(slug)}/knowledge/${encodeURIComponent(artifactId)}/comments`,
  );
}

export function listSavedKnowledgeViews(slug: string): Promise<SavedKnowledgeView[]> {
  return request<SavedKnowledgeView[]>(
    `/v2/projects/${encodeURIComponent(slug)}/knowledge/views`,
  );
}

export function getEvents(slug: string, after = 0): Promise<EventPage> {
  return request<EventPage>(
    `/v2/projects/${encodeURIComponent(slug)}/events?after=${after}&limit=200`,
  );
}

export function getPreflight(slug: string): Promise<Preflight> {
  return request<Preflight>(`/v2/projects/${encodeURIComponent(slug)}/preflight`);
}

export function listResources(slug: string): Promise<Resource[]> {
  return request<Resource[]>(`/v2/projects/${encodeURIComponent(slug)}/resources`);
}

export function listMembers(slug: string): Promise<ProjectMember[]> {
  return request<ProjectMember[]>(`/v2/projects/${encodeURIComponent(slug)}/members`);
}

export function listSources(slug: string): Promise<ProjectSource[]> {
  return request<ProjectSource[]>(`/v2/projects/${encodeURIComponent(slug)}/sources`);
}

export function listTemplates(): Promise<KickoffTemplate[]> {
  return request<KickoffTemplate[]>("/v2/project-templates");
}

export function listNotificationChannels(slug: string): Promise<NotificationChannel[]> {
  return request<NotificationChannel[]>(
    `/v2/projects/${encodeURIComponent(slug)}/notifications/channels`,
  );
}

export function listNotificationRules(slug: string): Promise<NotificationRule[]> {
  return request<NotificationRule[]>(
    `/v2/projects/${encodeURIComponent(slug)}/notifications/rules`,
  );
}

export function listNotificationDeliveries(
  slug: string,
  channelId: string,
): Promise<NotificationDelivery[]> {
  return request<NotificationDelivery[]>(
    `/v2/projects/${encodeURIComponent(slug)}/notifications/channels/${encodeURIComponent(channelId)}/deliveries`,
  );
}

export function getRuntimeHealth(): Promise<RuntimeHealth> {
  return request<RuntimeHealth>("/healthz");
}

export function createProject(
  body: {
    slug: string;
    name: string;
    objective: string;
    success_criteria: string;
    context: string;
    runtime: "codex" | "claude-code";
  },
  idempotencyKey: string,
): Promise<Project> {
  return mutate<Project>("/v2/projects", body, idempotencyKey);
}

export function resolveAttention(
  id: string,
  body: {
    action: string;
    expected_version: number;
    response?: string;
    choice?: string;
    snooze_until?: string;
    interaction_surface: "TODAY" | "PROJECT_DETAIL" | "KNOWLEDGE";
  },
  idempotencyKey: string,
): Promise<AttentionResolution> {
  return mutate<AttentionResolution>(
    `/v2/attention/${encodeURIComponent(id)}/resolve`,
    body,
    idempotencyKey,
  );
}

export function steerProject(
  slug: string,
  body: { body: string; kind: string },
  idempotencyKey: string,
): Promise<GuidanceReceipt> {
  return mutate<GuidanceReceipt>(
    `/v2/projects/${encodeURIComponent(slug)}/steering`,
    body,
    idempotencyKey,
  );
}

export function getLiveTicket(slug: string, idempotencyKey: string): Promise<LiveTicket> {
  return mutate<LiveTicket>(
    `/v2/projects/${encodeURIComponent(slug)}/live-ticket`,
    {},
    idempotencyKey,
  );
}

export async function mutate<T>(
  path: string,
  body: unknown,
  idempotencyKey: string,
  method: "POST" | "PUT" | "PATCH" | "DELETE" = "POST",
): Promise<T> {
  return request<T>(path, {
    method,
    headers: {
      "content-type": "application/json",
      "idempotency-key": idempotencyKey,
    },
    body: JSON.stringify(body),
  });
}
