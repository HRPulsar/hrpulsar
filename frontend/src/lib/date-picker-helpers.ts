// HRP-152: pure date helpers backing the custom DatePicker. Extracted
// so they can be unit-tested without spinning up a DOM.

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

export function toIso(date: Date): string {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

export function parseIso(value: string | undefined | null): Date | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  const [, y, m, d] = match;
  const year = Number(y);
  const month = Number(m);
  const day = Number(d);
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  const date = new Date(year, month - 1, day);
  if (Number.isNaN(date.getTime())) return null;
  // Reject rollovers like 2024-02-30 → 2024-03-01.
  if (
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return null;
  }
  return date;
}

export function startOfMonth(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

export function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

export function compareIso(a: string, b: string): number {
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

export function isWithinBounds(
  iso: string,
  min?: string,
  max?: string,
): boolean {
  if (min && compareIso(iso, min) < 0) return false;
  if (max && compareIso(iso, max) > 0) return false;
  return true;
}

export function buildMonthGrid(viewMonth: Date): Date[] {
  const start = startOfMonth(viewMonth);
  // HRP-152 REDO: Sunday-first week per the reviewer's screenshots —
  // JS ``getDay()`` already returns 0 for Sunday so no remap is needed.
  const dayOfWeek = start.getDay();
  const gridStart = new Date(start);
  gridStart.setDate(start.getDate() - dayOfWeek);
  const days: Date[] = [];
  for (let i = 0; i < 42; i += 1) {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    days.push(d);
  }
  return days;
}

export function yesterdayIso(today: Date = new Date()): string {
  const y = new Date(today);
  y.setDate(today.getDate() - 1);
  return toIso(y);
}

// HRP-152 REDO: input mask helper for the DatePicker — strips everything
// except digits, then re-inserts the ``yyyy-mm-dd`` dashes as the user
// types. Returns at most 10 characters. ``2024031`` → ``2024-03-1``.
export function applyDateMask(raw: string): string {
  const digits = raw.replace(/\D/g, "").slice(0, 8);
  if (digits.length <= 4) return digits;
  if (digits.length <= 6) {
    return `${digits.slice(0, 4)}-${digits.slice(4)}`;
  }
  return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6)}`;
}
