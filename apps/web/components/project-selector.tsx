"use client";

import { useEffect, useRef, useState } from "react";

import { Add, Checkmark, ChevronDown, Folders, Search } from "@carbon/icons-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

export type ProjectSelectorOption = {
  slug: string;
  name: string;
  status: string;
};

type Props = {
  projects: ProjectSelectorOption[];
  totalProjects: number;
  currentProject: { slug: string; name: string } | null;
  canCreateProject: boolean;
};

export function projectDestination(slug: string, pathname: string): string {
  const projectSection = pathname.match(
    /^\/projects\/[^/]+\/(knowledge|runs|live|settings)(?:\/|$)/,
  )?.[1];
  const base = `/projects/${encodeURIComponent(slug)}`;
  return projectSection ? `${base}/${projectSection}` : base;
}

export function ProjectSelector({
  projects,
  totalProjects,
  currentProject,
  canCreateProject,
}: Props) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const openedWithKeyboardRef = useRef(false);

  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filteredProjects = projects
    .filter((project) => {
      if (!normalizedQuery) return true;
      return `${project.name} ${project.slug}`.toLocaleLowerCase().includes(normalizedQuery);
    });
  filteredProjects.sort((left, right) => {
      if (left.slug === currentProject?.slug) return -1;
      if (right.slug === currentProject?.slug) return 1;
      return left.name.localeCompare(right.name);
  });

  function close({ restoreFocus = false } = {}) {
    setOpen(false);
    setQuery("");
    if (restoreFocus) triggerRef.current?.focus();
  }

  function focusProjectOption(position: "first" | "last") {
    const options = panelRef.current?.querySelectorAll<HTMLAnchorElement>(
      ".lc-project-selector__option",
    );
    const option = position === "first" ? options?.[0] : options?.[options.length - 1];
    option?.focus();
  }

  function onPanelKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (!(event.target instanceof HTMLAnchorElement)) return;
    const options = Array.from(
      event.currentTarget.querySelectorAll<HTMLAnchorElement>(
        ".lc-project-selector__option",
      ),
    );
    const currentIndex = options.indexOf(event.target);
    if (currentIndex < 0) return;

    let nextIndex: number | null = null;
    if (event.key === "ArrowDown") nextIndex = Math.min(currentIndex + 1, options.length - 1);
    if (event.key === "ArrowUp") nextIndex = Math.max(currentIndex - 1, 0);
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = options.length - 1;
    if (nextIndex !== null) {
      event.preventDefault();
      options[nextIndex]?.focus();
    }
  }

  useEffect(() => {
    if (!open) return;

    const focusFrame = window.requestAnimationFrame(() => {
      if (
        openedWithKeyboardRef.current ||
        window.matchMedia("(pointer: fine)").matches
      ) {
        searchRef.current?.focus();
      }
    });
    function onPointerDown(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) close();
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        close({ restoreFocus: true });
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const triggerLabel = currentProject?.name ?? "All Projects";

  return (
    <div
      className="lc-project-selector"
      ref={containerRef}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) close();
      }}
    >
      <button
        className="lc-project-selector__trigger"
        type="button"
        ref={triggerRef}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? "project-selector-panel" : undefined}
        aria-label={
          currentProject
            ? `Switch project, current project: ${currentProject.name}`
            : "Select a project"
        }
        onPointerDown={() => {
          openedWithKeyboardRef.current = false;
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            openedWithKeyboardRef.current = true;
          }
        }}
        onClick={(event) => {
          if (event.detail === 0) openedWithKeyboardRef.current = true;
          setOpen((value) => !value);
        }}
      >
        <Folders size={16} aria-hidden focusable="false" />
        <span title={triggerLabel}>{triggerLabel}</span>
        <ChevronDown size={16} aria-hidden focusable="false" />
      </button>

      {open ? (
        <div
          className="lc-project-selector__panel"
          id="project-selector-panel"
          ref={panelRef}
          role="dialog"
          aria-label="Select project"
          onKeyDown={onPanelKeyDown}
        >
          <div className="lc-project-selector__search">
            <Search size={16} aria-hidden focusable="false" />
            <input
              ref={searchRef}
              type="search"
              name="project_query"
              aria-label="Search projects"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "ArrowDown") {
                  event.preventDefault();
                  focusProjectOption("first");
                }
                if (event.key === "ArrowUp") {
                  event.preventDefault();
                  focusProjectOption("last");
                }
              }}
              placeholder="Find project…"
              autoComplete="off"
              spellCheck={false}
            />
            <kbd>Esc</kbd>
          </div>

          <nav className="lc-project-selector__list" aria-label="Available projects">
            {!normalizedQuery ? (
              <Link
                className="lc-project-selector__option"
                href="/projects"
                aria-current={pathname === "/projects" ? "page" : undefined}
                onClick={() => close()}
              >
                <Folders size={16} aria-hidden focusable="false" />
                <span>
                  <strong>All Projects</strong>
                  <small>View the complete portfolio</small>
                </span>
                {pathname === "/projects" ? (
                  <Checkmark size={16} aria-hidden focusable="false" />
                ) : null}
              </Link>
            ) : null}

            {filteredProjects.map((project) => {
              const current = project.slug === currentProject?.slug;
              return (
                <Link
                  className="lc-project-selector__option"
                  href={projectDestination(project.slug, pathname)}
                  aria-current={current ? "location" : undefined}
                  onClick={() => close()}
                  key={project.slug}
                  title={project.name}
                >
                  <span className="lc-project-selector__initial" aria-hidden>
                    {project.name.slice(0, 1).toUpperCase()}
                  </span>
                  <span>
                    <strong>{project.name}</strong>
                    <small>
                      {project.slug} · {project.status}
                    </small>
                  </span>
                  {current ? <Checkmark size={16} aria-hidden focusable="false" /> : null}
                </Link>
              );
            })}

            {filteredProjects.length === 0 ? (
              <p className="lc-project-selector__empty">
                {normalizedQuery
                  ? "No projects match this search."
                  : "No projects are available."}
              </p>
            ) : null}

            {totalProjects > projects.length ? (
              <p className="lc-project-selector__limit">
                Showing the first {projects.length} of {totalProjects} projects.
              </p>
            ) : null}
          </nav>

          {canCreateProject ? (
            <div className="lc-project-selector__footer">
              <Link
                className="lc-project-selector__option"
                href="/new"
                onClick={() => close()}
              >
                <Add size={16} aria-hidden focusable="false" />
                <span>
                  <strong>Create Project</strong>
                  <small>Start a new durable research brief</small>
                </span>
              </Link>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
