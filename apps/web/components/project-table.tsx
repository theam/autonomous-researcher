import { ArrowRight, CheckmarkFilled, ErrorFilled, Pause, Time } from "@carbon/icons-react";
import Link from "next/link";

import { formatRelative } from "@/lib/format";
import type { Project } from "@/lib/limina/types";

type ProjectTableProps = { projects: Project[] };

function StatusIcon({ status }: { status: string }) {
  if (status === "COMPLETE") return <CheckmarkFilled size={16} aria-hidden />;
  if (status === "FAILED") return <ErrorFilled size={16} aria-hidden />;
  if (status === "PAUSED" || status === "WAITING") return <Pause size={16} aria-hidden />;
  return <Time size={16} aria-hidden />;
}

export function ProjectTable({ projects }: ProjectTableProps) {
  if (projects.length === 0) {
    return (
      <div className="lc-panel lc-empty">
        <p className="lc-display lc-display--sm">No projects yet</p>
        <p className="lc-prose lc-prose--muted">Create a research brief to start the first durable investigation.</p>
        <Link className="tam-button tam-button--primary" href="/new">New project</Link>
      </div>
    );
  }
  return (
    <div className="lc-table-wrap">
      <table className="lc-table">
        <caption className="lc-visually-hidden">Projects visible to you</caption>
        <thead>
          <tr>
            <th scope="col">Project</th>
            <th scope="col">State</th>
            <th scope="col">Current objective</th>
            <th scope="col">Runtime</th>
            <th scope="col">Role</th>
            <th scope="col">Updated</th>
            <th scope="col"><span className="lc-visually-hidden">Open</span></th>
          </tr>
        </thead>
        <tbody>
          {projects.map((project) => (
            <tr key={project.slug}>
              <th scope="row">
                <Link href={`/projects/${encodeURIComponent(project.slug)}`}>{project.name}</Link>
                <span className="lc-meta">{project.slug}</span>
              </th>
              <td>
                <span className="lc-state-inline">
                  <StatusIcon status={project.status} /> {project.status}
                </span>
              </td>
              <td className="lc-prose-cell">{project.current_objective}</td>
              <td>{project.runtime}</td>
              <td>{project.role ?? "—"}</td>
              <td><time dateTime={project.updated_at}>{formatRelative(project.updated_at)}</time></td>
              <td>
                <Link aria-label={`Open ${project.name}`} href={`/projects/${encodeURIComponent(project.slug)}`}>
                  <ArrowRight size={20} aria-hidden />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
