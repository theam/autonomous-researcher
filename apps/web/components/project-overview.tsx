/**
 * Project overview — the situation, above the fold, in one screen's worth.
 *
 * The one important thing here is the current situation: objective, next step,
 * and blocker. Evidence counts, lifecycle controls and recent activity are
 * deliberately subordinate in type size and position. This is not a dashboard:
 * no charts, no token burn, no run telemetry — those live in Runs.
 *
 * Like the Desk, this component never mutates and never decides authority. It
 * renders exactly the lifecycle actions it is handed. `renderAction` lets the
 * page bind real server actions without forking this file.
 *
 * Server-compatible: no "use client", no hooks, no event handlers.
 */

import type { ReactNode } from "react";

import { Information } from "@carbon/icons-react";

import { HefMark, StateChip } from "@/components/state-marks";
import type { StateRole } from "@/components/state-marks";
import type { DeskAction, DeskActionIntent } from "@/components/attention-desk";

export type OverviewProject = {
  slug: string;
  name: string;
  mission: string;
  runtime: "codex" | "claude-code";
  /** Lifecycle state, e.g. RUNNING, WAITING, PAUSED, COMPLETE. */
  status: string;
  role: "OWNER" | "EDITOR" | "VIEWER" | null;
};

export type OverviewSituation = {
  objective: string;
  nextStep: string;
  /** Empty string when the project is not blocked. */
  blocker: string;
};

export type OverviewCounts = {
  hypotheses: number;
  experiments: number;
  findings: number;
};

export type OverviewActivityEntry = {
  id: string;
  /** Human-readable summary of what happened. */
  label: string;
  /** Who acted — "Limina" for agent-side activity. */
  actorLabel: string;
  timestamp: string;
  timeLabel: string;
};

export type ProjectOverviewProps = {
  project: OverviewProject;
  situation: OverviewSituation;
  counts: OverviewCounts;
  /** Server-derived; render nothing extra when empty. */
  lifecycleActions: DeskAction[];
  recentActivity: OverviewActivityEntry[];
  renderAction?: (action: DeskAction) => ReactNode;
};

const STATUS_ROLE: Record<string, StateRole> = {
  RUNNING: "success",
  COMPLETE: "success",
  WAITING: "warning",
  PAUSED: "warning",
  CREATED: "info",
  STOPPED: "muted",
  ARCHIVED: "muted",
  FAILED: "critical",
};

const RUNTIME_LABEL: Record<OverviewProject["runtime"], string> = {
  codex: "Codex",
  "claude-code": "Claude Code",
};

const INTENT_CLASS: Record<DeskActionIntent, string> = {
  primary: "tam-button--primary",
  neutral: "tam-button--outline",
  critical: "tam-button--critical",
};

function DefaultAction({ action }: { action: DeskAction }) {
  const className = `tam-button tam-button--compact ${
    INTENT_CLASS[action.intent ?? "neutral"]
  }`;
  if (action.href) {
    return (
      <a className={className} href={action.href}>
        {action.label}
      </a>
    );
  }
  return (
    <button
      type="button"
      className={className}
      data-lifecycle-action={action.id}
      aria-disabled="true"
    >
      {action.label}
    </button>
  );
}

function StatusChip({ status }: { status: string }) {
  return (
    <StateChip
      role={STATUS_ROLE[status] ?? "muted"}
      icon={Information}
      label={status}
      description="project state"
    />
  );
}

export function ProjectOverview({
  project,
  situation,
  counts,
  lifecycleActions,
  recentActivity,
  renderAction,
}: ProjectOverviewProps) {
  return (
    <section aria-labelledby="overview-title">
      <div className="lc-pagehead">
        <div className="lc-stack lc-stack--2">
          <span className="tam-eyebrow">Project</span>
          <h1 className="lc-display" id="overview-title">
            {project.name}
          </h1>
          <span className="lc-metaline">
            <StatusChip status={project.status} />
            <span className="lc-meta">{RUNTIME_LABEL[project.runtime]}</span>
            <span className="lc-meta lc-metaline__sep" aria-hidden>
              ·
            </span>
            <span className="lc-meta">{project.slug}</span>
            {project.role ? (
              <>
                <span className="lc-meta lc-metaline__sep" aria-hidden>
                  ·
                </span>
                <span className="lc-meta">
                  Your role: {project.role}
                </span>
              </>
            ) : null}
          </span>
        </div>

        {lifecycleActions.length > 0 ? (
          <div className="lc-actions">
            {lifecycleActions.map((action) =>
              renderAction ? (
                <span key={action.id}>{renderAction(action)}</span>
              ) : (
                <DefaultAction key={action.id} action={action} />
              ),
            )}
          </div>
        ) : null}
      </div>

      <div className="lc-grid">
        {/* The one important thing. */}
        <div className="lc-col-5 lc-stack lc-stack--5">
          <div className="lc-field">
            <span className="tam-eyebrow">Current objective</span>
            <p className="lc-prose lc-prose--lead">
              {situation.objective || "No objective recorded yet."}
            </p>
          </div>

          <div className="lc-field">
            <span className="tam-eyebrow">Next step</span>
            <p className="lc-prose">
              {situation.nextStep || "No next step recorded yet."}
            </p>
          </div>

          {situation.blocker ? (
            <div className="lc-blocker lc-field">
              <span className="tam-eyebrow">Blocker</span>
              <p className="lc-prose">{situation.blocker}</p>
            </div>
          ) : null}

          <div className="lc-field">
            <span className="tam-eyebrow">Mission</span>
            <p className="lc-prose lc-prose--muted">{project.mission}</p>
          </div>
        </div>

        <div className="lc-col-3 lc-stack lc-stack--5">
          <section className="lc-panel" aria-labelledby="overview-evidence">
            <h2 className="lc-display lc-display--sm" id="overview-evidence">
              Evidence
            </h2>
            <hr className="lc-divider" />
            <div className="lc-counts">
              <span className="lc-count">
                <span className="lc-count__value">{counts.hypotheses}</span>
                <HefMark kind="H" label="Hypotheses" />
              </span>
              <span className="lc-count">
                <span className="lc-count__value">{counts.experiments}</span>
                <HefMark kind="E" label="Experiments" />
              </span>
              <span className="lc-count">
                <span className="lc-count__value">{counts.findings}</span>
                <HefMark kind="F" label="Findings" filled />
              </span>
            </div>
          </section>

          <section className="lc-panel" aria-labelledby="overview-activity">
            <h2 className="lc-display lc-display--sm" id="overview-activity">
              Recent activity
            </h2>
            <hr className="lc-divider" />
            {recentActivity.length === 0 ? (
              <p className="lc-meta">No activity recorded yet.</p>
            ) : (
              <ol>
                {recentActivity.map((entry) => (
                  <li className="lc-activity__item" key={entry.id}>
                    <span className="lc-prose">{entry.label}</span>
                    <span className="lc-metaline">
                      <span className="lc-meta">{entry.actorLabel}</span>
                      <span className="lc-meta lc-metaline__sep" aria-hidden>
                        ·
                      </span>
                      <time className="lc-meta" dateTime={entry.timestamp}>
                        {entry.timeLabel}
                      </time>
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>
      </div>
    </section>
  );
}

export default ProjectOverview;
