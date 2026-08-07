import { ConsoleFrame } from "@/components/console-frame";
import { SettingsSection } from "@/components/settings-section";
import { StreamHealth } from "@/components/stream-health";
import { getMe, getRuntimeHealth } from "@/lib/limina/server";

export default async function HealthPage() {
  const [health, me] = await Promise.all([getRuntimeHealth(), getMe()]);
  return (
    <ConsoleFrame activeNav="account">
      <div className="lc-pagehead lc-pagehead--settings">
        <div className="lc-stack lc-stack--2">
          <p className="tam-eyebrow">Instance administration</p>
          <h1 className="lc-display">Health</h1>
          <p className="lc-prose lc-prose--muted">
            Runtime availability and the authorization boundary for this deployment.
          </p>
        </div>
        <StreamHealth />
      </div>

      <div className="lc-settings-content lc-settings-content--standalone">
        <SettingsSection
          id="runtime-api"
          title="Runtime API"
          description="Health reported by the canonical Limina runtime."
        >
          <div className="lc-settings-row">
            <span className="lc-chip" data-role={health.ok ? "success" : "critical"}>
              {health.ok ? "Healthy" : "Unavailable"}
            </span>
            <span className="lc-meta">
              Version {health.version} · {health.auth_mode}
            </span>
          </div>
        </SettingsSection>

        <SettingsSection
          id="executors"
          title="Executors"
          description="Provider runtimes currently available to new projects."
        >
          <p className="lc-prose">
            {health.runtimes.join(", ") || "No executor credential is configured."}
          </p>
        </SettingsSection>

        <SettingsSection
          id="access-boundary"
          title="Access boundary"
          description="Organization context and instance-level capabilities for this session."
        >
          <p className="lc-prose">{me.organization?.id ?? "Local instance"}</p>
          <p className="lc-meta">{me.capabilities.join(" · ")}</p>
        </SettingsSection>
      </div>
    </ConsoleFrame>
  );
}
