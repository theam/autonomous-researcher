/**
 * Limina product mark — original geometry, not TAM artwork.
 *
 * "Limina" is Latin *limen*, threshold. The mark is a contained square (the
 * known) crossed by a single full-width rule (the threshold), with a shorter
 * muted rule above it standing for what has already been established. Drawn in
 * currentColor so it inherits surrounding ink in both themes; no gradients, no
 * decorative fill, no shadow.
 *
 * Deliberately distinct from the TAM symbol shipped in
 * @theam/brand-system/assets — that artwork is not redrawn or reinterpreted
 * here; the footer signature carries the TAM attribution as linked text.
 */

export type LiminaMarkProps = {
  /** Edge length in px. Defaults to 20 so it sits on the 4px grid. */
  size?: number;
  /** Accessible name. Omit to render the mark as decorative. */
  title?: string;
};

export function LiminaMark({ size = 20, title }: LiminaMarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      {title ? <title>{title}</title> : null}
      <rect
        x="1.5"
        y="1.5"
        width="17"
        height="17"
        rx="2"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path d="M1.5 10.25H18.5" stroke="currentColor" strokeWidth="1.5" />
      <path
        d="M6.5 5.75H13.5"
        stroke="currentColor"
        strokeWidth="1.5"
        opacity="0.45"
      />
    </svg>
  );
}

export default LiminaMark;
