import {
  createNotificationChannelAction,
  createNotificationRuleAction,
  setNotificationChannelStateAction,
  testNotificationChannelAction,
} from "@/app/actions";
import { PendingButton } from "@/components/pending-button";
import { formatTimestamp } from "@/lib/format";
import type {
  AttentionKind,
  NotificationChannel,
  NotificationDelivery,
  NotificationRule,
  Severity,
} from "@/lib/limina/types";

const attentionTypes: Array<{ value: AttentionKind; label: string }> = [
  { value: "agent_request", label: "Executor questions" },
  { value: "run_failure", label: "Run failures" },
  { value: "finding_review", label: "Finding reviews" },
  { value: "project_complete", label: "Project completion" },
  { value: "stalled_project", label: "Stalled projects" },
  { value: "notification_failure", label: "Delivery failures" },
  { value: "preflight_issue", label: "Preflight issues" },
  { value: "unattended_run", label: "Unattended runs" },
];

const severities: Severity[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

type Props = {
  slug: string;
  canManage: boolean;
  channels: NotificationChannel[];
  rules: NotificationRule[];
  deliveries: Record<string, NotificationDelivery[]>;
};

function healthRole(health: string): "success" | "critical" | "warning" | "muted" {
  if (health === "HEALTHY") return "success";
  if (health === "FAILING") return "critical";
  if (health === "DISABLED") return "muted";
  return "warning";
}

export function NotificationSettings({ slug, canManage, channels, rules, deliveries }: Props) {
  return (
    <section className="lc-panel lc-stack lc-stack--4">
      <div className="lc-stack lc-stack--2">
        <h2 className="lc-display lc-display--sm">Notifications</h2>
        <p className="lc-prose lc-prose--muted">
          Send concise attention summaries without exposing project secrets. Destinations are
          encrypted at rest and never returned by the API.
        </p>
      </div>

      {channels.length === 0 ? (
        <p className="lc-meta">No external notification destination is configured.</p>
      ) : (
        <div className="lc-stack lc-stack--4">
          {channels.map((channel) => {
            const channelRules = rules.filter((rule) => rule.channel_id === channel.id);
            const latestDelivery = deliveries[channel.id]?.[0];
            return (
              <div className="lc-field" key={channel.id}>
                <div className="lc-settings-row">
                  <span>{channel.display_name}</span>
                  <span className="lc-chip" data-role={healthRole(channel.health)}>
                    {channel.health}
                  </span>
                </div>
                <p className="lc-meta">
                  {channel.type.replaceAll("_", " ")} · {channel.destination.host ?? "Hidden"} ·{" "}
                  {channel.enabled ? "Enabled" : "Disabled"}
                </p>
                {channelRules.map((rule) => (
                  <p className="lc-meta" key={rule.id}>
                    {rule.display_name}: {rule.attention_types.length || "all"} attention types ·{" "}
                    {rule.severities.length ? rule.severities.join(", ") : "all severities"} ·{" "}
                    {rule.cooldown_seconds}s cooldown
                  </p>
                ))}
                {latestDelivery ? (
                  <p className="lc-meta">
                    Latest delivery: {latestDelivery.outcome} · {formatTimestamp(latestDelivery.completed_at)}
                    {latestDelivery.error_code ? ` · ${latestDelivery.error_code}` : ""}
                  </p>
                ) : null}
                {canManage ? (
                  <div className="lc-actions">
                    <form
                      action={testNotificationChannelAction.bind(null, slug, channel.id)}
                    >
                      <PendingButton kind="secondary" pendingLabel="Queuing…">
                        Send test
                      </PendingButton>
                    </form>
                    <form
                      action={setNotificationChannelStateAction.bind(
                        null,
                        slug,
                        channel.id,
                        !channel.enabled,
                      )}
                    >
                      <PendingButton kind="secondary">
                        {channel.enabled ? "Disable" : "Enable"}
                      </PendingButton>
                    </form>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      {canManage ? (
        <details>
          <summary className="lc-meta lc-meta--strong">Add a destination</summary>
          <form
            className="lc-stack lc-stack--3"
            action={createNotificationChannelAction.bind(null, slug)}
          >
            <label className="lc-field">
              <span className="tam-eyebrow">Type</span>
              <select className="lc-select" name="type" defaultValue="SLACK">
                <option value="SLACK">Slack incoming webhook</option>
                <option value="GENERIC_WEBHOOK">Generic signed webhook</option>
              </select>
            </label>
            <label className="lc-field">
              <span className="tam-eyebrow">Name</span>
              <input className="lc-writing-input" name="display_name" required maxLength={160} />
            </label>
            <label className="lc-field">
              <span className="tam-eyebrow">HTTPS destination</span>
              <input
                className="lc-writing-input"
                type="url"
                name="destination"
                placeholder="https://…"
                autoComplete="off"
                required
              />
            </label>
            <label className="lc-field">
              <span className="tam-eyebrow">Signing secret (generic webhook only)</span>
              <input
                className="lc-writing-input"
                type="password"
                name="signing_secret"
                autoComplete="new-password"
              />
            </label>
            <label className="lc-confirm">
              <input type="checkbox" name="trust_delegation_confirmed" required />
              I authorize Limina to share concise attention summaries with this destination.
            </label>
            <PendingButton kind="secondary">Save destination</PendingButton>
          </form>
        </details>
      ) : null}

      {canManage && channels.length > 0 ? (
        <details>
          <summary className="lc-meta lc-meta--strong">Add a delivery rule</summary>
          <form
            className="lc-stack lc-stack--3"
            action={createNotificationRuleAction.bind(null, slug)}
          >
            <label className="lc-field">
              <span className="tam-eyebrow">Destination</span>
              <select className="lc-select" name="channel_id">
                {channels.map((channel) => (
                  <option key={channel.id} value={channel.id}>
                    {channel.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="lc-field">
              <span className="tam-eyebrow">Rule name</span>
              <input className="lc-writing-input" name="display_name" required maxLength={160} />
            </label>
            <fieldset className="lc-field">
              <legend className="tam-eyebrow">Attention types (none means all)</legend>
              {attentionTypes.map((item) => (
                <label className="lc-confirm" key={item.value}>
                  <input type="checkbox" name="attention_types" value={item.value} />
                  {item.label}
                </label>
              ))}
            </fieldset>
            <fieldset className="lc-field">
              <legend className="tam-eyebrow">Severities (none means all)</legend>
              <div className="lc-actions">
                {severities.map((severity) => (
                  <label className="lc-confirm" key={severity}>
                    <input type="checkbox" name="severities" value={severity} />
                    {severity}
                  </label>
                ))}
              </div>
            </fieldset>
            <label className="lc-field">
              <span className="tam-eyebrow">Cooldown in seconds</span>
              <input
                className="lc-writing-input"
                type="number"
                name="cooldown_seconds"
                min={0}
                max={86_400}
                defaultValue={300}
                required
              />
            </label>
            <PendingButton kind="secondary">Save rule</PendingButton>
          </form>
        </details>
      ) : null}
    </section>
  );
}
