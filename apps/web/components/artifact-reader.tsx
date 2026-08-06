import Link from "next/link";

import { formatTimestamp } from "@/lib/format";
import type {
  Artifact,
  ArtifactComment,
  ArtifactReview,
  ArtifactRevision,
} from "@/lib/limina/types";

type ArtifactReaderProps = {
  artifact: Artifact;
  slug: string;
  revisions: ArtifactRevision[];
  reviews: ArtifactReview[];
  comments: ArtifactComment[];
};

const preferredOrder: Record<string, string[]> = {
  H: ["statement", "mechanism", "generalization", "shortcut_risks", "test_plan", "conclusion"],
  E: ["objective", "procedure", "success_criteria", "guardrails", "results", "analysis", "decision"],
  F: ["finding", "evidence", "improvement", "remaining_debt", "next_move", "impact"],
};

function label(value: string): string {
  return value.replaceAll("_", " ").replace(/^./, (first) => first.toUpperCase());
}

export function ArtifactReader({ artifact, slug, revisions, reviews, comments }: ArtifactReaderProps) {
  const known = preferredOrder[artifact.kind] ?? [];
  const keys = [...known.filter((key) => key in artifact.content), ...Object.keys(artifact.content).filter((key) => !known.includes(key))];
  return (
    <div className="lc-grid">
      <article className="lc-col-5 lc-panel lc-stack lc-stack--5">
        <header className="lc-stack lc-stack--2">
          <span className="lc-hef" data-kind={artifact.kind}>
            <span className="lc-hef__shape" aria-hidden /> {artifact.id} · revision {artifact.version}
          </span>
          <h1 className="lc-display">{artifact.title}</h1>
          <p className="lc-meta">{artifact.status}</p>
        </header>
        {artifact.hypothesis_id || artifact.experiment_id ? (
          <nav className="lc-actions" aria-label="Evidence lineage">
            {artifact.hypothesis_id ? (
              <Link
                className="tam-button tam-button--outline"
                href={`/projects/${encodeURIComponent(slug)}/knowledge/${encodeURIComponent(artifact.hypothesis_id)}`}
              >
                Hypothesis {artifact.hypothesis_id}
              </Link>
            ) : null}
            {artifact.experiment_id ? (
              <Link
                className="tam-button tam-button--outline"
                href={`/projects/${encodeURIComponent(slug)}/knowledge/${encodeURIComponent(artifact.experiment_id)}`}
              >
                Experiment {artifact.experiment_id}
              </Link>
            ) : null}
          </nav>
        ) : null}
        {keys.map((key) => (
          <section className="lc-field" key={key}>
            <h2 className="tam-eyebrow">{label(key)}</h2>
            <p className="lc-prose lc-prose--lead">{String(artifact.content[key] ?? "Not recorded")}</p>
          </section>
        ))}
        {artifact.observations?.length ? (
          <section className="lc-stack lc-stack--3">
            <h2 className="tam-eyebrow">Observations</h2>
            <ol className="lc-activity">
              {artifact.observations.map((observation) => (
                <li className="lc-activity__item" key={observation.id}>
                  <p className="lc-prose">{observation.body}</p>
                  <span className="lc-meta">{observation.actor}</span>
                </li>
              ))}
            </ol>
          </section>
        ) : null}
      </article>
      <aside className="lc-col-3 lc-stack lc-stack--4" aria-label="Evidence context">
        <section className="lc-panel lc-stack lc-stack--3">
          <h2 className="tam-eyebrow">Revision history</h2>
          <ol className="lc-activity">
            {revisions.map((revision) => (
              <li className="lc-activity__item" key={revision.version}>
                <span className="lc-meta">v{revision.version} · {revision.status}</span>
                <span className="lc-prose">{revision.title}</span>
              </li>
            ))}
          </ol>
        </section>
        <section className="lc-panel lc-stack lc-stack--3">
          <h2 className="tam-eyebrow">Discussion</h2>
          {comments.length ? (
            <ol className="lc-activity">
              {comments.map((comment) => (
                <li className="lc-activity__item" key={comment.id}>
                  <p className="lc-prose">{comment.body}</p>
                  <span className="lc-meta">
                    {comment.actor} · {formatTimestamp(comment.created_at)}
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="lc-prose lc-prose--muted">No human discussion has been recorded.</p>
          )}
        </section>
        <section className="lc-panel lc-stack lc-stack--3">
          <h2 className="tam-eyebrow">Human reviews</h2>
          {reviews.length ? (
            <ol className="lc-activity">
              {reviews.map((review) => (
                <li className="lc-activity__item" key={review.id}>
                  <span className="lc-chip" data-role={review.outcome.startsWith("ACCEPT") ? "success" : "warning"}>{review.outcome.replaceAll("_", " ")}</span>
                  <p className="lc-prose">{review.rationale || "Accepted without reservation."}</p>
                  <span className="lc-meta">{review.reviewer_name} · v{review.artifact_version}</span>
                </li>
              ))}
            </ol>
          ) : <p className="lc-prose lc-prose--muted">No human review has been recorded for this evidence.</p>}
        </section>
      </aside>
    </div>
  );
}
