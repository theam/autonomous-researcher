import type { ReactNode } from "react";

import Link from "next/link";

import { ConsoleFrame } from "@/components/console-frame";

export type ProjectSettingsSection =
  | "general"
  | "sources"
  | "environment"
  | "team"
  | "notifications";

type Props = {
  slug: string;
  projectName: string;
  active: ProjectSettingsSection;
  children: ReactNode;
};

const sections: Array<{
  id: ProjectSettingsSection;
  label: string;
  suffix: string;
}> = [
  { id: "general", label: "General", suffix: "" },
  { id: "sources", label: "Sources", suffix: "/sources" },
  { id: "environment", label: "Environment", suffix: "/environment" },
  { id: "team", label: "Team", suffix: "/team" },
  { id: "notifications", label: "Notifications", suffix: "/notifications" },
];

export function ProjectSettingsFrame({ slug, projectName, active, children }: Props) {
  const base = `/projects/${encodeURIComponent(slug)}/settings`;
  return (
    <ConsoleFrame
      activeNav="project"
      activeProjectSection="settings"
      currentProject={{ slug, name: projectName }}
    >
      <div className="lc-pagehead lc-pagehead--settings">
        <div className="lc-stack lc-stack--2">
          <p className="tam-eyebrow">Project Administration</p>
          <h1 className="lc-display">Settings</h1>
          <p className="lc-prose lc-prose--muted">
            Manage the project configuration that Limina uses while it runs.
          </p>
        </div>
      </div>

      <div className="lc-settings-layout">
        <nav className="lc-settings-index" aria-label="Settings">
          {sections.map((section) => (
            <Link
              className="lc-settings-index__link"
              href={`${base}${section.suffix}`}
              aria-current={active === section.id ? "page" : undefined}
              key={section.id}
            >
              {section.label}
            </Link>
          ))}
        </nav>
        <div className="lc-settings-content">{children}</div>
      </div>
    </ConsoleFrame>
  );
}
