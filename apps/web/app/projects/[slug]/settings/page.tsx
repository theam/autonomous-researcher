import {
  cloneProjectAction,
  setMemberAction,
  setResourceAction,
  setSourceAction,
  updateProjectDraftAction,
} from "@/app/actions";
import { ConsoleFrame } from "@/components/console-frame";
import { NotificationSettings } from "@/components/notification-settings";
import { PendingButton } from "@/components/pending-button";
import { ProjectNav } from "@/components/project-nav";
import { searchOrganizationUsers } from "@/lib/auth/workos-directory";
import { env } from "@/lib/env";
import {
  getPreflight,
  getMe,
  getProject,
  listMembers,
  listNotificationChannels,
  listNotificationDeliveries,
  listNotificationRules,
  listResources,
  listSources,
} from "@/lib/limina/server";

type PageProps = {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ member_query?: string | string[] }>;
};

export default async function ProjectSettingsPage({ params, searchParams }: PageProps) {
  const { slug } = await params;
  const rawMemberQuery = (await searchParams).member_query;
  const selectedMemberQuery = Array.isArray(rawMemberQuery) ? rawMemberQuery[0] : rawMemberQuery;
  const memberQuery = (selectedMemberQuery ?? "")
    .trim()
    .slice(0, 240);
  const [me, project, preflight, resources, sources, members, channels, rules] = await Promise.all([
    getMe(),
    getProject(slug),
    getPreflight(slug),
    listResources(slug),
    listSources(slug),
    listMembers(slug),
    listNotificationChannels(slug),
    listNotificationRules(slug),
  ]);
  const deliveryEntries = await Promise.all(
    channels.map(async (channel) => [channel.id, await listNotificationDeliveries(slug, channel.id)] as const),
  );
  const deliveries = Object.fromEntries(deliveryEntries);
  const canWrite = project.capabilities.includes("resource:write");
  const canWriteSecret = project.capabilities.includes("secret:write");
  const canManageMembers = project.capabilities.includes("member:manage");
  const canManageNotifications = project.capabilities.includes("notification:manage");
  const canClone = me.capabilities.includes("project:create");
  const usesWorkOS = env.LIMINA_UI_AUTH_MODE === "workos";
  const directorySearch =
    canManageMembers && usesWorkOS && me.organization && memberQuery
      ? await searchOrganizationUsers(me.organization.id, memberQuery)
      : { candidates: [], error: null };
  const existingSubjects = new Set(members.map((member) => member.subject));
  const directoryCandidates = directorySearch.candidates.filter(
    (candidate) => !existingSubjects.has(candidate.subject),
  );

  return (
    <ConsoleFrame activeNav="project" currentProject={{ slug, name: project.name }}>
      <ProjectNav slug={slug} active="settings" />
      <div className="lc-pagehead">
        <div>
          <p className="tam-eyebrow">Project administration</p>
          <h1 className="lc-display">Settings</h1>
        </div>
      </div>
      <div className="lc-settings-grid">
        {project.status === "CREATED" && project.capabilities.includes("project:draft-write") ? (
          <section className="lc-panel lc-stack lc-stack--4">
            <h2 className="lc-display lc-display--sm">Kickoff draft</h2>
            <p className="lc-prose lc-prose--muted">
              These fields remain editable until the first start. Saving checks revision {project.version}
              so another operator&apos;s changes cannot be overwritten silently.
            </p>
            <form
              className="lc-stack lc-stack--3"
              action={updateProjectDraftAction.bind(null, slug, project.version)}
            >
              <label className="lc-field">
                <span className="tam-eyebrow">Project name</span>
                <input
                  className="lc-writing-input"
                  name="name"
                  defaultValue={project.name}
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
                  rows={3}
                  required
                />
              </label>
              <label className="lc-field">
                <span className="tam-eyebrow">Context and strongest baseline</span>
                <textarea
                  className="lc-writing-input"
                  name="context"
                  defaultValue={project.context}
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
          </section>
        ) : null}

        <section className="lc-panel lc-stack lc-stack--4">
          <h2 className="lc-display lc-display--sm">Brief and preflight</h2>
          <p className="lc-prose">{project.mission}</p>
          <ul className="lc-activity">
            {preflight.checks.map((check) => (
              <li className="lc-activity__item" key={check.name}>
                <span className="lc-meta">
                  {check.status} · {check.name}
                </span>
                <span>{check.detail}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="lc-panel lc-stack lc-stack--4">
          <h2 className="lc-display lc-display--sm">Sources</h2>
          <ul>
            {sources.map((source) => (
              <li className="lc-settings-row" key={source.id}>
                <span>{source.name}</span>
                <span className="lc-meta">
                  {source.type} · {source.status}
                </span>
              </li>
            ))}
          </ul>
          {canWrite ? (
            <form className="lc-stack lc-stack--3" action={setSourceAction.bind(null, slug)}>
              <input
                className="lc-writing-input"
                name="name"
                aria-label="Source name"
                placeholder="Source name"
                required
              />
              <select className="lc-select" name="type" aria-label="Source type">
                <option value="URL">URL</option>
                <option value="CONNECTOR">Connector</option>
              </select>
              <input
                className="lc-writing-input"
                type="url"
                name="uri"
                aria-label="Source URL"
                placeholder="https://…"
                required
              />
              <PendingButton kind="secondary">Add source</PendingButton>
            </form>
          ) : null}
        </section>

        <section className="lc-panel lc-stack lc-stack--4">
          <h2 className="lc-display lc-display--sm">Variables and secrets</h2>
          <ul>
            {resources.map((resource) => (
              <li className="lc-settings-row" key={resource.name}>
                <span>{resource.name}</span>
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
          {canWrite ? (
            <form
              className="lc-stack lc-stack--3"
              action={setResourceAction.bind(null, slug, "VARIABLE")}
            >
              <input
                className="lc-writing-input"
                name="name"
                aria-label="Variable name"
                placeholder="VARIABLE_NAME"
                required
              />
              <textarea
                className="lc-writing-input"
                name="value"
                aria-label="Variable value"
                rows={2}
                required
              />
              <PendingButton kind="secondary">Set variable</PendingButton>
            </form>
          ) : null}
          {canWriteSecret ? (
            <form
              className="lc-stack lc-stack--3"
              action={setResourceAction.bind(null, slug, "SECRET")}
            >
              <input
                className="lc-writing-input"
                name="name"
                aria-label="Secret name"
                placeholder="SECRET_NAME"
                required
              />
              <input
                className="lc-writing-input"
                type="password"
                name="value"
                aria-label="Secret value"
                autoComplete="new-password"
                required
              />
              <PendingButton kind="secondary">Set write-only secret</PendingButton>
            </form>
          ) : null}
        </section>

        <section className="lc-panel lc-stack lc-stack--4">
          <h2 className="lc-display lc-display--sm">Team</h2>
          <ul>
            {members.map((member) => (
              <li className="lc-settings-row" key={member.subject}>
                <span>{member.display_name}</span>
                <span className="lc-meta">
                  {member.role} · {member.email ?? member.subject}
                </span>
              </li>
            ))}
          </ul>
          {canManageMembers && usesWorkOS ? (
            <div className="lc-stack lc-stack--3">
              <p className="lc-prose lc-prose--muted">
                Search the current WorkOS organization. Limina stores the immutable WorkOS user ID;
                it does not create or invite identities.
              </p>
              {me.organization ? (
                <form className="lc-action-row" method="get">
                  <input
                    className="lc-writing-input"
                    type="search"
                    name="member_query"
                    aria-label="Search organization members"
                    defaultValue={memberQuery}
                    placeholder="Name or exact email"
                    maxLength={240}
                    required
                  />
                  <button className="tam-button tam-button--secondary" type="submit">
                    Search directory
                  </button>
                </form>
              ) : (
                <p className="lc-meta">Your signed session has no WorkOS organization context.</p>
              )}
              {directorySearch.error ? <p className="lc-meta">{directorySearch.error}</p> : null}
              {memberQuery && !directorySearch.error && directoryCandidates.length === 0 ? (
                <p className="lc-meta">No unassigned organization members matched this search.</p>
              ) : null}
              {directoryCandidates.length > 0 ? (
                <ul>
                  {directoryCandidates.map((candidate) => (
                    <li className="lc-settings-row" key={candidate.subject}>
                      <span>
                        {candidate.displayName}
                        <span className="lc-meta"> · {candidate.email}</span>
                      </span>
                      <form
                        className="lc-action-row"
                        action={setMemberAction.bind(null, slug)}
                      >
                        <input type="hidden" name="subject" value={candidate.subject} />
                        <input type="hidden" name="display_name" value={candidate.displayName} />
                        <input type="hidden" name="email" value={candidate.email} />
                        <select
                          className="lc-select"
                          name="role"
                          aria-label={`Role for ${candidate.displayName}`}
                          defaultValue="VIEWER"
                        >
                          <option value="VIEWER">Viewer</option>
                          <option value="EDITOR">Editor</option>
                          <option value="OWNER">Owner</option>
                        </select>
                        <PendingButton kind="secondary">Add member</PendingButton>
                      </form>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
          {canManageMembers && !usesWorkOS ? (
            <div className="lc-stack lc-stack--3">
              <p className="lc-prose lc-prose--muted">
                Local development mode has no identity directory. Add a fixture identity manually;
                production WorkOS mode replaces this form with an organization-scoped picker.
              </p>
            <form className="lc-stack lc-stack--3" action={setMemberAction.bind(null, slug)}>
              <input
                className="lc-writing-input"
                name="subject"
                aria-label="Immutable WorkOS user ID"
                placeholder="WorkOS user ID"
                required
              />
              <input
                className="lc-writing-input"
                name="display_name"
                aria-label="Display name"
                placeholder="Display name"
                required
              />
              <input
                className="lc-writing-input"
                type="email"
                name="email"
                aria-label="Email"
                placeholder="Email (optional)"
              />
              <select className="lc-select" name="role" aria-label="Project role">
                <option value="VIEWER">Viewer</option>
                <option value="EDITOR">Editor</option>
                <option value="OWNER">Owner</option>
              </select>
              <PendingButton kind="secondary">Add existing member</PendingButton>
            </form>
            </div>
          ) : null}
        </section>

        <NotificationSettings
          slug={slug}
          canManage={canManageNotifications}
          channels={channels}
          rules={rules}
          deliveries={deliveries}
        />

        {canClone ? (
          <section className="lc-panel lc-stack lc-stack--4">
            <h2 className="lc-display lc-display--sm">Clone kickoff</h2>
            <p className="lc-prose lc-prose--muted">
              Copy the mission, success criteria, context, and executor into an independent draft.
              Secrets, variables, sources, evidence, members, and notification destinations are not copied.
            </p>
            <form className="lc-stack lc-stack--3" action={cloneProjectAction.bind(null, slug)}>
              <input
                className="lc-writing-input"
                name="name"
                aria-label="Cloned project name"
                placeholder={`${project.name} — copy`}
                required
              />
              <input
                className="lc-writing-input"
                name="slug"
                aria-label="Cloned project slug"
                placeholder={`${slug}-copy`}
                pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                required
              />
              <PendingButton kind="secondary">Create independent draft</PendingButton>
            </form>
          </section>
        ) : null}
      </div>
    </ConsoleFrame>
  );
}
