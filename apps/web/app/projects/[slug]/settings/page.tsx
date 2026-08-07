import Link from "next/link";

import { cloneProjectAction, updateProjectDraftAction } from "@/app/actions";
import { PendingButton } from "@/components/pending-button";
import { ProjectSettingsFrame } from "@/components/project-settings-frame";
import { SettingsSection } from "@/components/settings-section";
import { getMe, getProject } from "@/lib/limina/server";

type PageProps = {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ edit?: string | string[]; clone?: string | string[] }>;
};

function isOpen(value: string | string[] | undefined): boolean {
  return (Array.isArray(value) ? value[0] : value) === "1";
}

export default async function ProjectSettingsPage({ params, searchParams }: PageProps) {
  const { slug } = await params;
  const query = await searchParams;
  const [me, project] = await Promise.all([getMe(), getProject(slug)]);
  const canEditDraft =
    project.status === "CREATED" && project.capabilities.includes("project:draft-write");
  const canClone = me.capabilities.includes("project:create");
  const editDraft = canEditDraft && isOpen(query.edit);
  const cloneProject = canClone && isOpen(query.clone);
  const settingsPath = `/projects/${encodeURIComponent(slug)}/settings`;

  return (
    <ProjectSettingsFrame slug={slug} projectName={project.name} active="general">
      <SettingsSection
        id="general"
        title="General"
        description="Project identity, research brief, and executor. The brief becomes immutable after the first start."
        action={
          canEditDraft && !editDraft ? (
            <Link className="tam-button tam-button--outline" href={`${settingsPath}?edit=1`}>
              Edit draft
            </Link>
          ) : null
        }
      >
        {editDraft ? (
          <form
            className="lc-settings-form lc-stack lc-stack--4"
            action={updateProjectDraftAction.bind(null, slug, project.version)}
          >
            <div className="lc-settings-form__head">
              <p className="lc-meta">
                Saving checks revision {project.version} so another operator&apos;s changes cannot
                be overwritten silently.
              </p>
              <Link className="lc-text-link" href={settingsPath}>
                Cancel
              </Link>
            </div>
            <label className="lc-field">
              <span className="tam-eyebrow">Project name</span>
              <input
                className="lc-writing-input"
                name="name"
                defaultValue={project.name}
                autoComplete="off"
                maxLength={240}
                required
              />
            </label>
            <label className="lc-field">
              <span className="tam-eyebrow">Mission</span>
              <textarea
                className="lc-writing-input"
                name="mission"
                defaultValue={project.mission}
                autoComplete="off"
                rows={4}
                required
              />
            </label>
            <label className="lc-field">
              <span className="tam-eyebrow">Success criteria</span>
              <textarea
                className="lc-writing-input"
                name="success_criteria"
                defaultValue={project.success_criteria}
                autoComplete="off"
                rows={3}
                required
              />
            </label>
            <label className="lc-field">
              <span className="tam-eyebrow">Context & strongest baseline</span>
              <textarea
                className="lc-writing-input"
                name="context"
                defaultValue={project.context}
                autoComplete="off"
                rows={4}
              />
            </label>
            <label className="lc-field">
              <span className="tam-eyebrow">Executor</span>
              <select className="lc-select" name="runtime" defaultValue={project.runtime}>
                <option value="codex">Codex</option>
                <option value="claude-code">Claude Code</option>
              </select>
            </label>
            <PendingButton kind="secondary">Save draft</PendingButton>
          </form>
        ) : (
          <dl className="lc-definition-list">
            <div className="lc-definition-row">
              <dt>Name</dt>
              <dd>{project.name}</dd>
            </div>
            <div className="lc-definition-row">
              <dt>Mission</dt>
              <dd>{project.mission}</dd>
            </div>
            <div className="lc-definition-row">
              <dt>Success criteria</dt>
              <dd>{project.success_criteria}</dd>
            </div>
            <div className="lc-definition-row">
              <dt>Executor</dt>
              <dd className="lc-meta lc-meta--strong">{project.runtime}</dd>
            </div>
            <div className="lc-definition-row">
              <dt>Status</dt>
              <dd className="lc-meta lc-meta--strong">{project.status}</dd>
            </div>
          </dl>
        )}
      </SettingsSection>

      {canClone ? (
        <SettingsSection
          id="clone"
          title="Clone project"
          description="Create an independent draft from this brief. Evidence, members, inputs, secrets, and notification destinations are not copied."
          action={
            !cloneProject ? (
              <Link className="tam-button tam-button--outline" href={`${settingsPath}?clone=1`}>
                Clone project
              </Link>
            ) : null
          }
        >
          {cloneProject ? (
            <form
              className="lc-settings-form lc-stack lc-stack--4"
              action={cloneProjectAction.bind(null, slug)}
            >
              <div className="lc-settings-form__head">
                <p className="lc-meta">Choose a new name and stable URL slug.</p>
                <Link className="lc-text-link" href={settingsPath}>
                  Cancel
                </Link>
              </div>
              <label className="lc-field">
                <span className="tam-eyebrow">Project name</span>
                <input
                  className="lc-writing-input"
                  name="name"
                  placeholder={`${project.name} — copy…`}
                  autoComplete="off"
                  required
                />
              </label>
              <label className="lc-field">
                <span className="tam-eyebrow">Stable slug</span>
                <input
                  className="lc-writing-input"
                  name="slug"
                  placeholder={`${slug}-copy…`}
                  autoComplete="off"
                  pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                  spellCheck={false}
                  required
                />
              </label>
              <PendingButton kind="secondary">Create independent draft</PendingButton>
            </form>
          ) : (
            <p className="lc-meta">The source project is never changed by cloning.</p>
          )}
        </SettingsSection>
      ) : null}
    </ProjectSettingsFrame>
  );
}
