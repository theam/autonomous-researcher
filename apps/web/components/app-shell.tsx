/**
 * Console shell: a persistent workspace rail, project-level navigation, main
 * landmark, operator identity, and the mandatory TAM footer signature.
 *
 * Server-compatible: no hooks and no authority inference. Pages supply the
 * active workspace/project state explicitly; the shell only renders it.
 */

import type { ReactNode } from "react";

import {
  Activity,
  Add,
  Document,
  Folders,
  Home,
  ListChecked,
  Play,
  Settings as SettingsIcon,
} from "@carbon/icons-react";
import type { CarbonIconType } from "@carbon/icons-react";
import Link from "next/link";

import { LiminaMark } from "@/components/limina-mark";

export type ShellNavKey = "today" | "projects" | "new" | "project" | "account";
export type ProjectSection = "overview" | "knowledge" | "runs" | "live" | "settings";

export type ShellOperator = {
  name: string;
  email?: string | null;
  authModeLabel: string;
  organizationLabel?: string | null;
};

export type ShellCurrentProject = {
  slug: string;
  name: string;
};

export type AppShellProps = {
  operator: ShellOperator;
  activeNav: ShellNavKey;
  activeProjectSection?: ProjectSection | null;
  currentProject?: ShellCurrentProject | null;
  children: ReactNode;
};

type ProjectNavItem = {
  id: ProjectSection;
  label: string;
  suffix: string;
  icon: CarbonIconType;
};

const TAM_URL = "https://theagilemonkeys.com";

const projectNavigation: ProjectNavItem[] = [
  { id: "overview", label: "Overview", suffix: "", icon: Home },
  { id: "knowledge", label: "Knowledge", suffix: "/knowledge", icon: Document },
  { id: "runs", label: "Runs", suffix: "/runs", icon: Play },
  { id: "live", label: "Live", suffix: "/live", icon: Activity },
  { id: "settings", label: "Settings", suffix: "/settings", icon: SettingsIcon },
];

function ProjectNavigation({
  activeProjectSection,
  currentProject,
}: {
  activeProjectSection?: ProjectSection | null;
  currentProject: ShellCurrentProject;
}) {
  const base = `/projects/${encodeURIComponent(currentProject.slug)}`;
  return (
    <div className="lc-sidebar__project">
      <p className="lc-sidebar__label">Project</p>
      <Link className="lc-sidebar__project-name" href={base}>
        <Folders size={16} aria-hidden focusable="false" />
        <span>{currentProject.name}</span>
      </Link>
      <nav className="lc-sidebar__nav lc-sidebar__nav--nested" aria-label="Project">
        {projectNavigation.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              className="lc-sidebar__link"
              href={`${base}${item.suffix}`}
              aria-current={activeProjectSection === item.id ? "page" : undefined}
              key={item.id}
            >
              <Icon size={16} aria-hidden focusable="false" />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}

function WorkspaceNavigation({ activeNav }: { activeNav: ShellNavKey }) {
  return (
    <nav className="lc-sidebar__nav" aria-label="Primary">
      <Link
        className="lc-sidebar__link"
        href="/"
        aria-current={activeNav === "today" ? "page" : undefined}
      >
        <ListChecked size={16} aria-hidden focusable="false" />
        <span>Today</span>
      </Link>
      <Link
        className="lc-sidebar__link"
        href="/projects"
        aria-current={activeNav === "projects" ? "page" : undefined}
      >
        <Folders size={16} aria-hidden focusable="false" />
        <span>Projects</span>
      </Link>
      <Link
        className="lc-sidebar__link"
        href="/new"
        aria-current={activeNav === "new" ? "page" : undefined}
      >
        <Add size={16} aria-hidden focusable="false" />
        <span>New Project</span>
      </Link>
    </nav>
  );
}

function OperatorLink({ operator, active }: { operator: ShellOperator; active: boolean }) {
  return (
    <Link
      className="lc-operator"
      href="/settings"
      aria-current={active ? "page" : undefined}
    >
      <span className="lc-operator__avatar" aria-hidden>
        {operator.name.slice(0, 1).toUpperCase()}
      </span>
      <span className="lc-operator__copy">
        <span className="lc-meta lc-meta--strong">{operator.name}</span>
        <span className="lc-meta">
          {operator.organizationLabel
            ? `${operator.organizationLabel} · ${operator.authModeLabel}`
            : operator.authModeLabel}
        </span>
      </span>
    </Link>
  );
}

export function AppShell({
  operator,
  activeNav,
  activeProjectSection = null,
  currentProject = null,
  children,
}: AppShellProps) {
  const showProjectNavigation = activeNav === "project" && currentProject;

  return (
    <div className="lc-shell">
      <a className="lc-skip-link" href="#main">
        Skip to main content
      </a>

      <aside className="lc-sidebar">
        <div className="lc-sidebar__brand-row">
          <Link className="lc-brand" href="/">
            <LiminaMark size={20} title="Limina Console" />
            <span className="lc-brand__word">Limina</span>
          </Link>
          <span className="lc-sidebar__product">Console</span>
        </div>

        <details className="lc-mobile-navigation">
          <summary className="tam-button tam-button--outline">Navigation</summary>
          <div className="lc-mobile-navigation__body">
            <WorkspaceNavigation activeNav={activeNav} />
            {showProjectNavigation ? (
              <ProjectNavigation
                activeProjectSection={activeProjectSection}
                currentProject={currentProject}
              />
            ) : null}
          </div>
        </details>

        <div className="lc-sidebar__desktop-body">
          <WorkspaceNavigation activeNav={activeNav} />
          {showProjectNavigation ? (
            <ProjectNavigation
              activeProjectSection={activeProjectSection}
              currentProject={currentProject}
            />
          ) : null}
        </div>

        <div className="lc-sidebar__bottom">
          <OperatorLink operator={operator} active={activeNav === "account"} />
        </div>
      </aside>

      <div className="lc-workspace">
        <main className="lc-main" id="main" tabIndex={-1}>
          <div className="lc-content">{children}</div>
        </main>

        <footer className="lc-footer">
          <div className="lc-content lc-footer__inner">
            <span className="lc-footer__signature">
              <LiminaMark size={16} />
              <span>Limina Console</span>
            </span>
            <span className="lc-footer__signature">
              <a
                className="lc-footer__link"
                href={TAM_URL}
                target="_blank"
                rel="noreferrer noopener"
              >
                An initiative by The Agile Monkeys
              </a>
            </span>
          </div>
        </footer>
      </div>
    </div>
  );
}

export default AppShell;
