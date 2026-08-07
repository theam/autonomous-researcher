import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { ProjectSelector, projectDestination } from "@/components/project-selector";

vi.mock("next/navigation", () => ({ usePathname: () => "/projects" }));

beforeAll(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
});

afterEach(cleanup);

describe("projectDestination", () => {
  it("preserves the current top-level project section", () => {
    expect(
      projectDestination("second-project", "/projects/first-project/knowledge/F001"),
    ).toBe("/projects/second-project/knowledge");
    expect(
      projectDestination("second-project", "/projects/first-project/settings/environment"),
    ).toBe("/projects/second-project/settings");
  });

  it("opens overview from global and overview routes", () => {
    expect(projectDestination("second-project", "/projects")).toBe(
      "/projects/second-project",
    );
    expect(projectDestination("second-project", "/projects/first-project")).toBe(
      "/projects/second-project",
    );
  });
});

describe("ProjectSelector states", () => {
  it("explains an empty project list", () => {
    render(
      <ProjectSelector
        projects={[]}
        totalProjects={0}
        currentProject={null}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Select a project" }));
    expect(screen.getByText("No projects are available.")).toBeTruthy();
  });

  it("filters by slug and exposes a no-match state", () => {
    render(
      <ProjectSelector
        projects={[{ slug: "retrieval-lab", name: "Retrieval Lab", status: "ACTIVE" }]}
        totalProjects={1}
        currentProject={null}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Select a project" }));
    const search = screen.getByRole("searchbox", { name: "Search projects" });
    fireEvent.change(search, { target: { value: "retrieval-lab" } });
    expect(screen.getByRole("link", { name: /Retrieval Lab/ })).toBeTruthy();
    fireEvent.change(search, { target: { value: "missing" } });
    expect(screen.getByText("No projects match this search.")).toBeTruthy();
  });

  it("makes a truncated project list explicit", () => {
    render(
      <ProjectSelector
        projects={[{ slug: "first", name: "First", status: "ACTIVE" }]}
        totalProjects={240}
        currentProject={null}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Select a project" }));
    expect(screen.getByText("Showing the first 1 of 240 projects.")).toBeTruthy();
  });
});
