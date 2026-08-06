/**
 * Console shell: skip link, header, primary navigation, operator identity,
 * main landmark, and the mandatory TAM footer signature.
 *
 * Server-compatible: no "use client", no hooks, no event handlers. Every value
 * is supplied explicitly by the page, including the auth mode — the shell never
 * infers identity or authority, and never decides what a user may do.
 */

import type { ReactNode } from "react";

import Link from "next/link";
import { Folders, ListChecked } from "@carbon/icons-react";

import { LiminaMark } from "@/components/limina-mark";

export type ShellNavKey = "today" | "projects" | "project";

export type ShellOperator = {
  /** Display name, server-derived. */
  name: string;
  email?: string | null;
  /** Human-readable auth mode, e.g. "WorkOS" or "Local dev". */
  authModeLabel: string;
  /** Optional organization name, shown only when supplied. */
  organizationLabel?: string | null;
};

export type ShellCurrentProject = {
  slug: string;
  name: string;
};

export type AppShellProps = {
  operator: ShellOperator;
  activeNav: ShellNavKey;
  /** Shown as a third nav affordance only while a project is in scope. */
  currentProject?: ShellCurrentProject | null;
  children: ReactNode;
};

const TAM_URL = "https://theagilemonkeys.com";

export function AppShell({
  operator,
  activeNav,
  currentProject = null,
  children,
}: AppShellProps) {
  return (
    <div className="lc-shell">
      <a className="lc-skip-link" href="#main">
        Skip to main content
      </a>

      <header className="lc-header">
        <div className="lc-bounds lc-header__inner">
          <Link className="lc-brand" href="/">
            <LiminaMark size={20} title="Limina Console" />
            <span className="lc-brand__word">Limina</span>
          </Link>

          <nav className="lc-nav" aria-label="Primary">
            <Link
              className="lc-nav__link"
              href="/"
              aria-current={activeNav === "today" ? "page" : undefined}
            >
              <ListChecked size={16} aria-hidden focusable="false" />
              Today
            </Link>
            <Link
              className="lc-nav__link"
              href="/projects"
              aria-current={activeNav === "projects" ? "page" : undefined}
            >
              <Folders size={16} aria-hidden focusable="false" />
              Projects
            </Link>
            {currentProject ? (
              <Link
                className="lc-nav__link"
                href={`/projects/${currentProject.slug}`}
                aria-current={activeNav === "project" ? "page" : undefined}
              >
                {currentProject.name}
              </Link>
            ) : null}
          </nav>

          <span className="lc-header__spacer" />

          <Link className="lc-operator" href="/settings" aria-label="Open operator profile">
            <span className="lc-meta lc-meta--strong">{operator.name}</span>
            <span className="lc-meta">
              {operator.organizationLabel
                ? `${operator.organizationLabel} · ${operator.authModeLabel}`
                : operator.authModeLabel}
            </span>
          </Link>
        </div>
      </header>

      <main className="lc-main" id="main" tabIndex={-1}>
        <div className="lc-bounds">{children}</div>
      </main>

      <footer className="lc-footer">
        <div className="lc-bounds lc-footer__inner">
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
  );
}

export default AppShell;
