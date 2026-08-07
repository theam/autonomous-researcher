import type { ReactNode } from "react";

import {
  AppShell,
  type ProjectSection,
  type ShellCurrentProject,
  type ShellNavKey,
} from "@/components/app-shell";
import { getMe } from "@/lib/limina/server";

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
  const me = await getMe();
  return (
    <AppShell
      activeNav={activeNav}
      activeProjectSection={activeProjectSection}
      currentProject={currentProject}
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
