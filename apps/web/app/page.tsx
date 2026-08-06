import Link from "next/link";

import { ActionNotice, type NoticeCode } from "@/components/action-notice";
import { AttentionAction } from "@/components/attention-action";
import { AttentionDesk, type DeskAction, type DeskItem } from "@/components/attention-desk";
import { ConsoleFrame } from "@/components/console-frame";
import { StreamHealth } from "@/components/stream-health";
import { presentAttention } from "@/lib/attention-presenter";
import { formatRelative } from "@/lib/format";
import { listAttention, listProjects } from "@/lib/limina/server";

type PageProps = { searchParams: Promise<{ item?: string; notice?: string }> };

function isAttentionStale(lastSyncedAt: string): boolean {
  const syncedAt = Date.parse(lastSyncedAt);
  return !Number.isFinite(syncedAt) || Date.now() - syncedAt > 2 * 60 * 1_000;
}

export default async function TodayPage({ searchParams }: PageProps) {
  const [{ item: selectedId, notice }, attention, projects] = await Promise.all([
    searchParams,
    listAttention(),
    listProjects(),
  ]);
  const selected = selectedId ?? attention.items.at(0)?.id;
  const presented = attention.items.map((item) => presentAttention(item, item.id === selected));
  const byId = new Map(attention.items.map((item) => [item.id, item]));

  function renderAction(action: DeskAction, item: DeskItem) {
    const source = byId.get(item.id);
    return source ? (
      <AttentionAction
        action={action}
        item={item}
        source={source}
        interactionSurface="TODAY"
      />
    ) : null;
  }

  return (
    <ConsoleFrame activeNav="today">
      <ActionNotice code={notice as NoticeCode | undefined} />
      <div className="lc-today-health"><StreamHealth /></div>
      <AttentionDesk
        items={presented}
        freshness={{
          lastSyncedLabel: formatRelative(attention.last_synced_at),
          stale: isAttentionStale(attention.last_synced_at),
        }}
        digest={projects.items.length ? [`${projects.items.length} visible project${projects.items.length === 1 ? "" : "s"}`] : ["No projects yet"]}
        renderAction={renderAction}
      />
      <nav className="lc-secondary-nav" aria-label="Today shortcuts">
        <Link href="/projects">View all projects</Link>
        <Link href="/new">Start a project</Link>
      </nav>
    </ConsoleFrame>
  );
}
