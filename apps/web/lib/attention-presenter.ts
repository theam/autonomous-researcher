import type { DeskAction, DeskItem } from "@/components/attention-desk";
import { formatRelative } from "@/lib/format";
import type { AttentionItem } from "@/lib/limina/types";

const actionLabels: Record<string, string> = {
  ANSWER: "Answer",
  SELECT: "Choose",
  CONFIRM: "Confirm",
  REJECT: "Reject",
  REVIEW: "Review evidence",
  ACKNOWLEDGE: "Acknowledge",
  SNOOZE: "Snooze",
};

export function presentAttention(item: AttentionItem, selected: boolean): DeskItem {
  const allowedActions: DeskAction[] = item.allowed_actions.map((action) => ({
    id: action,
    label: actionLabels[action] ?? action.replaceAll("_", " ").toLowerCase(),
    intent:
      action === "ANSWER" || action === "SELECT" || action === "CONFIRM" || action === "REVIEW"
        ? "primary"
        : action === "REJECT"
          ? "critical"
          : "neutral",
  }));
  return {
    id: item.id,
    kind: item.kind,
    severity: item.severity,
    title: item.title,
    summary: item.summary,
    project: item.project,
    timestamp: item.opened_at,
    timeLabel: formatRelative(item.opened_at),
    selected,
    allowedActions,
    responseMode: item.request?.response_mode,
    choices: item.request?.choices,
    href: `/?item=${encodeURIComponent(item.id)}`,
    version: item.version,
  };
}
