import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ActionNotice } from "@/components/action-notice";

afterEach(cleanup);

describe("ActionNotice", () => {
  it("focuses stale-write guidance so keyboard and screen-reader users hear it", async () => {
    const view = render(<ActionNotice code="changed" />);
    const alert = view.getByRole("alert");
    await waitFor(() => expect(document.activeElement).toBe(alert));
    expect(alert.textContent).toContain("changed before your response was saved");
  });

  it("announces a successful resolution without critical semantics", () => {
    const view = render(<ActionNotice code="resolved" />);
    expect(view.getByRole("status").textContent).toContain("response was recorded");
  });
});
