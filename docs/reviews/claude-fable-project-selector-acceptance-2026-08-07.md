# Claude Code Opus 5 project-selector acceptance — Limina Console

Date: 2026-08-07

Reviewed branch: `feat/limina-console-tam50`

Review posture: independent max-reasoning proposal, reciprocal implementation review, and final
resolution with Codex.

Final consensus verdict: **APPROVE — SHIP**

## Joint design

Claude and Codex independently converged on a single searchable selector replacing the duplicated
static project-name row. The shipped design improves on the first proposal in three agreed ways:

- the selector is global and uses All Projects outside project context, matching the leader's
  reference more closely;
- project choices remain native links inside a non-modal dialog, preserving new-tab behavior and
  simpler screen-reader semantics;
- the mobile selector expands inline at full width rather than introducing an overlay and focus
  trap.

Switching preserves the current top-level project section while dropping detail IDs and Settings
sub-routes. The selector filters by name or slug, pins and checks the current project, provides a
capability-gated Create Project action, and visibly reports when the authorized project total is
larger than the 200-item selector contract.

## Reciprocal findings and closure

Claude's initial acceptance found no P0 or P1. Codex accepted and closed the concrete follow-ups:

- keyboard and assistive-technology opens focus search even on touch-primary devices; ordinary
  coarse-pointer taps do not force the software keyboard;
- Home and End retain native search-caret behavior and move through options only while a project
  link has focus;
- Escape restores the trigger, outside interaction and Tab-out dismiss, and arrow keys traverse
  navigation links;
- empty, no-match, filter-recovery, and list-limit states have unit coverage;
- desktop and mobile Playwright cover open-popover accessibility, keyboard focus, Escape, outside
  dismissal, filtering, and section-preserving selection;
- light and dark production captures both prove zero horizontal overflow and no popover shadow.

## Nonblocking watch points

The authorized project list refetches on each server navigation; React request caching only
deduplicates calls within one render. This is acceptable at the current 200-project contract and is
the first optimization trigger if remote shell TTFB becomes material.

Synthetic click `detail === 0` is the standard assistive-technology heuristic but not universal.
Failure is soft: focus remains on the trigger and the next Tab reaches search.

## Leader-facing conclusion

Both reviewers recommend shipping. The selector provides the requested Vercel-like project
switching while retaining TAM-50 typography, geometry, Carbon icons, shadowless surfaces, project
vocabulary, and server-authoritative authorization.
