import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AttentionDesk } from "@/components/attention-desk";

afterEach(cleanup);

describe("AttentionDesk empty state", () => {
  it("does not claim the queue is empty when freshness is stale", () => {
    const view = render(
      <AttentionDesk
        items={[]}
        freshness={{ lastSyncedLabel: "2 minutes ago", stale: true }}
      />,
    );
    expect(view.container.textContent).toContain("This queue may be incomplete.");
    expect(view.container.textContent).not.toContain("No attention was pending");
  });

  it("scopes the healthy empty claim to the last successful sync", () => {
    const view = render(
      <AttentionDesk items={[]} freshness={{ lastSyncedLabel: "now", stale: false }} />,
    );
    expect(view.container.textContent).toContain("No attention was pending at the last sync.");
  });
});
