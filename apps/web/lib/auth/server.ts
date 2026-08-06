import "server-only";

import { withAuth } from "@workos-inc/authkit-nextjs";
import { SignJWT, jwtVerify } from "jose";
import { cookies } from "next/headers";
import { cache } from "react";

import { env, requireDevJwtSecret } from "@/lib/env";

const DEV_SESSION_COOKIE = "limina-dev-session";
const DEV_ISSUER = "urn:limina:dev";
const DEV_AUDIENCE = "limina-api";
const DEV_SESSION_AUDIENCE = "limina-console";

export type ConsoleIdentity = {
  subject: string;
  displayName: string;
  email: string | null;
  permissions: string[];
  authMode: "local" | "workos";
};

export type ConsoleSession = {
  identity: ConsoleIdentity;
  accessToken: string;
};

const defaultLocalIdentity: ConsoleIdentity = {
  subject: "local_operator",
  displayName: "Local operator",
  email: "operator@localhost",
  permissions: ["limina:access", "limina:project-create"],
  authMode: "local",
};

async function localIdentity(): Promise<ConsoleIdentity> {
  const cookieStore = await cookies();
  const sealed = cookieStore.get(DEV_SESSION_COOKIE)?.value;
  if (!sealed) return defaultLocalIdentity;

  try {
    const { payload } = await jwtVerify(sealed, requireDevJwtSecret(), {
      issuer: DEV_ISSUER,
      audience: DEV_SESSION_AUDIENCE,
      algorithms: ["HS256"],
    });
    if (
      typeof payload.sub !== "string" ||
      typeof payload.name !== "string" ||
      !Array.isArray(payload.permissions) ||
      payload.permissions.some((permission) => typeof permission !== "string")
    ) {
      return defaultLocalIdentity;
    }
    return {
      subject: payload.sub,
      displayName: payload.name,
      email: typeof payload.email === "string" ? payload.email : null,
      permissions: payload.permissions as string[],
      authMode: "local",
    };
  } catch {
    return defaultLocalIdentity;
  }
}

async function localAccessToken(identity: ConsoleIdentity): Promise<string> {
  return new SignJWT({
    name: identity.displayName,
    email: identity.email,
    org_id: env.LIMINA_DEV_JWT_ORGANIZATION_ID,
    permissions: identity.permissions,
  })
    .setProtectedHeader({ alg: "HS256", typ: "JWT" })
    .setSubject(identity.subject)
    .setIssuer(DEV_ISSUER)
    .setAudience(DEV_AUDIENCE)
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(requireDevJwtSecret());
}

export const getConsoleSession = cache(async (): Promise<ConsoleSession> => {
  if (env.LIMINA_UI_AUTH_MODE === "local") {
    const identity = await localIdentity();
    return { identity, accessToken: await localAccessToken(identity) };
  }

  const auth = await withAuth({ ensureSignedIn: true });
  if (!auth.accessToken || !auth.user) {
    throw new Error("Your WorkOS session is unavailable. Sign in again.");
  }
  const name = [auth.user.firstName, auth.user.lastName].filter(Boolean).join(" ").trim();
  return {
    identity: {
      subject: auth.user.id,
      displayName: name || auth.user.email,
      email: auth.user.email,
      permissions: auth.permissions ?? [],
      authMode: "workos",
    },
    accessToken: auth.accessToken,
  };
});
