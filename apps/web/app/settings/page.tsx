import Link from "next/link";

import { signOutAction } from "@/app/actions";
import { ConsoleFrame } from "@/components/console-frame";
import { PendingButton } from "@/components/pending-button";
import { env } from "@/lib/env";
import { getMe } from "@/lib/limina/server";

export default async function SettingsPage() {
  const me = await getMe();
  return (
    <ConsoleFrame activeNav="projects">
      <section className="lc-panel lc-stack lc-stack--4">
        <p className="tam-eyebrow">Profile</p>
        <h1 className="lc-display">{me.display_name}</h1>
        <p className="lc-meta">{me.email ?? me.subject} · {me.auth_mode}</p>
        <p className="lc-prose">
          Capabilities are derived by Limina and never inferred by the Console.
        </p>
        <div className="lc-action-row">
          {me.capabilities.includes("instance:admin") ? (
            <Link className="tam-button tam-button--outline" href="/settings/health">
              Instance health
            </Link>
          ) : null}
          {env.LIMINA_UI_AUTH_MODE === "workos" ? (
            <form action={signOutAction}>
              <PendingButton kind="secondary" pendingLabel="Signing out…">
                Sign out
              </PendingButton>
            </form>
          ) : null}
        </div>
      </section>
    </ConsoleFrame>
  );
}
