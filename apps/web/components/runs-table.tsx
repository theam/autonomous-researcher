import { CheckmarkFilled, ErrorFilled, InProgress } from "@carbon/icons-react";
import Link from "next/link";

import { formatDuration, formatRelative, readableTokenCount } from "@/lib/format";
import type { Run } from "@/lib/limina/types";

export function RunsTable({ slug, runs }: { slug: string; runs: Run[] }) {
  return (
    <div className="lc-table-wrap">
      <table className="lc-table">
        <caption className="lc-visually-hidden">Runtime attempts for this project</caption>
        <thead><tr><th>Started</th><th>Status</th><th>Summary</th><th>Model</th><th>Duration</th><th>Attempt</th><th>Usage</th></tr></thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td><Link href={`/projects/${encodeURIComponent(slug)}/runs/${encodeURIComponent(run.id)}`}>{formatRelative(run.started_at)}</Link></td>
              <td><span className="lc-state-inline">{run.status === "COMPLETED" ? <CheckmarkFilled size={16} aria-hidden /> : run.status === "FAILED" ? <ErrorFilled size={16} aria-hidden /> : <InProgress size={16} aria-hidden />}{run.status}</span></td>
              <td className="lc-prose-cell">{run.summary || run.error?.message || "No summary reported"}</td>
              <td>{run.model ?? run.runtime}</td>
              <td>{formatDuration(run.duration_ms)}</td>
              <td>{run.retry_count + 1}</td>
              <td>{readableTokenCount(run.usage.total_tokens)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {runs.length === 0 ? <p className="lc-panel lc-empty">No runtime attempts have been recorded.</p> : null}
    </div>
  );
}
