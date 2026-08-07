---
event_id: evt-2026-08-06-limina-console-tam50
piece: "Limina Console — apps/web (live: http://127.0.0.1:7433)"
piece_file: "apps/web/app/page.tsx"
type: proto
tier_declared: 50
tier_final: 50
environment: "local development (org_local)"
evaluation:
  evaluator: "skills/tam-brand-system/evaluators/proto.md"
  ssot_current: "0.2.6"
  ssot_referenced: "0.2.6"
  ssot_commit: "d65a58be63bdffd4a1503f15cb7c8632167e123b"
  ssot_version_source: "live hub /version endpoint, confirmed"
  generator_mode: create
  mode_declared: auto
  surface_scope_declared: desktop_and_mobile
  metadata_sidecar: "apps/web/tam-decision.yml"
verdict: compliant
outcome: corrected
signals:
  failure_origin: unknown
  root_cause_hypothesis: unknown
failed_checks: []
n_a_checks:
  - id: imagery
    reason: "No product imagery, screenshots, mockups, or diagrams appear in evaluated surfaces; only the Limina mark and Carbon icons are present."
resolution:
  type: corrections_applied
  corrections_present:
    - "Neue Galano/Montserrat structurally excluded; proto display bound to IBM Plex Sans Medium."
    - "IBM Plex Mono carries chrome and IBM Plex Sans carries prose; authorship is not encoded by typeface."
    - "Token-only color with one restrained violet product accent mapped onto TAM roles; state uses color, icon, and text."
    - "r4 contained surfaces, r0 writing inputs, pill radius reserved to tags, and no shadows."
    - "Current product_logo_plus_tam_text footer signature with linked live TAM text and the Limina mark."
    - "Contrast tuned for AA in light and dark modes."
    - "Plain-language system messages and explicit destructive-action confirmation."
    - "Persistent workspace/project navigation and route-level read-state-first settings replace the prior card-heavy composition while retaining TAM-50 geometry and tokens."
  open_fixes: []
  optional_polish:
    - "Move the project preflight heading below the overview h1, or demote it to a non-heading callout."
    - "Add Escape and outside-click dismissal to the Start/Archive confirmation layer."
    - "Define the referenced .lc-action-row layout utility."
  tier_change: none
system_implications:
  candidate_files_to_revisit:
    - "skills/tam-brand-system/evaluators/proto.md — TAM-50 signature wording still says with_wordmark_image."
    - "skills/tam-brand-system/references/brand-alignment.md — the frozen tier map still says with_wordmark_image."
  pattern_keys:
    - tam50-signature-wording-drift
    - tam50-proto-compliant-create
governance:
  pr_cadence: weekly_grouped
  notification_guardian: not_produced
  notes: "Compliant TAM-50 proto closed as corrected. No accepted drift."
---

# Resolution · Limina Console — TAM-50 proto · `corrected`

An evaluator isolated from the implementation role inspected the Limina Console against the canonical TAM brand-system at version `0.2.6` and commit `d65a58be63bdffd4a1503f15cb7c8632167e123b`.

The piece is **compliant**: all 24 universal UX-floor checks pass, all seven applicable TAM-50 inherited proto checks pass, and imagery is not applicable. Piece metadata, canonical SSOT, and the live version endpoint agree on `0.2.6`.

The case closes as **`corrected`** under the requested post-correction framing. The aligned typography, roles, component geometry, spacing, iconography, contrast, system feedback, and current `product_logo_plus_tam_text` signature are embodied in the artifact. There are no open fixes; three optional polish notes are retained above.

No `publish_drift` occurred, so no guardian notification is produced. The only system-level signal is stale signature wording in two supporting SSOT documents, superseded by the current TAM-50 tier file.
