import { NotificationSettings } from "@/components/notification-settings";
import { ProjectSettingsFrame } from "@/components/project-settings-frame";
import {
  getProject,
  listNotificationChannels,
  listNotificationDeliveries,
  listNotificationRules,
} from "@/lib/limina/server";

type PageProps = {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ add?: string | string[] }>;
};

export default async function ProjectNotificationsSettingsPage({
  params,
  searchParams,
}: PageProps) {
  const { slug } = await params;
  const [project, channels, rules, query] = await Promise.all([
    getProject(slug),
    listNotificationChannels(slug),
    listNotificationRules(slug),
    searchParams,
  ]);
  const deliveryEntries = await Promise.all(
    channels.map(
      async (channel) =>
        [channel.id, await listNotificationDeliveries(slug, channel.id)] as const,
    ),
  );
  const add = Array.isArray(query.add) ? query.add[0] : query.add;
  const canManage = project.capabilities.includes("notification:manage");
  const basePath = `/projects/${encodeURIComponent(slug)}/settings/notifications`;

  return (
    <ProjectSettingsFrame slug={slug} projectName={project.name} active="notifications">
      <NotificationSettings
        slug={slug}
        canManage={canManage}
        channels={channels}
        rules={rules}
        deliveries={Object.fromEntries(deliveryEntries)}
        basePath={basePath}
        showDestinationForm={canManage && add === "destination"}
        showRuleForm={canManage && add === "rule"}
      />
    </ProjectSettingsFrame>
  );
}
