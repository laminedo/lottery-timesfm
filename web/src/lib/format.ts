const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const integer = new Intl.NumberFormat("en-US");

/** $485,000,000 -> "$485 million"; $1,250,000,000 -> "$1.25 billion"; $550,000 -> "$550,000". */
export function formatJackpot(amount: number): string {
  if (amount >= 1e9) return `$${trim(amount / 1e9, 2)} billion`;
  if (amount >= 1e6) return `$${trim(amount / 1e6, 1)} million`;
  return usd.format(amount);
}

function trim(value: number, digits: number): string {
  return value.toFixed(digits).replace(/\.?0+$/, "");
}

export function formatInt(value: number): string {
  return integer.format(value);
}

export function formatPercent(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

/** "2026-10-07" -> "Wed, Oct 7, 2026" without shifting the calendar day across time zones. */
export function formatDate(iso: string, withYear = true): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: withYear ? "numeric" : undefined,
    timeZone: "UTC",
  });
}

export function formatShortDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

/** Tick labels for a date axis: "Oct 6" for spans under ten months, "Oct ’26" for longer ones. */
export function dateTickFormatter(first: string | undefined, last: string | undefined): (iso: string) => string {
  const days = first && last ? (Date.parse(last) - Date.parse(first)) / 86_400_000 : 0;
  if (days <= 300) return formatShortDate;
  return (iso) => {
    const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
    const month = new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", { month: "short", timeZone: "UTC" });
    return `${month} ’${String(y).slice(2)}`;
  };
}

/** A p-value the way a reader expects it: "0.43", "0.008", "< 0.001". */
export function formatP(p: number | null): string {
  if (p === null) return "n/a";
  if (p < 0.001) return "< 0.001";
  return p < 0.01 ? p.toFixed(3) : p.toFixed(2);
}

/** Milliseconds -> the parts of a countdown. */
export function countdownParts(ms: number): { days: number; hours: number; minutes: number; seconds: number } {
  const total = Math.max(0, Math.floor(ms / 1000));
  return {
    days: Math.floor(total / 86400),
    hours: Math.floor((total % 86400) / 3600),
    minutes: Math.floor((total % 3600) / 60),
    seconds: total % 60,
  };
}
