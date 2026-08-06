/**
 * Shared state and kind marks for the Console.
 *
 * Two orthogonal encodings, kept strictly separate:
 *   - KIND is carried by geometry + text. H = circle, E = square, F = diamond.
 *   - STATE is carried by a TAM semantic colour role + a Carbon icon + text.
 *
 * Because kind never consumes colour, colour stays free to mean state, and no
 * information is ever conveyed by colour alone (WCAG 2.2 AA, 1.4.1).
 *
 * Server-compatible: no "use client", no hooks, no event handlers.
 */

import {
  CheckmarkFilled,
  CircleDash,
  DocumentTasks,
  ErrorFilled,
  Idea,
  Information,
  ListChecked,
  Notification,
  Time,
  Warning,
} from "@carbon/icons-react";
import type { CarbonIconType } from "@carbon/icons-react";

import type { AttentionKind, Severity } from "@/lib/limina/types";

/** TAM semantic colour roles. `accent` is the Limina product role. */
export type StateRole = "critical" | "warning" | "success" | "info" | "muted" | "accent";

/* ── Severity ─────────────────────────────────────────────────────────────── */

const SEVERITY_ROLE: Record<Severity, StateRole> = {
  CRITICAL: "critical",
  HIGH: "warning",
  MEDIUM: "info",
  LOW: "muted",
};

const SEVERITY_ICON: Record<Severity, CarbonIconType> = {
  CRITICAL: ErrorFilled,
  HIGH: Warning,
  MEDIUM: Information,
  LOW: CircleDash,
};

/* ── Attention kind ───────────────────────────────────────────────────────── */

/**
 * Exhaustive over AttentionKind by construction: adding a kind in
 * lib/limina/types.ts breaks typecheck here rather than silently rendering
 * an unlabelled item.
 */
const KIND_LABEL: Record<AttentionKind, string> = {
  agent_request: "Agent request",
  run_failure: "Run failure",
  finding_review: "Evidence review",
  project_complete: "Mission complete",
  stalled_project: "Stalled project",
  notification_failure: "Delivery failure",
  preflight_issue: "Preflight issue",
  unattended_run: "Unattended run",
};

const KIND_ICON: Record<AttentionKind, CarbonIconType> = {
  agent_request: Idea,
  run_failure: ErrorFilled,
  finding_review: DocumentTasks,
  project_complete: CheckmarkFilled,
  stalled_project: Warning,
  notification_failure: Notification,
  preflight_issue: ListChecked,
  unattended_run: Time,
};

export function attentionKindLabel(kind: AttentionKind): string {
  return KIND_LABEL[kind];
}

/* ── Chip ─────────────────────────────────────────────────────────────────── */

export type StateChipProps = {
  role: StateRole;
  icon: CarbonIconType;
  label: string;
  /** Extra context announced to assistive tech but not shown. */
  description?: string;
};

/** Colour + icon + text. Never colour alone. */
export function StateChip({ role, icon: Icon, label, description }: StateChipProps) {
  return (
    <span className="lc-chip" data-role={role}>
      <Icon size={16} className="lc-chip__icon" aria-hidden focusable="false" />
      <span>{label}</span>
      {description ? <span className="lc-visually-hidden">{description}</span> : null}
    </span>
  );
}

export function SeverityChip({ severity }: { severity: Severity }) {
  return (
    <StateChip
      role={SEVERITY_ROLE[severity]}
      icon={SEVERITY_ICON[severity]}
      label={severity}
      description="severity"
    />
  );
}

export function AttentionKindChip({ kind }: { kind: AttentionKind }) {
  return (
    <StateChip role="muted" icon={KIND_ICON[kind]} label={KIND_LABEL[kind]} />
  );
}

/* ── H / E / F mark ───────────────────────────────────────────────────────── */

export type HefKind = "H" | "E" | "F";

const HEF_NAME: Record<HefKind, string> = {
  H: "Hypothesis",
  E: "Experiment",
  F: "Finding",
};

export type HefMarkProps = {
  kind: HefKind;
  /** Visible technical label, e.g. "H001". Falls back to the kind name. */
  label?: string;
  /** Solid shape rather than outline, for a settled artifact. */
  filled?: boolean;
};

/**
 * The shape is decorative on its own — the adjacent text always carries the
 * meaning — so it is hidden from assistive tech and the full artifact name is
 * announced instead.
 */
export function HefMark({ kind, label, filled = false }: HefMarkProps) {
  return (
    <span
      className={filled ? "lc-hef lc-hef--filled" : "lc-hef"}
      data-kind={kind}
    >
      <span className="lc-hef__shape" aria-hidden />
      <span>{label ?? HEF_NAME[kind]}</span>
      <span className="lc-visually-hidden">{HEF_NAME[kind]}</span>
    </span>
  );
}

export function hefName(kind: HefKind): string {
  return HEF_NAME[kind];
}
