// HRP-152: shared date formatters. The UI renders every date as ISO
// yyyy-MM-dd (date-only) and yyyy-MM-dd HH:mm (date-time). Native
// <input type="date"> uses this same shape for its value, so the helper
// also doubles as the canonical placeholder.

export const DATE_PLACEHOLDER = "yyyy-mm-dd";

export type DateInput = Date | string | number | null | undefined;

function toDate(value: DateInput): Date | null {
  if (value == null || value === "") return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

export function formatDate(value: DateInput, fallback = ""): string {
  // Backend serves date-only fields as bare `YYYY-MM-DD`; `new Date(str)`
  // would treat that as UTC midnight and a negative-offset viewer would
  // see the previous day. Pass the literal through to stay stable.
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return value;
  }
  const d = toDate(value);
  if (!d) return fallback;
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

export function formatDateTime(value: DateInput, fallback = ""): string {
  const d = toDate(value);
  if (!d) return fallback;
  const base = formatDate(d);
  return `${base} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

// Backend stores date-only fields as ISO `YYYY-MM-DD`. Parsing that
// directly via `new Date(value)` interprets it as UTC midnight and can
// roll the day over depending on the viewer's timezone. This helper
// pins it to a stable calendar day.
export function formatDateOnlyIso(
  value: string | null | undefined,
  fallback = "",
): string {
  if (!value) return fallback;
  const iso = value.slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return fallback;
  return iso;
}
