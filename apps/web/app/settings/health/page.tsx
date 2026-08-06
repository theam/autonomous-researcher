import { ConsoleFrame } from "@/components/console-frame";
import { StreamHealth } from "@/components/stream-health";
import { getMe, getRuntimeHealth } from "@/lib/limina/server";

export default async function HealthPage() {
  const [me, health] = await Promise.all([getMe(), getRuntimeHealth()]);
  return <ConsoleFrame activeNav="projects"><div className="lc-pagehead"><div><p className="tam-eyebrow">Instance administration</p><h1 className="lc-display">Health</h1></div><StreamHealth /></div><div className="lc-settings-grid"><section className="lc-panel lc-stack lc-stack--3"><h2 className="lc-display lc-display--sm">Runtime API</h2><span className="lc-chip" data-role={health.ok ? "success" : "critical"}>{health.ok ? "Healthy" : "Unavailable"}</span><p className="lc-meta">Version {health.version} · {health.auth_mode}</p></section><section className="lc-panel lc-stack lc-stack--3"><h2 className="lc-display lc-display--sm">Executors</h2><p className="lc-prose">{health.runtimes.join(", ") || "No executor credentials configured"}</p></section><section className="lc-panel lc-stack lc-stack--3"><h2 className="lc-display lc-display--sm">Access boundary</h2><p className="lc-prose">{me.organization?.id ?? "Local instance"}</p><p className="lc-meta">{me.capabilities.join(" · ")}</p></section></div></ConsoleFrame>;
}
