import { ConsoleFrame } from "@/components/console-frame";
import { LiveMonitor } from "@/components/live-monitor";
import { ProjectNav } from "@/components/project-nav";
import { getEvents, getProject } from "@/lib/limina/server";

type PageProps = { params: Promise<{ slug: string }> };

export default async function LivePage({ params }: PageProps) {
  const { slug } = await params;
  const [project, events] = await Promise.all([getProject(slug), getEvents(slug)]);
  return (
    <ConsoleFrame activeNav="project" currentProject={{ slug, name: project.name }}>
      <ProjectNav slug={slug} active="live" />
      <LiveMonitor
        slug={slug}
        initialCursor={events.cursor}
        initialEvents={events.events}
        canSteer={project.capabilities.includes("project:lifecycle")}
        allowedActions={project.allowed_actions}
      />
    </ConsoleFrame>
  );
}
