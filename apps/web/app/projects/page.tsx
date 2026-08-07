import { Add } from "@carbon/icons-react";
import Link from "next/link";

import { ConsoleFrame } from "@/components/console-frame";
import { ProjectGrid } from "@/components/project-grid";
import { listProjects } from "@/lib/limina/server";

export default async function ProjectsPage() {
  const projects = await listProjects();
  return (
    <ConsoleFrame activeNav="projects">
      <div className="lc-pagehead">
        <div className="lc-stack lc-stack--2">
          <p className="tam-eyebrow">Portfolio</p>
          <h1 className="lc-display">Projects</h1>
          <p className="lc-prose lc-prose--muted">Durable missions, evidence state, and the next consequential step.</p>
        </div>
        <Link className="tam-button tam-button--primary" href="/new">
          <Add size={16} aria-hidden /> New project
        </Link>
      </div>
      <ProjectGrid projects={projects.items} />
    </ConsoleFrame>
  );
}
