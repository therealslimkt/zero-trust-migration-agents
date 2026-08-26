export function formatTimestamp(timestamp: string | null | undefined): string {
  if (!timestamp) return "Never";
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" }).format(new Date(timestamp));
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** exponent).toFixed(exponent > 2 ? 1 : 0)} ${units[exponent]}`;
}

export function humanize(value: string): string {
  return value.replaceAll("_", " ").replaceAll(".", " · ");
}
