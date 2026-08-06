import { z } from "zod";

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);

const schema = z
  .object({
    LIMINA_UI_AUTH_MODE: z.enum(["local", "workos"]).default("local"),
    LIMINA_RUNTIME_URL: z.string().url().default("http://127.0.0.1:7434"),
    LIMINA_CONSOLE_ORIGIN: z.string().url().default("http://127.0.0.1:7433"),
    LIMINA_DEV_JWT_SECRET: z.string().min(32).optional(),
    LIMINA_DEV_JWT_ORGANIZATION_ID: z.string().min(1).default("org_local"),
    LIMINA_DEV_SESSION_SECRET: z.string().min(32).optional(),
    LIMINA_ALLOW_LOCAL_AUTH: z.enum(["0", "1"]).default("0"),
    NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  })
  .superRefine((value, context) => {
    if (value.LIMINA_UI_AUTH_MODE !== "local") return;
    const hostname = new URL(value.LIMINA_CONSOLE_ORIGIN).hostname;
    if (!LOOPBACK_HOSTS.has(hostname)) {
      context.addIssue({
        code: "custom",
        path: ["LIMINA_CONSOLE_ORIGIN"],
        message: "Local Console authentication is restricted to a loopback origin.",
      });
    }
    if (value.NODE_ENV === "production" && value.LIMINA_ALLOW_LOCAL_AUTH !== "1") {
      context.addIssue({
        code: "custom",
        path: ["LIMINA_ALLOW_LOCAL_AUTH"],
        message:
          "Production local auth requires LIMINA_ALLOW_LOCAL_AUTH=1 and remains loopback-only.",
      });
    }
  });

export function parseConsoleEnv(source: NodeJS.ProcessEnv) {
  return schema.parse(source);
}
