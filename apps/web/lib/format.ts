export function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

export function formatRelative(value: string, now = Date.now()): string {
  const delta = new Date(value).getTime() - now;
  const absolute = Math.abs(delta);
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  if (absolute < 60_000) return formatter.format(Math.round(delta / 1_000), "second");
  if (absolute < 3_600_000) return formatter.format(Math.round(delta / 60_000), "minute");
  if (absolute < 86_400_000) return formatter.format(Math.round(delta / 3_600_000), "hour");
  return formatter.format(Math.round(delta / 86_400_000), "day");
}

export function formatDuration(milliseconds: number | null): string {
  if (milliseconds === null) return "Not reported";
  const seconds = Math.round(milliseconds / 1_000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

export function readableTokenCount(value: number | null): string {
  return value === null ? "Not reported" : new Intl.NumberFormat("en").format(value);
}
