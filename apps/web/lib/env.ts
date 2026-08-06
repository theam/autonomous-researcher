import "server-only";

import { parseConsoleEnv } from "@/lib/env-schema";

export const env = parseConsoleEnv({
  LIMINA_UI_AUTH_MODE: process.env.LIMINA_UI_AUTH_MODE,
  LIMINA_RUNTIME_URL: process.env.LIMINA_RUNTIME_URL,
  LIMINA_CONSOLE_ORIGIN: process.env.LIMINA_CONSOLE_ORIGIN,
  LIMINA_DEV_JWT_SECRET: process.env.LIMINA_DEV_JWT_SECRET,
  LIMINA_DEV_JWT_ORGANIZATION_ID: process.env.LIMINA_DEV_JWT_ORGANIZATION_ID,
  LIMINA_DEV_SESSION_SECRET: process.env.LIMINA_DEV_SESSION_SECRET,
  LIMINA_ALLOW_LOCAL_AUTH: process.env.LIMINA_ALLOW_LOCAL_AUTH,
  NODE_ENV: process.env.NODE_ENV,
});

export function requireDevJwtSecret(): Uint8Array {
  if (env.LIMINA_UI_AUTH_MODE !== "local") {
    throw new Error("The developer JWT secret is available only in local Console mode.");
  }
  if (!env.LIMINA_DEV_JWT_SECRET) {
    throw new Error("LIMINA_DEV_JWT_SECRET is required in local Console mode.");
  }
  return new TextEncoder().encode(env.LIMINA_DEV_JWT_SECRET);
}
