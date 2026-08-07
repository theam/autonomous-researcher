import Link from "next/link";

import { lifecycleAction } from "@/app/actions";
import { ConsoleFrame } from "@/components/console-frame";
import { PendingButton } from "@/components/pending-button";
import { ProjectOverview } from "@/components/project-overview";
import type { DeskAction } from "@/components/attention-desk";
import { formatRelative } from "@/lib/format";
import { getEvents, getPreflight, getProjectStatus } from "@/lib/limina/server";

type PageProps = { params: Promise<{ slug: string }> };

function total(counts: Record<string, number> | undefined): number {
  return Object.values(counts ?? {}).reduce((sum, value) => sum + value, 0);
}

function preflightRemedy(slug: string, checkName: string): string | null {
  const settings = `/projects/${encodeURIComponent(slug)}/settings`;
  if (["mission", "success_criteria", "runtime"].includes(checkName)) return settings;
  if (checkName === "sources") return `${settings}/sources`;
  return null;
}

export default async function ProjectOverviewPage({ params }: PageProps) {
  const { slug } = await params;
  const [status, events, preflight] = await Promise.all([
    getProjectStatus(slug),
    getEvents(slug),
    getPreflight(slug),
  ]);
  const project = status.project;
  const actions: DeskAction[] = project.allowed_actions
    .filter((action) => action !== "start" || preflight.ready)
    .map((action) => ({
      id: action,
      label: action.replace(/^./, (value) => value.toUpperCase()),
      intent:
        action === "start" || action === "resume"
          ? "primary"
          : action === "archive"
            ? "critical"
            : "neutral",
    }));

  function renderLifecycle(action: DeskAction) {
    if (action.id === "start" || action.id === "archive") {
      const starting = action.id === "start";
      return (
        <details className="lc-action-confirm">
          <summary
            className={`tam-button ${starting ? "tam-button--primary" : "tam-button--critical"}`}
          >
            {action.label}
          </summary>
          <form
            className="lc-action-confirm__body lc-stack lc-stack--3"
            action={lifecycleAction.bind(null, slug, action.id)}
          >
            <p className="lc-prose">
              {starting
                ? "Starting fixes the mission, success criteria, context, and executor for this project’s evidence history."
                : "Archiving removes this project from the active portfolio. Its evidence remains durable and readable."}
            </p>
            <label className="lc-confirm">
              <input type="checkbox" required /> I understand and want to {action.id} this project.
            </label>
            <PendingButton kind={starting ? "primary" : "critical"}>
              Confirm {action.id}
            </PendingButton>
          </form>
        </details>
      );
    }
    return (
      <form action={lifecycleAction.bind(null, slug, action.id)}>
        <PendingButton kind={action.intent === "critical" ? "critical" : action.intent === "primary" ? "primary" : "secondary"}>
          {action.label}
        </PendingButton>
      </form>
    );
  }

  return (
    <ConsoleFrame
      activeNav="project"
      activeProjectSection="overview"
      currentProject={{ slug, name: project.name }}
    >
      {!preflight.ready && project.status === "CREATED" ? (
        <section className="lc-preflight" aria-labelledby="preflight-title">
          <h2 className="tam-eyebrow" id="preflight-title">Preflight needs attention</h2>
          <ul>
            {preflight.checks
              .filter((check) => check.status === "FAIL")
              .map((check) => {
                const remedy = preflightRemedy(slug, check.name);
                return (
                  <li key={check.name}>
                    <span>
                      <strong>{check.name}</strong> — {check.detail}
                    </span>
                    {remedy ? (
                      <Link className="lc-text-link" href={remedy}>
                        Open settings
                      </Link>
                    ) : null}
                  </li>
                );
              })}
          </ul>
        </section>
      ) : null}
      <ProjectOverview
        project={{ slug, name: project.name, mission: project.mission, runtime: project.runtime, status: project.status, role: project.role }}
        situation={{ objective: project.current_objective, nextStep: project.next_step, blocker: project.blocker === "None" ? "" : project.blocker }}
        counts={{ hypotheses: total(status.knowledge.H), experiments: total(status.knowledge.E), findings: total(status.knowledge.F) }}
        lifecycleActions={actions}
        recentActivity={events.events.slice(-8).reverse().map((event) => ({ id: String(event.sequence), label: String(event.detail.summary ?? event.detail.status ?? event.type.replaceAll(".", " ")), actorLabel: event.actor, timestamp: event.created_at, timeLabel: formatRelative(event.created_at) }))}
        renderAction={renderLifecycle}
      />
    </ConsoleFrame>
  );
}
