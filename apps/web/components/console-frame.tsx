import type { ReactNode } from "react";

import {
  AppShell,
  type ProjectSection,
  type ShellCurrentProject,
  type ShellNavKey,
} from "@/components/app-shell";
import { getMe, listProjects } from "@/lib/limina/server";

type ConsoleFrameProps = {
  activeNav: ShellNavKey;
  activeProjectSection?: ProjectSection | null;
  currentProject?: ShellCurrentProject | null;
  children: ReactNode;
};

const authLabels: Record<string, string> = {
  local: "Local token",
  "dev-jwt": "Local development",
  oidc: "OIDC",
  workos: "WorkOS",
};

export async function ConsoleFrame({
  activeNav,
  activeProjectSection = null,
  currentProject = null,
  children,
}: ConsoleFrameProps) {
  const [me, projects] = await Promise.all([getMe(), listProjects()]);
  return (
    <AppShell
      activeNav={activeNav}
      activeProjectSection={activeProjectSection}
      currentProject={currentProject}
      projects={projects.items.map(({ slug, name, status }) => ({ slug, name, status }))}
      totalProjects={projects.total}
      operator={{
        name: me.display_name,
        email: me.email,
        authModeLabel: authLabels[me.auth_mode] ?? me.auth_mode,
        organizationLabel: me.organization?.name ?? me.organization?.id ?? null,
      }}
    >
      {children}
    </AppShell>
  );
}
