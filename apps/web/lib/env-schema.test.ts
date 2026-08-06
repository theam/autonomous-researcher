import { describe, expect, it } from "vitest";

import { parseConsoleEnv } from "@/lib/env-schema";

describe("Console environment boundary", () => {
  it("requires an explicit acknowledgement for production local auth", () => {
    expect(() =>
      parseConsoleEnv({
        NODE_ENV: "production",
        LIMINA_UI_AUTH_MODE: "local",
        LIMINA_CONSOLE_ORIGIN: "http://127.0.0.1:7433",
      }),
    ).toThrow(/LIMINA_ALLOW_LOCAL_AUTH=1/);
  });

  it("never permits local auth on a non-loopback origin", () => {
    expect(() =>
      parseConsoleEnv({
        NODE_ENV: "production",
        LIMINA_UI_AUTH_MODE: "local",
        LIMINA_ALLOW_LOCAL_AUTH: "1",
        LIMINA_CONSOLE_ORIGIN: "https://limina.example.com",
      }),
    ).toThrow(/loopback origin/);
  });

  it("allows an explicitly acknowledged loopback production instance", () => {
    const value = parseConsoleEnv({
      NODE_ENV: "production",
      LIMINA_UI_AUTH_MODE: "local",
      LIMINA_ALLOW_LOCAL_AUTH: "1",
      LIMINA_CONSOLE_ORIGIN: "http://localhost:7433",
    });
    expect(value.LIMINA_UI_AUTH_MODE).toBe("local");
  });

  it("allows WorkOS on a network origin without the local acknowledgement", () => {
    const value = parseConsoleEnv({
      NODE_ENV: "production",
      LIMINA_UI_AUTH_MODE: "workos",
      LIMINA_CONSOLE_ORIGIN: "https://limina.example.com",
    });
    expect(value.LIMINA_UI_AUTH_MODE).toBe("workos");
  });
});
