import { ConsoleFrame } from "@/components/console-frame";
import { ProjectNav } from "@/components/project-nav";
import { getProject, getRun } from "@/lib/limina/server";
import { formatDuration, formatTimestamp, readableTokenCount } from "@/lib/format";

type PageProps = { params: Promise<{ slug: string; runId: string }> };

export default async function RunDetailPage({ params }: PageProps) {
  const { slug, runId } = await params;
  const [project, run] = await Promise.all([getProject(slug), getRun(slug, runId)]);
  return (
    <ConsoleFrame activeNav="project" currentProject={{ slug, name: project.name }}>
      <ProjectNav slug={slug} active="runs" />
      <article className="lc-grid">
        <section className="lc-col-5 lc-panel lc-stack lc-stack--5">
          <header className="lc-stack lc-stack--2">
            <p className="tam-eyebrow">Attempt {run.retry_count + 1} · {run.runtime}</p>
            <h1 className="lc-display">{run.summary || "Runtime attempt"}</h1>
            <span className="lc-chip" data-role={run.status === "FAILED" ? "critical" : run.status === "COMPLETED" ? "success" : "info"}>{run.status}</span>
          </header>
          {run.error ? <div className="lc-blocker"><p className="tam-eyebrow">Normalized failure</p><p className="lc-prose">{run.error.message ?? "No safe error detail was reported."}</p><span className="lc-meta">{run.error.code ?? "UNCLASSIFIED"}</span></div> : null}
          <section><h2 className="tam-eyebrow">Sanitized events</h2><ol className="lc-activity">{run.events.map((event) => <li className="lc-activity__item" key={event.sequence}><span className="lc-meta">#{event.sequence} · {event.type} · {event.actor}</span><p className="lc-prose">{String(event.detail.summary ?? event.detail.status ?? "State changed")}</p></li>)}</ol></section>
        </section>
        <aside className="lc-col-3 lc-panel lc-stack lc-stack--4" aria-label="Run facts">
          <div className="lc-field"><span className="tam-eyebrow">Started</span><time>{formatTimestamp(run.started_at)}</time></div>
          <div className="lc-field"><span className="tam-eyebrow">Duration</span><span>{formatDuration(run.duration_ms)}</span></div>
          <div className="lc-field"><span className="tam-eyebrow">Model</span><span>{run.model ?? "Not reported"}</span></div>
          <div className="lc-field"><span className="tam-eyebrow">Tool calls</span><span>{run.tool_calls}</span></div>
          <div className="lc-field"><span className="tam-eyebrow">Total tokens</span><span>{readableTokenCount(run.usage.total_tokens)}</span><small className="lc-meta">{run.usage.usage_source ?? "Not reported by provider"}</small></div>
        </aside>
      </article>
    </ConsoleFrame>
  );
}
