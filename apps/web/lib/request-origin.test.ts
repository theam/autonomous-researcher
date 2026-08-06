import { describe, expect, it } from "vitest";

import { isTrustedMutationOrigin } from "@/lib/request-origin";

describe("isTrustedMutationOrigin", () => {
  const configured = "http://127.0.0.1:7433";

  it("accepts an exact same origin", () => {
    const request = new Request("http://127.0.0.1:7433/api/ticket", {
      headers: { origin: configured },
    });
    expect(isTrustedMutationOrigin(request, configured)).toBe(true);
  });

  it("rejects missing, malformed, and cross-site origins", () => {
    expect(
      isTrustedMutationOrigin(new Request("http://127.0.0.1:7433/api/ticket"), configured),
    ).toBe(false);
    expect(
      isTrustedMutationOrigin(
        new Request("http://127.0.0.1:7433/api/ticket", {
          headers: { origin: "not a URL" },
        }),
        configured,
      ),
    ).toBe(false);
    expect(
      isTrustedMutationOrigin(
        new Request("http://127.0.0.1:7433/api/ticket", {
          headers: { origin: "https://attacker.example" },
        }),
        configured,
      ),
    ).toBe(false);
  });
});
