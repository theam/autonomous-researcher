import type { ReactNode } from "react";

type Props = {
  id: string;
  title: string;
  description: string;
  action?: ReactNode;
  children: ReactNode;
};

export function SettingsSection({ id, title, description, action, children }: Props) {
  return (
    <section className="lc-settings-section" id={id} aria-labelledby={`${id}-title`}>
      <div className="lc-settings-section__head">
        <div className="lc-stack lc-stack--2">
          <h2 className="lc-display lc-display--sm" id={`${id}-title`}>
            {title}
          </h2>
          <p className="lc-prose lc-prose--muted">{description}</p>
        </div>
        {action ? <div className="lc-settings-section__action">{action}</div> : null}
      </div>
      <div className="lc-settings-section__body">{children}</div>
    </section>
  );
}
