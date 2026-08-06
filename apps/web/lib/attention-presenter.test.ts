import { describe, expect, it } from "vitest";

import { presentAttention } from "@/lib/attention-presenter";
import type { AttentionItem } from "@/lib/limina/types";

const item: AttentionItem = {
  id: "attention/id",
  kind: "agent_request",
  project: { slug: "retrieval", name: "Retrieval" },
  severity: "HIGH",
  title: "Choose a baseline",
  summary: "The executor needs a fair comparator.",
  status: "OPEN",
  source: {
    request_id: "request-1",
    artifact_id: null,
    artifact_version: null,
    run_id: null,
    event_sequence: null,
  },
  request: {
    kind: "QUESTION",
    response_mode: "CHOICE",
    choices: ["BM25", "Hybrid"],
  },
  allowed_actions: ["SELECT", "SNOOZE"],
  version: 2,
  opened_at: "2026-08-06T09:00:00Z",
  updated_at: "2026-08-06T09:00:00Z",
};

describe("presentAttention", () => {
  it("preserves server authority while mapping presentation intent", () => {
    const presented = presentAttention(item, true);
    expect(presented.selected).toBe(true);
    expect(presented.allowedActions).toEqual([
      { id: "SELECT", label: "Choose", intent: "primary" },
      { id: "SNOOZE", label: "Snooze", intent: "neutral" },
    ]);
    expect(presented.responseMode).toBe("CHOICE");
    expect(presented.choices).toEqual(["BM25", "Hybrid"]);
    expect(presented.href).toBe("/?item=attention%2Fid");
    expect(presented.version).toBe(2);
  });

  it("presents rejection as a critical executor decision", () => {
    const presented = presentAttention(
      { ...item, allowed_actions: ["CONFIRM", "REJECT"] },
      false,
    );
    expect(presented.allowedActions).toEqual([
      { id: "CONFIRM", label: "Confirm", intent: "primary" },
      { id: "REJECT", label: "Reject", intent: "critical" },
    ]);
  });
});
