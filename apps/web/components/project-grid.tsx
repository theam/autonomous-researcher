import {
  CheckmarkFilled,
  ErrorFilled,
  Pause,
  Time,
} from "@carbon/icons-react";
import Link from "next/link";

import { formatRelative } from "@/lib/format";
import type { Project } from "@/lib/limina/types";

type ProjectGridProps = { projects: Project[] };

function StatusIcon({ status }: { status: string }) {
  if (status === "COMPLETE") return <CheckmarkFilled size={16} aria-hidden />;
  if (status === "FAILED") return <ErrorFilled size={16} aria-hidden />;
  if (status === "PAUSED" || status === "WAITING") return <Pause size={16} aria-hidden />;
  return <Time size={16} aria-hidden />;
}

export function ProjectGrid({ projects }: ProjectGridProps) {
  if (projects.length === 0) {
    return (
      <div className="lc-panel lc-empty">
        <p className="lc-display lc-display--sm">No projects yet</p>
        <p className="lc-prose lc-prose--muted">
          Create a research brief to start the first durable investigation.
        </p>
      </div>
    );
  }

  return (
    <ul className="lc-project-grid" aria-label="Projects visible to you">
      {projects.map((project) => (
        <li key={project.slug}>
          <Link
            className="lc-project-card"
            href={`/projects/${encodeURIComponent(project.slug)}`}
            aria-label={`Open ${project.name}`}
          >
            <span className="lc-project-card__head">
              <span className="lc-project-card__initial" aria-hidden>
                {project.name.slice(0, 1).toUpperCase()}
              </span>
              <span className="lc-project-card__identity">
                <strong>{project.name}</strong>
                <span>{project.slug}</span>
              </span>
              <span
                className="lc-project-card__status"
                data-status={project.status}
                role="img"
                aria-label={`Status: ${project.status.toLocaleLowerCase()}`}
                title={project.status.toLocaleLowerCase()}
              >
                <StatusIcon status={project.status} />
              </span>
            </span>

            <span className="lc-project-card__objective">
              {project.current_objective || project.mission}
            </span>

            <span className="lc-project-card__meta">
              <span>{project.runtime}</span>
              <span aria-hidden>·</span>
              <span>{project.role?.toLocaleLowerCase() ?? "no role"}</span>
              <span aria-hidden>·</span>
              <time dateTime={project.updated_at}>{formatRelative(project.updated_at)}</time>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
