import Link from "next/link";

import {
  createNotificationChannelAction,
  createNotificationRuleAction,
  setNotificationChannelStateAction,
  testNotificationChannelAction,
} from "@/app/actions";
import { PendingButton } from "@/components/pending-button";
import { SettingsSection } from "@/components/settings-section";
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
  basePath: string;
  showDestinationForm: boolean;
  showRuleForm: boolean;
};

function healthRole(health: string): "success" | "critical" | "warning" | "muted" {
  if (health === "HEALTHY") return "success";
  if (health === "FAILING") return "critical";
  if (health === "DISABLED") return "muted";
  return "warning";
}

export function NotificationSettings({
  slug,
  canManage,
  channels,
  rules,
  deliveries,
  basePath,
  showDestinationForm,
  showRuleForm,
}: Props) {
  return (
    <SettingsSection
      id="notifications"
      title="Notifications"
      description="Send concise attention summaries without exposing project secrets. Destinations are encrypted and never returned by the API."
      action={
        canManage ? (
          <div className="lc-actions">
            {!showDestinationForm ? (
              <Link className="tam-button tam-button--outline" href={`${basePath}?add=destination`}>
                Add destination
              </Link>
            ) : null}
            {channels.length > 0 && !showRuleForm ? (
              <Link className="tam-button tam-button--outline" href={`${basePath}?add=rule`}>
                Add rule
              </Link>
            ) : null}
          </div>
        ) : null
      }
    >
      {showDestinationForm ? (
        <form
          className="lc-settings-form lc-stack lc-stack--4"
          action={createNotificationChannelAction.bind(null, slug)}
        >
          <div className="lc-settings-form__head">
            <p className="lc-meta">Add an encrypted external destination.</p>
            <Link className="lc-text-link" href={basePath}>
              Cancel
            </Link>
          </div>
          <label className="lc-field">
            <span className="tam-eyebrow">Type</span>
            <select className="lc-select" name="type" defaultValue="SLACK">
              <option value="SLACK">Slack incoming webhook</option>
              <option value="GENERIC_WEBHOOK">Generic signed webhook</option>
            </select>
          </label>
          <label className="lc-field">
            <span className="tam-eyebrow">Name</span>
            <input
              className="lc-writing-input"
              name="display_name"
              placeholder="Research alerts…"
              autoComplete="off"
              required
              maxLength={160}
            />
          </label>
          <label className="lc-field">
            <span className="tam-eyebrow">HTTPS destination</span>
            <input
              className="lc-writing-input"
              type="url"
              name="destination"
              placeholder="https://hooks.example.com/limina…"
              autoComplete="off"
              spellCheck={false}
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
      ) : null}

      {showRuleForm && channels.length > 0 ? (
        <form
          className="lc-settings-form lc-stack lc-stack--4"
          action={createNotificationRuleAction.bind(null, slug)}
        >
          <div className="lc-settings-form__head">
            <p className="lc-meta">Choose which attention events reach a destination.</p>
            <Link className="lc-text-link" href={basePath}>
              Cancel
            </Link>
          </div>
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
            <input
              className="lc-writing-input"
              name="display_name"
              placeholder="High-priority attention…"
              autoComplete="off"
              required
              maxLength={160}
            />
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
              inputMode="numeric"
              min={0}
              max={86_400}
              defaultValue={300}
              required
            />
          </label>
          <PendingButton kind="secondary">Save rule</PendingButton>
        </form>
      ) : null}

      {channels.length === 0 ? (
        <p className="lc-settings-empty">No external notification destination is configured.</p>
      ) : (
        <div className="lc-settings-list">
          {channels.map((channel) => {
            const channelRules = rules.filter((rule) => rule.channel_id === channel.id);
            const latestDelivery = deliveries[channel.id]?.[0];
            return (
              <div className="lc-settings-channel" key={channel.id}>
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

    </SettingsSection>
  );
}
