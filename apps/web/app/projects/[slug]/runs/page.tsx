import { ConsoleFrame } from "@/components/console-frame";
import { RunsTable } from "@/components/runs-table";
import { getProject, listRuns } from "@/lib/limina/server";

type PageProps = { params: Promise<{ slug: string }> };

export default async function RunsPage({ params }: PageProps) {
  const { slug } = await params;
  const [project, runs] = await Promise.all([getProject(slug), listRuns(slug)]);
  return (
    <ConsoleFrame
      activeNav="project"
      activeProjectSection="runs"
      currentProject={{ slug, name: project.name }}
    >
      <div className="lc-pagehead">
        <div className="lc-stack lc-stack--2">
          <p className="tam-eyebrow">Diagnostics · {project.name}</p>
          <h1 className="lc-display">Runtime attempts</h1>
          <p className="lc-prose lc-prose--muted">Normalized outcomes, retry lineage, duration, and honest usage availability.</p>
        </div>
      </div>
      <RunsTable slug={slug} runs={runs.items} />
    </ConsoleFrame>
  );
}
