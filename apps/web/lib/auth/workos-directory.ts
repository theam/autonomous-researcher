import "server-only";

import { getWorkOS } from "@workos-inc/authkit-nextjs";

export type OrganizationUserCandidate = {
  subject: string;
  displayName: string;
  email: string;
};

export type OrganizationUserSearch = {
  candidates: OrganizationUserCandidate[];
  error: string | null;
};

const EXACT_EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export async function searchOrganizationUsers(
  organizationId: string,
  rawQuery: string,
): Promise<OrganizationUserSearch> {
  const query = rawQuery.trim().slice(0, 240);
  if (!query) return { candidates: [], error: null };

  try {
    const result = await getWorkOS().userManagement.listUsers({
      organizationId,
      limit: 100,
      ...(EXACT_EMAIL.test(query) ? { email: query } : {}),
    });
    const needle = query.toLocaleLowerCase();
    const candidates = result.data
      .map((user) => {
        const displayName = [user.firstName, user.lastName].filter(Boolean).join(" ").trim();
        return {
          subject: user.id,
          displayName: displayName || user.email,
          email: user.email,
        };
      })
      .filter((user) =>
        [user.displayName, user.email, user.subject].some((value) =>
          value.toLocaleLowerCase().includes(needle),
        ),
      )
      .sort((left, right) => left.displayName.localeCompare(right.displayName));
    return { candidates, error: null };
  } catch (error) {
    console.error("WorkOS organization directory lookup failed", { error });
    return {
      candidates: [],
      error: "The organization directory could not be searched. Try again or check WorkOS access.",
    };
  }
}
