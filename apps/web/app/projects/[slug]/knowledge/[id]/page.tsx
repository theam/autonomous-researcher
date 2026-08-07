import { ConsoleFrame } from "@/components/console-frame";
import { ArtifactReader } from "@/components/artifact-reader";
import { PendingButton } from "@/components/pending-button";
import { addArtifactCommentAction, addArtifactTagAction, reviewArtifactAction } from "@/app/actions";
import {
  getArtifact,
  getArtifactComments,
  getArtifactReviews,
  getArtifactRevisions,
  getProject,
} from "@/lib/limina/server";

type PageProps = { params: Promise<{ slug: string; id: string }> };

export default async function ArtifactPage({ params }: PageProps) {
  const { slug, id } = await params;
  const [project, artifact, revisions, reviews, comments] = await Promise.all([
    getProject(slug),
    getArtifact(slug, id),
    getArtifactRevisions(slug, id),
    getArtifactReviews(slug, id),
    getArtifactComments(slug, id),
  ]);
  const canReview = project.capabilities.includes("artifact:review");
  const canCollaborate = project.capabilities.includes("knowledge:collaborate");
  return (
    <ConsoleFrame
      activeNav="project"
      activeProjectSection="knowledge"
      currentProject={{ slug, name: project.name }}
    >
      <ArtifactReader
        artifact={artifact}
        slug={slug}
        revisions={revisions}
        reviews={reviews}
        comments={comments}
      />
      {canCollaborate ? (
        <section className="lc-review-grid lc-review-form">
          <form
            className="lc-panel lc-stack lc-stack--3"
            action={addArtifactCommentAction.bind(null, slug, id)}
          >
            <h2 className="lc-display lc-display--sm">Discuss this evidence</h2>
            <textarea
              className="lc-writing-input"
              name="body"
              aria-label="Evidence comment"
              rows={4}
              required
            />
            <PendingButton kind="secondary">Add comment</PendingButton>
          </form>
          <form
            className="lc-panel lc-stack lc-stack--3"
            action={addArtifactTagAction.bind(null, slug, id)}
          >
            <h2 className="lc-display lc-display--sm">Tags</h2>
            <p className="lc-meta">{artifact.tags.join(" · ") || "No tags"}</p>
            <input
              className="lc-writing-input"
              name="tag"
              aria-label="Artifact tag"
              placeholder="generalization-risk"
              pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
              required
            />
            <PendingButton kind="secondary">Add tag</PendingButton>
          </form>
        </section>
      ) : null}
      {canReview ? (
        <section className="lc-panel lc-review-form" aria-labelledby="review-heading">
          <div className="lc-stack lc-stack--2">
            <p className="tam-eyebrow">Revision-pinned judgment</p>
            <h2 className="lc-display lc-display--sm" id="review-heading">Review {artifact.id} v{artifact.version}</h2>
          </div>
          <form className="lc-stack lc-stack--3" action={reviewArtifactAction.bind(null, slug, id, artifact.version)}>
            <label className="tam-eyebrow" htmlFor="outcome">Outcome</label>
            <select className="lc-select" id="outcome" name="outcome" defaultValue="NEEDS_MORE_EVIDENCE">
              <option value="ACCEPT">Accept</option>
              <option value="ACCEPT_WITH_RESERVATIONS">Accept with reservations</option>
              <option value="NEEDS_MORE_EVIDENCE">Needs more evidence</option>
              <option value="REJECT">Reject</option>
            </select>
            <label className="tam-eyebrow" htmlFor="rationale">Rationale</label>
            <textarea className="lc-writing-input" id="rationale" name="rationale" rows={5} />
            <label className="tam-eyebrow" htmlFor="guidance">Optional direction to the executor</label>
            <textarea className="lc-writing-input" id="guidance" name="guidance" rows={4} />
            <PendingButton pendingLabel="Recording review…">Record review</PendingButton>
          </form>
        </section>
      ) : null}
    </ConsoleFrame>
  );
}
