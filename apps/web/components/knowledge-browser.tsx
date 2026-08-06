import { Search } from "@carbon/icons-react";
import Link from "next/link";

import { saveKnowledgeViewAction } from "@/app/actions";
import { PendingButton } from "@/components/pending-button";
import { formatRelative } from "@/lib/format";
import type { Artifact, SavedKnowledgeView } from "@/lib/limina/types";

type KnowledgeBrowserProps = {
  slug: string;
  artifacts: Artifact[];
  query?: string;
  kind?: string;
  status?: string;
  tag?: string;
  savedViews: SavedKnowledgeView[];
  canCollaborate: boolean;
};

export function KnowledgeBrowser({
  slug,
  artifacts,
  query = "",
  kind = "",
  status = "",
  tag = "",
  savedViews,
  canCollaborate,
}: KnowledgeBrowserProps) {
  return (
    <div className="lc-stack lc-stack--5">
      <form className="lc-filterbar" method="get" role="search">
        <label className="lc-visually-hidden" htmlFor="knowledge-query">Search knowledge</label>
        <span className="lc-search-field">
          <Search size={16} aria-hidden />
          <input id="knowledge-query" name="query" defaultValue={query} placeholder="Search evidence" />
        </span>
        <label className="lc-visually-hidden" htmlFor="knowledge-kind">Artifact kind</label>
        <select className="lc-select" id="knowledge-kind" name="kind" defaultValue={kind}>
          <option value="">All kinds</option>
          <option value="H">Hypotheses</option>
          <option value="E">Experiments</option>
          <option value="F">Findings</option>
        </select>
        <label className="lc-visually-hidden" htmlFor="knowledge-status">Artifact status</label>
        <input
          className="lc-writing-input"
          id="knowledge-status"
          name="status"
          defaultValue={status}
          placeholder="Status"
        />
        <label className="lc-visually-hidden" htmlFor="knowledge-tag">Artifact tag</label>
        <input
          className="lc-writing-input"
          id="knowledge-tag"
          name="tag"
          defaultValue={tag}
          placeholder="Tag"
        />
        <button className="tam-button tam-button--outline" type="submit">Apply</button>
      </form>

      {savedViews.length > 0 || canCollaborate ? (
        <section className="lc-panel lc-stack lc-stack--3" aria-labelledby="saved-views-title">
          <h2 className="tam-eyebrow" id="saved-views-title">Saved views</h2>
          {savedViews.length > 0 ? (
            <nav className="lc-actions" aria-label="Saved knowledge filters">
              {savedViews.map((view) => (
                <Link
                  className="tam-button tam-button--outline"
                  href={{ pathname: `/projects/${slug}/knowledge`, query: view.query as Record<string, string> }}
                  key={view.id}
                >
                  {view.name}
                </Link>
              ))}
            </nav>
          ) : (
            <p className="lc-meta">No saved evidence filters.</p>
          )}
          {canCollaborate ? (
            <form className="lc-actions" action={saveKnowledgeViewAction.bind(null, slug)}>
              <input
                className="lc-writing-input"
                name="name"
                aria-label="Saved view name"
                placeholder="View name"
                required
              />
              <input type="hidden" name="query" value={query} />
              <input type="hidden" name="kind" value={kind} />
              <input type="hidden" name="status" value={status} />
              <input type="hidden" name="tag" value={tag} />
              <PendingButton kind="secondary">Save current filters</PendingButton>
            </form>
          ) : null}
        </section>
      ) : null}

      {artifacts.length === 0 ? (
        <div className="lc-panel lc-empty">
          <p className="lc-display lc-display--sm">No matching evidence</p>
          <p className="lc-prose lc-prose--muted">Adjust the filters or return after the runtime publishes an artifact.</p>
        </div>
      ) : (
        <ol className="lc-evidence-list">
          {artifacts.map((artifact) => (
            <li key={artifact.id}>
              <Link
                className="lc-evidence-row"
                href={`/projects/${encodeURIComponent(slug)}/knowledge/${encodeURIComponent(artifact.id)}`}
              >
                <span className="lc-hef" data-kind={artifact.kind}>
                  <span className="lc-hef__shape" aria-hidden />
                  <span>{artifact.id}</span>
                </span>
                <span>
                  <strong className="lc-prose">{artifact.title}</strong>
                  <span className="lc-meta">{artifact.status} · revision {artifact.version}</span>
                </span>
                <time className="lc-meta" dateTime={artifact.updated_at}>{formatRelative(artifact.updated_at)}</time>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
