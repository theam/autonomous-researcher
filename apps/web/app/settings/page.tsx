import Link from "next/link";

import { signOutAction } from "@/app/actions";
import { ConsoleFrame } from "@/components/console-frame";
import { PendingButton } from "@/components/pending-button";
import { SettingsSection } from "@/components/settings-section";
import { env } from "@/lib/env";
import { getMe } from "@/lib/limina/server";

export default async function SettingsPage() {
  const me = await getMe();
  return (
    <ConsoleFrame activeNav="account">
      <div className="lc-pagehead lc-pagehead--settings">
        <div className="lc-stack lc-stack--2">
          <p className="tam-eyebrow">Account</p>
          <h1 className="lc-display">Operator settings</h1>
          <p className="lc-prose lc-prose--muted">
            Your identity and instance-level access in this Limina deployment.
          </p>
        </div>
      </div>

      <div className="lc-settings-content lc-settings-content--standalone">
        <SettingsSection
          id="profile"
          title="Profile"
          description="Identity comes from the configured authentication provider."
          action={
            me.capabilities.includes("instance:admin") ? (
              <Link className="tam-button tam-button--outline" href="/settings/health">
                View instance health
              </Link>
            ) : null
          }
        >
          <dl className="lc-definition-list">
            <div className="lc-definition-row">
              <dt>Name</dt>
              <dd>{me.display_name}</dd>
            </div>
            <div className="lc-definition-row">
              <dt>Email</dt>
              <dd>{me.email ?? me.subject}</dd>
            </div>
            <div className="lc-definition-row">
              <dt>Authentication</dt>
              <dd className="lc-meta lc-meta--strong">{me.auth_mode}</dd>
            </div>
          </dl>
        </SettingsSection>

        <SettingsSection
          id="access"
          title="Access"
          description="Limina derives these capabilities server-side; the Console never invents permissions."
        >
          <p className="lc-meta lc-meta--strong">{me.capabilities.join(" · ")}</p>
        </SettingsSection>

        {env.LIMINA_UI_AUTH_MODE === "workos" ? (
          <SettingsSection
            id="session"
            title="Session"
            description="End the current WorkOS session on this device."
            action={
              <form action={signOutAction}>
                <PendingButton kind="secondary" pendingLabel="Signing out…">
                  Sign out
                </PendingButton>
              </form>
            }
          >
            <p className="lc-meta">Signing out does not stop active projects.</p>
          </SettingsSection>
        ) : null}
      </div>
    </ConsoleFrame>
  );
}
