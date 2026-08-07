# Evaluation · Limina Console — TAM-50 · proto

_Evaluator: `skills/tam-brand-system/evaluators/proto.md`, independent of the generator._
_Date: 2026-08-07 · Verdict: **Compliant**_

## 2026-08-07 navigation reevaluation

The post-acceptance information-architecture pass remains compliant. The new persistent sidebar
uses Carbon icons, TAM spacing and semantic roles, r4 interactive surfaces, no shadows, and the
existing product-logo-plus-TAM-text signature. Project navigation is structurally nested under the
workspace rail; Settings uses a restrained route index and border-separated rows rather than a
generic card grid. Writing forms retain r0 inputs and appear only on explicit edit/add routes.

Desktop dark, 1280×720, and narrow mobile captures were inspected. The rail and footer remain
visible at 1280×720, the main canvas has no page-level horizontal overflow, and mobile preserves the
same navigation order through a native disclosure. The Playwright desktop/mobile accessibility
suite passes 18/18 after the change. No TAM-50 check changed from pass to fail.

## 1 · Summary

| Field | Value |
|---|---|
| Piece | Limina Console (`apps/web`), live at `http://127.0.0.1:7433` |
| Entrypoint | `app/page.tsx` (Next.js/React, App Router) |
| Type · tier | `proto` · **TAM-50** (declared and confirmed) |
| SSOT current | `0.2.6` at canonical commit `d65a58be63bdffd4a1503f15cb7c8632167e123b`, verified against the live `/version` endpoint |
| Piece `system_version` | `0.2.6` — matches; no version lag |
| `generator_mode` | `create` — all tier checks apply to the whole piece |
| `mode_applied` | `auto` — `prefers-color-scheme` with explicit light/dark overrides; light and dark evidence inspected |
| `surface_scope` | `desktop_and_mobile` — responsive behavior and mobile evidence inspected |
| Display variant | `sans_default` — IBM Plex Sans Medium; Neue Galano absent |
| Signature variant | `product_logo_plus_tam_text` — present, linked, and correct |
| Metadata sidecar | `apps/web/tam-decision.yml` present |
| **Verdict** | **Compliant** — 24/24 UX-floor checks pass; 7/7 applicable TAM-50 piece checks pass; imagery is N/A |

Canonical precedence was applied. The current `tiers/TAM-50.design.md` v0.4 fixes the signature as `product_logo_plus_tam_text` and supersedes the older `with_wordmark_image` wording still present in the proto evaluator and the frozen brand-alignment map. That wording mismatch is an SSOT documentation-consistency item, not a defect in this piece.

## 2 · Checks by category

### 2.1 · Universal UX floor

Source: `foundations/UX.md` v0.3, consumed as the current 24-check `ux_foundations_checks` block.

| ID | Severity | Result | Reason and evidence |
|---|---|---|---|
| `structure.semantic_html` | high | **pass** | Semantic `header`, `nav`, `main`, `footer`, lists, articles, asides, labelled sections, fieldsets, labels, times, links, and buttons are used according to function. |
| `structure.heading_hierarchy` | medium | **pass** | Top-level pages have one `h1`; panels descend through `h2` and queue items through `h3`, with no arbitrary level jump. A conditional preflight `h2` precedes the overview `h1` in source order; moving it below the `h1` is optional polish, not a hierarchy failure. |
| `a11y.contrast_text` | high | **pass** | Role-driven colors meet the relevant floor: violet link `#4338CA` on white is 7.9:1; dark link `#A5B4FC` on black is 10.5:1; muted `#707070` is 4.54:1 on `#F5F5F5`; critical `#D83A34` is 4.59:1 on white. |
| `a11y.focus_visible` | high | **pass** | Global 2px TAM focus-yellow `:focus-visible` treatment and `:focus-within` for composite fields; the one search-input outline reset is replaced at wrapper level. |
| `a11y.touch_targets` | high | **pass** | Interactive controls are at least 24×24 CSS px; primary controls are 40px. Small icons are contained by larger targets or paired with text. |
| `a11y.alt_text` | high | **pass** | The Limina mark is named when informative and hidden when decorative; Carbon icons are hidden from assistive technology when text supplies the name. |
| `a11y.lang_attribute` | medium | **pass** | The root document declares `lang="en"` and the product copy is English. |
| `a11y.keyboard_navigation` | high | **pass** | Native links, buttons, selects, details/summary, checkboxes, and radios retain keyboard behavior; a skip link targets `main`; DOM and reading order align. |
| `interaction.feedback_on_action` | medium | **pass** | Pending actions change label and disable; stream health exposes connecting, synced, and delayed states through a polite live region; unavailable actions render visibly inert. |
| `interaction.dismissible_layers` | medium | **pass** | The only layer is the explicit Start/Archive sensitive-decision confirmation. Its visible summary control closes it; adding Escape/outside-click behavior is optional polish. |
| `interaction.preserve_user_work` | high | **pass** | Durable brief prerequisites precede runtime start; common invalid submissions are caught before transport; directory search persists in the URL. Server action notices preserve decision integrity when state changes. |
| `interaction.reversibility` | medium | **pass** | Archive and confirmation actions require an explicit acknowledgement and state their consequences; durable evidence remains readable after archive. |
| `forms.label_accessibility` | high | **pass** | Complex forms have visible associated labels; compact add-forms provide programmatic names; grouped choices use fieldset/legend. |
| `forms.visible_cue_policy` | high | **pass** | Complex/high-risk kickoff fields use visible labels without redundant placeholders; short add-forms use one placeholder cue with a programmatic label. |
| `forms.input_tolerance` | low | **pass** | Human prose inputs are free-form. Strict formats are limited to identifiers whose constraints are meaningful and explained. |
| `forms.input_semantics` | medium | **pass** | URL, email, number, search, password, and autocomplete semantics match the task and expected keyboard. |
| `forms.error_messages_helpful` | medium | **pass** | Validation and API errors are mapped to plain-language next steps; stack traces and transport codes do not surface. |
| `copy.cta_verb_object` | low | **pass** | Action labels use concrete verb/object pairs such as “Create draft,” “Send answer,” “Submit choice,” and “Confirm archive.” |
| `copy.cta_matches_action` | high | **pass** | Labels describe the real effect; project creation explicitly says it does not start execution. |
| `copy.no_filler` | low | **pass** | Product copy is compact and operational. |
| `copy.system_messages_user_voiced` | medium | **pass** | Error, empty, stale, and permission states explain what happened and what it means without internal mechanism language. |
| `antipattern.no_fake_urgency` | high | **pass** | No artificial countdowns, scarcity, or non-critical red alerts. |
| `antipattern.no_dark_patterns` | high | **pass** | Destructive outcomes are guarded and honestly described; permissions are explicit; write-only secrets are not redisplayed. |
| `antipattern.no_forced_gamification` | medium | **pass** | H/E/F counts are domain evidence, not streaks, badges, or levels. |

### 2.2 · TAM-50 inherited proto piece checks

Source: `TAM-50.design.md → evaluator.piece_checks`, interpreted through the TAM-100 proto grammar.

| ID | Result | Reason and evidence |
|---|---|---|
| `typography` | **pass** | Proto display is IBM Plex Sans Medium. IBM Plex Mono carries chrome and metadata; IBM Plex Sans carries prose and input. Neue Galano/Montserrat are not used and Serif is not invoked. |
| `components` | **pass** | Buttons and contained surfaces use r4, writing inputs use r0, the pill radius is reserved for tags, interaction states are present, and no shadow is used. |
| `composition` | **pass** | The product uses a ranked attention queue and detail rail, situation-first project views, true tables for tabular data, hairline structure, and functional grouping instead of a generic card wall. |
| `color` | **pass** | One restrained product accent maps to TAM roles. Semantic states use color together with icon and text; product color remains disciplined and structural edges remain quiet. |
| `imagery` | **n-a** | No product screenshots, mockups, diagrams, or photography appear in evaluated surfaces; only the Limina mark and Carbon icons are present. |
| `icons` | **pass** | `@carbon/icons-react` is used exclusively at coherent sizes; small icons are paired with text. |
| `spacing` | **pass** | Layout uses `--tam-space-1..10`, an eight-column desktop grammar, hierarchical gaps, and responsive horizontal discipline. |
| `signature` | **pass** | The footer combines the Limina product mark with live IBM Plex text “An initiative by The Agile Monkeys,” linked to `https://theagilemonkeys.com`, at discreet footer scale and AA contrast. |

## 3 · Version lags

None. Piece metadata, the canonical SSOT, and the live brand-system version endpoint all report `0.2.6`. No token or rule delta requires reconciliation.

The older `with_wordmark_image` wording in two canonical supporting documents is resolved by current-tier precedence; it is an SSOT documentation-consistency issue, not a piece version lag.

## 4 · Generator notices

- **“The newer TAM-50 tier signature rule supersedes the older proto generator wording.”** Accepted. The piece correctly implements `product_logo_plus_tam_text` from current `TAM-50.design.md` v0.4.
- **“The private `@theam/brand-system` package requires a GitHub Packages read token at build time.”** Accepted as an operations concern outside the brand check.
- The declared restrained violet accent and 5/3 attention layout respect TAM-50 product freedom and inherited proto grammar; neither is drift.

## 5 · Three paths

### A · Accept drift

Not applicable. No drift was found, so no `notification-guardian.md` is produced.

### B · Correction — closed as `corrected`

No open correction remains. The post-correction artifact already embodies:

1. Proto display bound to IBM Plex Sans Medium, with Neue Galano/Montserrat structurally excluded.
2. Mono/Sans role separation, without encoding authorship through typeface.
3. Token-only color and one mapped product accent; state communicated with color, icon, and text.
4. r4 contained surfaces, r0 writing surfaces, pill radius reserved for tags, and zero shadows.
5. The current `product_logo_plus_tam_text` signature.
6. Contrast tuning for AA in both modes.
7. Plain-language system feedback and explicit confirmation for destructive actions.

Optional polish, not check failures:

- Move the project preflight heading below the overview `h1`, or render it as a non-heading callout.
- Add Escape/outside-click dismissal to the Start/Archive confirmation layer.
- Define the referenced `.lc-action-row` layout utility.

Governance route: weekly grouped guardian PR.

### C · Reevaluate tier

Not applicable. The inherited layer is consistently respected and the product has a direct TAM relationship. No `reevaluation_signal` exists; TAM-50 is the correct tier.

## Independence notes

The evaluator inspected the canonical 0.2.6 skill and required references, source code, installed TAM package, desktop light/dark captures, mobile capture, metadata, live HTTP response, CSS/token usage, headings, form semantics, focus handling, icon imports, and load-bearing contrast ratios. It did not modify the piece.

Runtime keyboard traversal and screen-reader announcements were judged from native source semantics and existing interaction evidence rather than a manual assistive-technology session. Less-common semantic chip combinations were spot-checked rather than exhaustively measured. Neither uncertainty changed an atomic check result.
