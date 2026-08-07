import Link from "next/link";

import { setSourceAction } from "@/app/actions";
import { PendingButton } from "@/components/pending-button";
import { ProjectSettingsFrame } from "@/components/project-settings-frame";
import { SettingsSection } from "@/components/settings-section";
import { getProject, listSources } from "@/lib/limina/server";

type PageProps = {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ add?: string | string[] }>;
};

export default async function ProjectSourcesSettingsPage({ params, searchParams }: PageProps) {
  const { slug } = await params;
  const [project, sources, query] = await Promise.all([
    getProject(slug),
    listSources(slug),
    searchParams,
  ]);
  const canWrite = project.capabilities.includes("resource:write");
  const addSource = canWrite && (Array.isArray(query.add) ? query.add[0] : query.add) === "source";
  const route = `/projects/${encodeURIComponent(slug)}/settings/sources`;

  return (
    <ProjectSettingsFrame slug={slug} projectName={project.name} active="sources">
      <SettingsSection
        id="sources"
        title="Sources"
        description="References and connectors that the executor may read while researching this project."
        action={
          canWrite && !addSource ? (
            <Link className="tam-button tam-button--outline" href={`${route}?add=source`}>
              Add source
            </Link>
          ) : null
        }
      >
        {addSource ? (
          <form
            className="lc-settings-form lc-stack lc-stack--4"
            action={setSourceAction.bind(null, slug)}
          >
            <div className="lc-settings-form__head">
              <p className="lc-meta">Register a URL or connector reference.</p>
              <Link className="lc-text-link" href={route}>
                Cancel
              </Link>
            </div>
            <label className="lc-field">
              <span className="tam-eyebrow">Source name</span>
              <input
                className="lc-writing-input"
                name="name"
                placeholder="Held-out benchmark…"
                autoComplete="off"
                required
              />
            </label>
            <label className="lc-field">
              <span className="tam-eyebrow">Source type</span>
              <select className="lc-select" name="type" defaultValue="URL">
                <option value="URL">URL</option>
                <option value="CONNECTOR">Connector</option>
              </select>
            </label>
            <label className="lc-field">
              <span className="tam-eyebrow">Source URL</span>
              <input
                className="lc-writing-input"
                type="url"
                name="uri"
                placeholder="https://example.com/evidence…"
                autoComplete="off"
                spellCheck={false}
                required
              />
            </label>
            <PendingButton kind="secondary">Add source</PendingButton>
          </form>
        ) : null}

        {sources.length ? (
          <ul className="lc-settings-list">
            {sources.map((source) => (
              <li className="lc-settings-row" key={source.id}>
                <span>{source.name}</span>
                <span className="lc-meta">
                  {source.type} · {source.status}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="lc-settings-empty">No source is registered for this project.</p>
        )}
      </SettingsSection>
    </ProjectSettingsFrame>
  );
}
