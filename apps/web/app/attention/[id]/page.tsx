import { AttentionAction } from "@/components/attention-action";
import { ConsoleFrame } from "@/components/console-frame";
import { presentAttention } from "@/lib/attention-presenter";
import { getAttentionItem, LiminaApiError } from "@/lib/limina/server";

type PageProps = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ notice?: string }>;
};

export default async function AttentionDetailPage({ params, searchParams }: PageProps) {
  const { id } = await params;
  const { notice } = await searchParams;
  let source;
  try {
    source = await getAttentionItem(id);
  } catch (error) {
    if (error instanceof LiminaApiError && error.status === 404) notFound();
    throw error;
  }
  const item = presentAttention(source, true);
  return (
    <ConsoleFrame activeNav="today" currentProject={source.project}>
      <ActionNotice code={notice as NoticeCode | undefined} />
      <article className="lc-grid">
        <section className="lc-col-5 lc-panel lc-stack lc-stack--5">
          <header className="lc-stack lc-stack--2">
            <p className="tam-eyebrow">{source.kind.replaceAll("_", " ")} · {source.severity}</p>
            <h1 className="lc-display">{source.title}</h1>
            <p className="lc-prose lc-prose--lead">{source.summary}</p>
          </header>
          {source.request ? (
            <div className="lc-field">
              <span className="tam-eyebrow">Requested response</span>
              <span className="lc-meta">{source.request.response_mode.replaceAll("_", " ")}</span>
            </div>
          ) : null}
        </section>
        <aside className="lc-col-3 lc-panel lc-stack lc-stack--4" aria-label="Available actions">
          <h2 className="lc-display lc-display--sm">Respond</h2>
          {item.allowedActions.length ? item.allowedActions.map((action) => (
            <AttentionAction
              action={action}
              item={item}
              source={source}
              interactionSurface="PROJECT_DETAIL"
              key={action.id}
            />
          )) : <p className="lc-prose lc-prose--muted">This item clears automatically when its source changes.</p>}
        </aside>
      </article>
    </ConsoleFrame>
  );
}
import { notFound } from "next/navigation";

import { ActionNotice, type NoticeCode } from "@/components/action-notice";
