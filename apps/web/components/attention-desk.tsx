/**
 * Today / the Desk — one ranked cross-project queue with a detail rail.
 *
 * Contract with the page layer:
 *   - This component NEVER mutates and never decides authority. It renders
 *     exactly the actions it is given in `allowedActions`, in order.
 *   - It does not format dates. `timeLabel` is pre-formatted by the caller and
 *     `timestamp` is the machine value for <time dateTime>. Formatting here
 *     would be a hydration and locale hazard in a server component.
 *   - Actions with no `href` and no `renderAction` render visibly inert
 *     (aria-disabled). That is deliberate: an unwired action should look
 *     unavailable rather than silently do nothing.
 *   - Supply `renderAction` to bind real controls (e.g. a <form action={...}>
 *     around resolveAttentionAction) without forking this file. Each call
 *     receives the whole item, including `version`, which the resolve action
 *     needs for its optimistic-concurrency check.
 *
 * Server-compatible: no "use client", no hooks, no event handlers.
 */

import type { ReactNode } from "react";

import { CheckmarkFilled, Time, WarningAlt } from "@carbon/icons-react";

import {
  AttentionKindChip,
  SeverityChip,
  attentionKindLabel,
} from "@/components/state-marks";
import type { AttentionKind, Severity } from "@/lib/limina/types";

export type DeskActionIntent = "primary" | "neutral" | "critical";

export type DeskAction = {
  id: string;
  label: string;
  intent?: DeskActionIntent;
  /** Render as a link when the action is navigation rather than a mutation. */
  href?: string;
};

/** Mirrors the response modes in lib/limina/types.ts. */
export type DeskResponseMode = "TEXT" | "CHOICE" | "CONFIRMATION" | "ARTIFACT_REVIEW";

export type DeskItem = {
  id: string;
  kind: AttentionKind;
  severity: Severity;
  title: string;
  summary: string;
  project: { slug: string; name: string };
  /** ISO-8601 instant, used for <time dateTime>. */
  timestamp: string;
  /** Pre-formatted age or time, e.g. "14h". */
  timeLabel: string;
  selected?: boolean;
  allowedActions: DeskAction[];
  /** Present only for agent requests. */
  responseMode?: DeskResponseMode;
  choices?: string[];
  /** Detail route for this item. */
  href?: string;
  /** Optimistic-concurrency version, passed through to renderAction. */
  version?: number;
};

export type DeskFreshness = {
  /** Pre-formatted, e.g. "8s ago". */
  lastSyncedLabel: string;
  stale: boolean;
};

export type AttentionDeskProps = {
  items: DeskItem[];
  freshness: DeskFreshness;
  /** "Since your last visit" lines, shown when the queue is empty and healthy. */
  digest?: string[];
  renderAction?: (action: DeskAction, item: DeskItem) => ReactNode;
};

const RESPONSE_MODE_LABEL: Record<DeskResponseMode, string> = {
  TEXT: "Written answer",
  CHOICE: "Choose one",
  CONFIRMATION: "Confirm",
  ARTIFACT_REVIEW: "Evidence review",
};

const INTENT_CLASS: Record<DeskActionIntent, string> = {
  primary: "tam-button--primary",
  neutral: "tam-button--outline",
  critical: "tam-button--critical",
};

function actionClassName(intent: DeskActionIntent | undefined): string {
  return `tam-button tam-button--compact ${INTENT_CLASS[intent ?? "neutral"]}`;
}

function DefaultAction({ action }: { action: DeskAction }) {
  const className = actionClassName(action.intent);
  if (action.href) {
    return (
      <a className={className} href={action.href}>
        {action.label}
      </a>
    );
  }
  return (
    <button
      type="button"
      className={className}
      data-desk-action={action.id}
      aria-disabled="true"
    >
      {action.label}
    </button>
  );
}

function Actions({
  item,
  renderAction,
}: {
  item: DeskItem;
  renderAction: AttentionDeskProps["renderAction"];
}) {
  if (item.allowedActions.length === 0) return null;
  return (
    <div className="lc-actions">
      {item.allowedActions.map((action) =>
        renderAction ? (
          <span key={action.id}>{renderAction(action, item)}</span>
        ) : (
          <DefaultAction key={action.id} action={action} />
        ),
      )}
    </div>
  );
}

function Freshness({ freshness }: { freshness: DeskFreshness }) {
  const Icon = freshness.stale ? WarningAlt : Time;
  return (
    <p className="lc-freshness" data-stale={freshness.stale} role="status">
      <Icon size={16} aria-hidden focusable="false" />
      {freshness.stale
        ? `Stale — last synced ${freshness.lastSyncedLabel}`
        : `Last synced ${freshness.lastSyncedLabel}`}
    </p>
  );
}

/**
 * The empty state is where an unhealthy stream would otherwise lie. When
 * freshness is stale it must not claim that nothing needs attention.
 */
function EmptyQueue({
  freshness,
  digest,
}: {
  freshness: DeskFreshness;
  digest: string[];
}) {
  if (freshness.stale) {
    return (
      <div className="lc-empty lc-stack lc-stack--3">
        <p className="lc-prose lc-prose--lead">
          This queue may be incomplete.
        </p>
        <p className="lc-meta">
          The attention stream last synced {freshness.lastSyncedLabel}. Items
          raised since then are not shown.
        </p>
      </div>
    );
  }
  return (
    <div className="lc-empty lc-stack lc-stack--3">
      <p className="lc-prose lc-prose--lead">No attention was pending at the last sync.</p>
      {digest.length > 0 ? (
        <div className="lc-digest">
          {digest.map((line) => (
            <span className="lc-meta" key={line}>
              {line}
            </span>
          ))}
        </div>
      ) : (
        <p className="lc-meta">
          Projects continue without you. Slack carries anything urgent.
        </p>
      )}
    </div>
  );
}

function QueueItem({
  item,
  renderAction,
}: {
  item: DeskItem;
  renderAction: AttentionDeskProps["renderAction"];
}) {
  const titleId = `desk-item-${item.id}-title`;
  return (
    <article
      className="lc-item"
      data-selected={item.selected ? "true" : undefined}
      aria-labelledby={titleId}
    >
      <div className="lc-item__head">
        <SeverityChip severity={item.severity} />
        <AttentionKindChip kind={item.kind} />
        <span className="lc-metaline">
          <span className="lc-meta lc-meta--strong">{item.project.name}</span>
          <span className="lc-meta lc-metaline__sep" aria-hidden>
            ·
          </span>
          <time className="lc-meta" dateTime={item.timestamp}>
            {item.timeLabel}
          </time>
        </span>
      </div>

      <h3 className="lc-item__title" id={titleId}>
        {item.href ? (
          <a
            className="lc-item__link"
            href={item.href}
            aria-current={item.selected ? "true" : undefined}
          >
            {item.title}
          </a>
        ) : (
          item.title
        )}
      </h3>

      <p className="lc-prose lc-prose--muted">{item.summary}</p>

      <Actions item={item} renderAction={renderAction} />
    </article>
  );
}

function DetailRail({
  item,
  renderAction,
}: {
  item: DeskItem | undefined;
  renderAction: AttentionDeskProps["renderAction"];
}) {
  if (!item) {
    return (
      <aside className="lc-panel" aria-labelledby="desk-rail-title">
        <h2 className="lc-display lc-display--sm" id="desk-rail-title">
          Detail
        </h2>
        <hr className="lc-divider" />
        <p className="lc-prose lc-prose--muted">
          Open an item to see the evidence behind it and the responses it
          accepts.
        </p>
      </aside>
    );
  }

  const choices = item.choices ?? [];

  return (
    <aside className="lc-panel" aria-labelledby="desk-rail-title">
      <h2 className="lc-display lc-display--sm" id="desk-rail-title">
        {item.title}
      </h2>

      <div className="lc-rail__section lc-stack lc-stack--3">
        <span className="lc-metaline">
          <SeverityChip severity={item.severity} />
          <AttentionKindChip kind={item.kind} />
        </span>
        <p className="lc-prose">{item.summary}</p>
      </div>

      <div className="lc-rail__section lc-stack lc-stack--2">
        <span className="tam-eyebrow">Source</span>
        <span className="lc-meta lc-meta--strong">{item.project.name}</span>
        <span className="lc-meta">
          {attentionKindLabel(item.kind)} · opened{" "}
          <time dateTime={item.timestamp}>{item.timeLabel}</time>
        </span>
      </div>

      {item.responseMode ? (
        <div className="lc-rail__section lc-stack lc-stack--2">
          <span className="tam-eyebrow">Response</span>
          <span className="lc-meta lc-meta--strong">
            {RESPONSE_MODE_LABEL[item.responseMode]}
          </span>
          {choices.length > 0 ? (
            <ul className="lc-choices">
              {choices.map((choice) => (
                <li className="lc-choice" key={choice}>
                  {choice}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {item.allowedActions.length > 0 ? (
        <div className="lc-rail__section lc-stack lc-stack--2">
          <span className="tam-eyebrow">Available to you</span>
          <Actions item={item} renderAction={renderAction} />
        </div>
      ) : (
        <div className="lc-rail__section">
          <p className="lc-meta">
            <CheckmarkFilled size={16} aria-hidden focusable="false" /> No action
            is available to you on this item.
          </p>
        </div>
      )}
    </aside>
  );
}

export function AttentionDesk({
  items,
  freshness,
  digest = [],
  renderAction,
}: AttentionDeskProps) {
  const selected = items.find((item) => item.selected);

  return (
    <section aria-labelledby="desk-title">
      <div className="lc-pagehead">
        <div className="lc-stack lc-stack--2">
          <span className="tam-eyebrow">Attention</span>
          <h1 className="lc-display" id="desk-title">
            Today
          </h1>
        </div>
        <Freshness freshness={freshness} />
      </div>

      <div className="lc-grid">
        <div className="lc-col-5">
          <h2 className="lc-visually-hidden" id="desk-queue-title">
            Items needing your attention
          </h2>
          {items.length === 0 ? (
            <div className="lc-queue">
              <EmptyQueue freshness={freshness} digest={digest} />
            </div>
          ) : (
            <ol className="lc-queue" aria-labelledby="desk-queue-title">
              {items.map((item) => (
                <li className="lc-queue__item" key={item.id}>
                  <QueueItem item={item} renderAction={renderAction} />
                </li>
              ))}
            </ol>
          )}
        </div>

        <div className="lc-col-3">
          <DetailRail item={selected} renderAction={renderAction} />
        </div>
      </div>
    </section>
  );
}

export default AttentionDesk;
