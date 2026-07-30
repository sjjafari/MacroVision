export function formatExactDecimal(value: string): string {
  const match = /^([+-]?)(\d+)(\.\d+)?$/.exec(value);
  if (!match) return value;
  const [, sign, integer, fraction = ""] = match;
  return `${sign}${integer.replace(/\B(?=(\d{3})+(?!\d))/g, "٬")}${fraction}`;
}

export function formatUtcTimestamp(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return null;
  return new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(date);
}

export function safeSourceUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
      return null;
    }
    return url.toString();
  } catch {
    return null;
  }
}
