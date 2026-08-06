import { ConsoleFrame } from "@/components/console-frame";
import { KnowledgeBrowser } from "@/components/knowledge-browser";
import { ProjectNav } from "@/components/project-nav";
import { getProject, listKnowledge, listSavedKnowledgeViews } from "@/lib/limina/server";

type PageProps = {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ query?: string; kind?: string; status?: string; tag?: string }>;
};

export default async function KnowledgePage({ params, searchParams }: PageProps) {
  const [{ slug }, filters] = await Promise.all([params, searchParams]);
  const [project, knowledge, savedViews] = await Promise.all([
    getProject(slug),
    listKnowledge(slug, filters),
    listSavedKnowledgeViews(slug),
  ]);
  return (
    <ConsoleFrame activeNav="project" currentProject={{ slug, name: project.name }}>
      <ProjectNav slug={slug} active="knowledge" />
      <div className="lc-pagehead">
        <div className="lc-stack lc-stack--2">
          <p className="tam-eyebrow">Evidence desk · {project.name}</p>
          <h1 className="lc-display">Knowledge</h1>
          <p className="lc-prose lc-prose--muted">Hypotheses, experiments, and findings are typed, linked, and auditable by revision.</p>
        </div>
      </div>
      <KnowledgeBrowser
        slug={slug}
        artifacts={knowledge.items}
        query={filters.query}
        kind={filters.kind}
        status={filters.status}
        tag={filters.tag}
        savedViews={savedViews}
        canCollaborate={project.capabilities.includes("knowledge:collaborate")}
      />
    </ConsoleFrame>
  );
}
