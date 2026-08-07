"use server";

import { randomUUID } from "node:crypto";

import { signOut } from "@workos-inc/authkit-nextjs";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { z } from "zod";

import { env } from "@/lib/env";
import {
  createProject,
  LiminaApiError,
  mutate,
  resolveAttention,
  steerProject,
} from "@/lib/limina/server";
import type {
  ArtifactReview,
  ArtifactComment,
  NotificationChannel,
  NotificationRule,
  NotificationTest,
  Project,
  ProjectMember,
  ProjectSource,
  Resource,
  SavedKnowledgeView,
} from "@/lib/limina/types";

const text = z.string().trim().min(1);
const slug = z
  .string()
  .trim()
  .min(1)
  .max(120)
  .regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, "Use lower-case words separated by hyphens.");

const createProjectSchema = z.object({
  slug,
  name: text.max(240),
  objective: text,
  success_criteria: text,
  context: z.string().trim(),
  runtime: z.enum(["codex", "claude-code"]),
});

function formValues(formData: FormData): Record<string, FormDataEntryValue> {
  return Object.fromEntries(formData.entries());
}

export async function signOutAction(): Promise<void> {
  if (env.LIMINA_UI_AUTH_MODE !== "workos") {
    throw new Error("Sign-out is available only for WorkOS sessions.");
  }
  await signOut({ returnTo: env.LIMINA_CONSOLE_ORIGIN });
}

export async function createProjectAction(formData: FormData): Promise<never> {
  const input = createProjectSchema.parse(formValues(formData));
  const project = await createProject(input, randomUUID());
  redirect(`/projects/${encodeURIComponent(project.slug)}`);
}

export async function updateProjectDraftAction(
  projectSlug: string,
  expectedVersion: number,
  formData: FormData,
): Promise<never> {
  const safeSlug = slug.parse(projectSlug);
  const input = z
    .object({
      name: text.max(240),
      mission: text,
      success_criteria: text,
      context: z.string().trim(),
      runtime: z.enum(["codex", "claude-code"]),
    })
    .parse(formValues(formData));
  await mutate<Project>(
    `/v2/projects/${encodeURIComponent(safeSlug)}`,
    { ...input, expected_version: z.number().int().positive().parse(expectedVersion) },
    randomUUID(),
    "PATCH",
  );
  revalidatePath(`/projects/${safeSlug}`);
  revalidatePath(`/projects/${safeSlug}/settings`, "layout");
  redirect(`/projects/${safeSlug}/settings`);
}

export async function cloneProjectAction(
  sourceSlug: string,
  formData: FormData,
): Promise<never> {
  const safeSource = slug.parse(sourceSlug);
  const input = z.object({ slug, name: text.max(240) }).parse(formValues(formData));
  const project = await mutate<Project>(
    `/v2/projects/${encodeURIComponent(safeSource)}/clone`,
    input,
    randomUUID(),
  );
  redirect(`/projects/${encodeURIComponent(project.slug)}/settings`);
}

export async function lifecycleAction(
  projectSlug: string,
  action: string,
): Promise<void> {
  const safeSlug = slug.parse(projectSlug);
  const safeAction = z.enum(["start", "pause", "resume", "stop", "archive"]).parse(action);
  await mutate<Project>(
    `/v2/projects/${encodeURIComponent(safeSlug)}/actions/${safeAction}`,
    {},
    randomUUID(),
  );
  revalidatePath("/");
  revalidatePath(`/projects/${safeSlug}`);
}

export async function steerProjectAction(
  projectSlug: string,
  formData: FormData,
): Promise<void> {
  const safeSlug = slug.parse(projectSlug);
  const input = z
    .object({ body: text.max(32_768), kind: z.enum(["STEER", "ANSWER", "BLOCKER", "INTERRUPT"]) })
    .parse(formValues(formData));
  await steerProject(safeSlug, input, randomUUID());
  revalidatePath(`/projects/${safeSlug}`);
  revalidatePath(`/projects/${safeSlug}/live`);
}

export async function resolveAttentionAction(
  itemId: string,
  expectedVersion: number,
  projectSlug: string,
  interactionSurface: "TODAY" | "PROJECT_DETAIL",
  formData: FormData,
): Promise<never> {
  const safeItemId = text.parse(itemId);
  const safeProjectSlug = slug.parse(projectSlug);
  const input = z
    .object({
      action: z.enum([
        "ANSWER",
        "SELECT",
        "CONFIRM",
        "REJECT",
        "ACKNOWLEDGE",
        "SNOOZE",
      ]),
      response: z.string().trim().max(32_768).optional(),
      choice: z.string().trim().max(500).optional(),
    })
    .parse(formValues(formData));
  const destination =
    interactionSurface === "TODAY"
      ? "/"
      : `/attention/${encodeURIComponent(safeItemId)}`;
  try {
    await resolveAttention(
      safeItemId,
      {
        ...input,
        expected_version: z.number().int().positive().parse(expectedVersion),
        ...(input.action === "SNOOZE"
          ? { snooze_until: new Date(Date.now() + 60 * 60 * 1_000).toISOString() }
          : {}),
        interaction_surface: interactionSurface,
      },
      randomUUID(),
    );
  } catch (error) {
    if (error instanceof LiminaApiError) {
      const notice = error.status === 409 ? "changed" : error.status === 404 ? "gone" : "failed";
      redirect(`${destination}?notice=${notice}`);
    }
    throw error;
  }
  revalidatePath("/");
  revalidatePath(`/attention/${encodeURIComponent(safeItemId)}`);
  revalidatePath(`/projects/${safeProjectSlug}`);
  redirect(`${destination}?notice=resolved`);
}

export async function reviewArtifactAction(
  projectSlug: string,
  artifactId: string,
  artifactVersion: number,
  formData: FormData,
): Promise<void> {
  const safeSlug = slug.parse(projectSlug);
  const input = z
    .object({
      outcome: z.enum([
        "ACCEPT",
        "ACCEPT_WITH_RESERVATIONS",
        "NEEDS_MORE_EVIDENCE",
        "REJECT",
      ]),
      rationale: z.string().trim().max(32_768),
      guidance: z.string().trim().max(32_768).optional(),
    })
    .parse(formValues(formData));
  if (input.outcome !== "ACCEPT" && !input.rationale) {
    throw new Error("A rationale is required unless the evidence is accepted without reservation.");
  }
  await mutate<ArtifactReview>(
    `/v2/projects/${encodeURIComponent(safeSlug)}/knowledge/${encodeURIComponent(artifactId)}/reviews`,
    {
      artifact_version: artifactVersion,
      outcome: input.outcome,
      rationale: input.rationale,
      guidance: input.guidance || null,
      supersedes_id: null,
      interaction_surface: "KNOWLEDGE",
    },
    randomUUID(),
  );
  revalidatePath("/");
  revalidatePath(`/projects/${safeSlug}/knowledge/${encodeURIComponent(artifactId)}`);
}

export async function addArtifactCommentAction(
  projectSlug: string,
  artifactId: string,
  formData: FormData,
): Promise<void> {
  const safeSlug = slug.parse(projectSlug);
  const input = z.object({ body: text.max(32_768) }).parse(formValues(formData));
  await mutate<ArtifactComment>(
    `/v2/projects/${encodeURIComponent(safeSlug)}/knowledge/${encodeURIComponent(text.parse(artifactId))}/comments`,
    input,
    randomUUID(),
  );
  revalidatePath(`/projects/${safeSlug}/knowledge/${encodeURIComponent(artifactId)}`);
}

export async function addArtifactTagAction(
  projectSlug: string,
  artifactId: string,
  formData: FormData,
): Promise<void> {
  const safeSlug = slug.parse(projectSlug);
  const input = z
    .object({ tag: z.string().trim().min(1).max(80).regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/) })
    .parse(formValues(formData));
  await mutate<{ tags: string[] }>(
    `/v2/projects/${encodeURIComponent(safeSlug)}/knowledge/${encodeURIComponent(text.parse(artifactId))}/tags/${encodeURIComponent(input.tag)}`,
    {},
    randomUUID(),
    "PUT",
  );
  revalidatePath(`/projects/${safeSlug}/knowledge`);
  revalidatePath(`/projects/${safeSlug}/knowledge/${encodeURIComponent(artifactId)}`);
}

export async function saveKnowledgeViewAction(
  projectSlug: string,
  formData: FormData,
): Promise<void> {
  const safeSlug = slug.parse(projectSlug);
  const input = z
    .object({
      name: text.max(160),
      query: z.string().trim().max(500).optional(),
      kind: z.string().trim().max(20).optional(),
      status: z.string().trim().max(40).optional(),
      tag: z.string().trim().max(80).optional(),
    })
    .parse(formValues(formData));
  await mutate<SavedKnowledgeView>(
    `/v2/projects/${encodeURIComponent(safeSlug)}/knowledge/views`,
    {
      name: input.name,
      query: Object.fromEntries(
        Object.entries(input)
          .filter(([key, value]) => key !== "name" && Boolean(value))
          .map(([key, value]) => [key, value]),
      ),
    },
    randomUUID(),
    "PUT",
  );
  revalidatePath(`/projects/${safeSlug}/knowledge`);
}

export async function setResourceAction(
  projectSlug: string,
  resourceType: "VARIABLE" | "SECRET",
  formData: FormData,
): Promise<never> {
  const safeSlug = slug.parse(projectSlug);
  const input = z
    .object({ name: z.string().trim().regex(/^[A-Z][A-Z0-9_]*$/), value: text.max(32_768) })
    .parse(formValues(formData));
  const family = resourceType === "SECRET" ? "secrets" : "variables";
  await mutate<Resource>(
    `/v2/projects/${encodeURIComponent(safeSlug)}/resources/${family}/${encodeURIComponent(input.name)}`,
    { value: input.value },
    randomUUID(),
    "PUT",
  );
  revalidatePath(`/projects/${safeSlug}/settings`, "layout");
  redirect(`/projects/${safeSlug}/settings/environment`);
}

export async function setSourceAction(projectSlug: string, formData: FormData): Promise<never> {
  const safeSlug = slug.parse(projectSlug);
  const input = z
    .object({
      name: text.max(200),
      type: z.enum(["URL", "CONNECTOR"]),
      uri: z.string().trim().url(),
    })
    .parse(formValues(formData));
  await mutate<ProjectSource>(
    `/v2/projects/${encodeURIComponent(safeSlug)}/sources`,
    { ...input, media_type: null, metadata: {} },
    randomUUID(),
    "PUT",
  );
  revalidatePath(`/projects/${safeSlug}/settings`, "layout");
  redirect(`/projects/${safeSlug}/settings/sources`);
}

export async function setMemberAction(projectSlug: string, formData: FormData): Promise<never> {
  const safeSlug = slug.parse(projectSlug);
  const input = z
    .object({
      subject: text.max(300),
      display_name: text.max(240),
      email: z.union([z.literal(""), z.string().trim().email()]),
      role: z.enum(["OWNER", "EDITOR", "VIEWER"]),
    })
    .parse(formValues(formData));
  await mutate<ProjectMember>(
    `/v2/projects/${encodeURIComponent(safeSlug)}/members`,
    { ...input, email: input.email || null },
    randomUUID(),
    "PUT",
  );
  revalidatePath(`/projects/${safeSlug}/settings`, "layout");
  redirect(`/projects/${safeSlug}/settings/team`);
}

export async function createNotificationChannelAction(
  projectSlug: string,
  formData: FormData,
): Promise<never> {
  const safeSlug = slug.parse(projectSlug);
  const input = z
    .object({
      type: z.enum(["SLACK", "GENERIC_WEBHOOK"]),
      display_name: text.max(160),
      destination: z.string().trim().url().max(4_096),
      signing_secret: z.string().trim().max(4_096).optional(),
      trust_delegation_confirmed: z.literal("on"),
    })
    .superRefine((value, context) => {
      if (value.type === "GENERIC_WEBHOOK" && !value.signing_secret) {
        context.addIssue({
          code: "custom",
          path: ["signing_secret"],
          message: "Generic webhooks require a signing secret.",
        });
      }
      if (value.type === "SLACK" && value.signing_secret) {
        context.addIssue({
          code: "custom",
          path: ["signing_secret"],
          message: "Slack incoming webhooks do not use a separate signing secret.",
        });
      }
    })
    .parse(formValues(formData));
  await mutate<NotificationChannel>(
    `/v2/projects/${encodeURIComponent(safeSlug)}/notifications/channels`,
    {
      ...input,
      signing_secret: input.signing_secret || null,
      trust_delegation_confirmed: true,
    },
    randomUUID(),
  );
  revalidatePath(`/projects/${safeSlug}/settings`, "layout");
  redirect(`/projects/${safeSlug}/settings/notifications`);
}

export async function createNotificationRuleAction(
  projectSlug: string,
  formData: FormData,
): Promise<never> {
  const safeSlug = slug.parse(projectSlug);
  const input = z
    .object({
      channel_id: text,
      display_name: text.max(160),
      cooldown_seconds: z.coerce.number().int().min(0).max(86_400),
      attention_types: z.array(
        z.enum([
          "agent_request",
          "run_failure",
          "finding_review",
          "project_complete",
          "stalled_project",
          "notification_failure",
          "preflight_issue",
          "unattended_run",
        ]),
      ),
      severities: z.array(z.enum(["CRITICAL", "HIGH", "MEDIUM", "LOW"])),
    })
    .parse({
      ...formValues(formData),
      attention_types: formData.getAll("attention_types"),
      severities: formData.getAll("severities"),
    });
  await mutate<NotificationRule>(
    `/v2/projects/${encodeURIComponent(safeSlug)}/notifications/rules`,
    input,
    randomUUID(),
  );
  revalidatePath(`/projects/${safeSlug}/settings`, "layout");
  redirect(`/projects/${safeSlug}/settings/notifications`);
}

export async function setNotificationChannelStateAction(
  projectSlug: string,
  channelId: string,
  enabled: boolean,
): Promise<void> {
  const safeSlug = slug.parse(projectSlug);
  await mutate<NotificationChannel>(
    `/v2/projects/${encodeURIComponent(safeSlug)}/notifications/channels/${encodeURIComponent(text.parse(channelId))}/state`,
    { enabled },
    randomUUID(),
  );
  revalidatePath(`/projects/${safeSlug}/settings/notifications`);
}

export async function testNotificationChannelAction(
  projectSlug: string,
  channelId: string,
): Promise<void> {
  const safeSlug = slug.parse(projectSlug);
  await mutate<NotificationTest>(
    `/v2/projects/${encodeURIComponent(safeSlug)}/notifications/channels/${encodeURIComponent(text.parse(channelId))}/test`,
    {},
    randomUUID(),
  );
  revalidatePath(`/projects/${safeSlug}/settings/notifications`);
}
