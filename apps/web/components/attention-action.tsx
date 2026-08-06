import Link from "next/link";

import { resolveAttentionAction } from "@/app/actions";
import { PendingButton } from "@/components/pending-button";
import type { DeskAction, DeskItem } from "@/components/attention-desk";
import type { AttentionItem } from "@/lib/limina/types";

type AttentionActionProps = {
  action: DeskAction;
  item: DeskItem;
  source: AttentionItem;
  interactionSurface: "TODAY" | "PROJECT_DETAIL";
};

export function AttentionAction({
  action,
  item,
  source,
  interactionSurface,
}: AttentionActionProps) {
  if (action.id === "REVIEW" && source.source.artifact_id) {
    return (
      <Link
        className="tam-button tam-button--primary tam-button--compact"
        href={`/projects/${encodeURIComponent(source.project.slug)}/knowledge/${encodeURIComponent(source.source.artifact_id)}`}
      >
        Review evidence
      </Link>
    );
  }

  const submit = resolveAttentionAction.bind(
    null,
    source.id,
    source.version,
    source.project.slug,
    interactionSurface,
  );
  if (action.id === "ANSWER") {
    return (
      <form action={submit} className="lc-inline-response">
        <input type="hidden" name="action" value="ANSWER" />
        <textarea className="lc-writing-input" aria-label={`Answer ${source.title}`} name="response" rows={3} required placeholder="Your answer" />
        <PendingButton pendingLabel="Sending…">Send answer</PendingButton>
      </form>
    );
  }
  if (action.id === "SELECT") {
    return (
      <form action={submit} className="lc-inline-response">
        <input type="hidden" name="action" value="SELECT" />
        <select className="lc-select" aria-label={`Choose a response for ${source.title}`} name="choice" required defaultValue="">
          <option value="" disabled>Select one</option>
          {item.choices?.map((choice) => <option value={choice} key={choice}>{choice}</option>)}
        </select>
        <PendingButton pendingLabel="Sending…">Submit choice</PendingButton>
      </form>
    );
  }
  if (action.id === "CONFIRM") {
    return (
      <form action={submit} className="lc-inline-response">
        <input type="hidden" name="action" value="CONFIRM" />
        <input type="hidden" name="response" value="Confirmed by the operator." />
        <label className="lc-confirm"><input type="checkbox" required /> I confirm this decision</label>
        <PendingButton pendingLabel="Confirming…">Confirm</PendingButton>
      </form>
    );
  }
  if (action.id === "REJECT") {
    return (
      <form action={submit} className="lc-inline-response">
        <input type="hidden" name="action" value="REJECT" />
        <textarea
          className="lc-writing-input"
          aria-label={`Reason for rejecting ${source.title}`}
          name="response"
          rows={3}
          required
          placeholder="Why should the executor not proceed?"
        />
        <PendingButton kind="secondary" pendingLabel="Rejecting…">Reject</PendingButton>
      </form>
    );
  }
  if (action.id === "ACKNOWLEDGE" || action.id === "SNOOZE") {
    return (
      <form action={submit}>
        <input type="hidden" name="action" value={action.id} />
        <PendingButton kind="secondary" pendingLabel="Updating…">
          {action.id === "SNOOZE" ? "Snooze for 1 hour" : "Acknowledge"}
        </PendingButton>
      </form>
    );
  }
  return <span className="lc-meta">{action.label} is unavailable here.</span>;
}
