import Link from "next/link";

import { setResourceAction } from "@/app/actions";
import { PendingButton } from "@/components/pending-button";
import { ProjectSettingsFrame } from "@/components/project-settings-frame";
import { SettingsSection } from "@/components/settings-section";
import { getProject, listResources } from "@/lib/limina/server";

type PageProps = {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ add?: string | string[] }>;
};

export default async function ProjectEnvironmentSettingsPage({ params, searchParams }: PageProps) {
  const { slug } = await params;
  const [project, resources, query] = await Promise.all([
    getProject(slug),
    listResources(slug),
    searchParams,
  ]);
  const canWrite = project.capabilities.includes("resource:write");
  const canWriteSecret = project.capabilities.includes("secret:write");
  const requestedAdd = Array.isArray(query.add) ? query.add[0] : query.add;
  const addVariable = canWrite && requestedAdd === "variable";
  const addSecret = canWriteSecret && requestedAdd === "secret";
  const route = `/projects/${encodeURIComponent(slug)}/settings/environment`;

  return (
    <ProjectSettingsFrame slug={slug} projectName={project.name} active="environment">
      <SettingsSection
        id="environment"
        title="Environment"
        description="Visible variables and write-only secrets supplied to the project runtime."
        action={
          canWrite || canWriteSecret ? (
            <div className="lc-actions">
              {canWrite && !addVariable ? (
                <Link className="tam-button tam-button--outline" href={`${route}?add=variable`}>
                  Add variable
                </Link>
              ) : null}
              {canWriteSecret && !addSecret ? (
                <Link className="tam-button tam-button--outline" href={`${route}?add=secret`}>
                  Set secret
                </Link>
              ) : null}
            </div>
          ) : null
        }
      >
        {addVariable ? (
          <form
            className="lc-settings-form lc-stack lc-stack--4"
            action={setResourceAction.bind(null, slug, "VARIABLE")}
          >
            <div className="lc-settings-form__head">
              <p className="lc-meta">Variables are visible to authorized project members.</p>
              <Link className="lc-text-link" href={route}>
                Cancel
              </Link>
            </div>
            <label className="lc-field">
              <span className="tam-eyebrow">Variable name</span>
              <input
                className="lc-writing-input"
                name="name"
                placeholder="EVAL_SET_URI…"
                autoComplete="off"
                pattern="[A-Z][A-Z0-9_]*"
                spellCheck={false}
                required
              />
            </label>
            <label className="lc-field">
              <span className="tam-eyebrow">Variable value</span>
              <textarea
                className="lc-writing-input"
                name="value"
                autoComplete="off"
                rows={3}
                required
              />
            </label>
            <PendingButton kind="secondary">Set variable</PendingButton>
          </form>
        ) : null}

        {addSecret ? (
          <form
            className="lc-settings-form lc-stack lc-stack--4"
            action={setResourceAction.bind(null, slug, "SECRET")}
          >
            <div className="lc-settings-form__head">
              <p className="lc-meta">Secret values are encrypted and never returned by the API.</p>
              <Link className="lc-text-link" href={route}>
                Cancel
              </Link>
            </div>
            <label className="lc-field">
              <span className="tam-eyebrow">Secret name</span>
              <input
                className="lc-writing-input"
                name="name"
                placeholder="EVAL_TOKEN…"
                autoComplete="off"
                pattern="[A-Z][A-Z0-9_]*"
                spellCheck={false}
                required
              />
            </label>
            <label className="lc-field">
              <span className="tam-eyebrow">Secret value</span>
              <input
                className="lc-writing-input"
                type="password"
                name="value"
                autoComplete="new-password"
                required
              />
            </label>
            <PendingButton kind="secondary">Set write-only secret</PendingButton>
          </form>
        ) : null}

        {resources.length ? (
          <ul className="lc-settings-list">
            {resources.map((resource) => (
              <li className="lc-settings-row" key={resource.name}>
                <span className="lc-meta lc-meta--strong">{resource.name}</span>
                <span className="lc-meta">
                  {resource.type === "SECRET"
                    ? resource.configured
                      ? "Configured · value hidden"
                      : "Not configured"
                    : resource.value}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="lc-settings-empty">No variable or secret is configured.</p>
        )}
      </SettingsSection>
    </ProjectSettingsFrame>
  );
}
