import Link from "next/link";

import { setMemberAction } from "@/app/actions";
import { PendingButton } from "@/components/pending-button";
import { ProjectSettingsFrame } from "@/components/project-settings-frame";
import { SettingsSection } from "@/components/settings-section";
import { searchOrganizationUsers } from "@/lib/auth/workos-directory";
import { env } from "@/lib/env";
import { getMe, getProject, listMembers } from "@/lib/limina/server";

type PageProps = {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{
    add?: string | string[];
    member_query?: string | string[];
  }>;
};

function first(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

export default async function ProjectTeamSettingsPage({ params, searchParams }: PageProps) {
  const { slug } = await params;
  const query = await searchParams;
  const memberQuery = first(query.member_query).trim().slice(0, 240);
  const [me, project, members] = await Promise.all([
    getMe(),
    getProject(slug),
    listMembers(slug),
  ]);
  const canManage = project.capabilities.includes("member:manage");
  const usesWorkOS = env.LIMINA_UI_AUTH_MODE === "workos";
  const addMember = canManage && (first(query.add) === "member" || Boolean(memberQuery));
  const directorySearch =
    addMember && usesWorkOS && me.organization && memberQuery
      ? await searchOrganizationUsers(me.organization.id, memberQuery)
      : { candidates: [], error: null };
  const existingSubjects = new Set(members.map((member) => member.subject));
  const directoryCandidates = directorySearch.candidates.filter(
    (candidate) => !existingSubjects.has(candidate.subject),
  );
  const route = `/projects/${encodeURIComponent(slug)}/settings/team`;

  return (
    <ProjectSettingsFrame slug={slug} projectName={project.name} active="team">
      <SettingsSection
        id="team"
        title="Team"
        description="Project membership is durable and separate from organization-level access."
        action={
          canManage && !addMember ? (
            <Link className="tam-button tam-button--outline" href={`${route}?add=member`}>
              Add member
            </Link>
          ) : null
        }
      >
        {addMember ? (
          <div className="lc-settings-form lc-stack lc-stack--4">
            <div className="lc-settings-form__head">
              <p className="lc-meta">
                {usesWorkOS
                  ? "Search the current WorkOS organization. Limina does not invite identities."
                  : "Local development has no identity directory. Add a fixture identity manually."}
              </p>
              <Link className="lc-text-link" href={route}>
                Cancel
              </Link>
            </div>

            {usesWorkOS ? (
              me.organization ? (
                <>
                  <form className="lc-action-row" method="get">
                    <input type="hidden" name="add" value="member" />
                    <label className="lc-field lc-field--grow">
                      <span className="tam-eyebrow">Organization member</span>
                      <input
                        className="lc-writing-input"
                        type="search"
                        name="member_query"
                        defaultValue={memberQuery}
                        placeholder="Name or exact email…"
                        autoComplete="off"
                        spellCheck={false}
                        maxLength={240}
                        required
                      />
                    </label>
                    <button className="tam-button tam-button--outline" type="submit">
                      Search Directory
                    </button>
                  </form>
                  {directorySearch.error ? (
                    <p className="lc-error" role="alert">
                      {directorySearch.error}
                    </p>
                  ) : null}
                  {memberQuery && !directorySearch.error && directoryCandidates.length === 0 ? (
                    <p className="lc-meta">No unassigned organization member matched this search.</p>
                  ) : null}
                  {directoryCandidates.length ? (
                    <ul className="lc-settings-list">
                      {directoryCandidates.map((candidate) => (
                        <li className="lc-settings-row lc-settings-row--action" key={candidate.subject}>
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
                </>
              ) : (
                <p className="lc-meta">Your signed session has no WorkOS organization context.</p>
              )
            ) : (
              <form className="lc-stack lc-stack--4" action={setMemberAction.bind(null, slug)}>
                <label className="lc-field">
                  <span className="tam-eyebrow">Immutable WorkOS user ID</span>
                  <input
                    className="lc-writing-input"
                    name="subject"
                    placeholder="user_01H…"
                    autoComplete="off"
                    spellCheck={false}
                    required
                  />
                </label>
                <label className="lc-field">
                  <span className="tam-eyebrow">Display name</span>
                  <input
                    className="lc-writing-input"
                    name="display_name"
                    placeholder="Ada Lovelace…"
                    autoComplete="off"
                    required
                  />
                </label>
                <label className="lc-field">
                  <span className="tam-eyebrow">Email</span>
                  <input
                    className="lc-writing-input"
                    type="email"
                    name="email"
                    placeholder="ada@example.com…"
                    autoComplete="off"
                    spellCheck={false}
                  />
                </label>
                <label className="lc-field">
                  <span className="tam-eyebrow">Project role</span>
                  <select className="lc-select" name="role" defaultValue="VIEWER">
                    <option value="VIEWER">Viewer</option>
                    <option value="EDITOR">Editor</option>
                    <option value="OWNER">Owner</option>
                  </select>
                </label>
                <PendingButton kind="secondary">Add existing member</PendingButton>
              </form>
            )}
          </div>
        ) : null}

        <ul className="lc-settings-list">
          {members.map((member) => (
            <li className="lc-settings-row" key={member.subject}>
              <span>{member.display_name}</span>
              <span className="lc-meta">
                {member.role} · {member.email ?? member.subject}
              </span>
            </li>
          ))}
        </ul>
      </SettingsSection>
    </ProjectSettingsFrame>
  );
}
