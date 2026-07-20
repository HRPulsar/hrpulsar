// HRP-23: shared helpers for deadline inputs (Assessment / PDP / Exam).

export function todayLocalISO(): string {
  const d = new Date();
  const offsetMs = d.getTimezoneOffset() * 60_000;
  return new Date(d.getTime() - offsetMs).toISOString().slice(0, 10);
}

export function isPastDeadline(value: string): boolean {
  if (!value) return false;
  const datePart = value.slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(datePart)) return false;
  return datePart < todayLocalISO();
}
