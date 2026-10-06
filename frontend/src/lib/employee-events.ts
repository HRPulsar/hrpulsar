// HRP-1013: system events on the employee card read in the viewer's
// language. The backend words them in English (employee/service.py) and
// keeps the raw values beside the words; the sentence is rebuilt here from
// those values, or dropped where it only repeats the event's title. A
// manual event keeps the text its author typed.

type Values = Record<string, unknown> | null | undefined;

export interface EventDescriptionInput {
  event_type: string;
  description: string | null;
  old_value?: Values;
  new_value?: Values;
}

export interface EventDescriptionDeps {
  /** The `employees` namespace. */
  t: (key: string, values?: Record<string, string>) => string;
  roleLabel: (codes: string[]) => string;
  /** `undefined` when the viewer cannot resolve the division. */
  divisionName: (id: string) => string | undefined;
  /** Compensation amounts are stored in cents. */
  money: (cents: number, currency: string) => string;
}

// The backend and the dev seed both open a hire with this; a hire added by
// hand carries whatever its author typed. The position is not kept as a
// value, so the sentence has nothing to be rebuilt from.
const SYSTEM_HIRE_PREFIX = "Hired as ";
// The one compensation event the backend writes without values.
const COMPENSATION_REMOVED = "Compensation record removed";

const COMP_TYPE_KEYS: Record<string, string> = {
  salary: "compTypeSalary",
  bonus: "compTypeBonus",
  allowance: "compTypeAllowance",
};

const NONE = "—";

export function eventDescription(
  event: EventDescriptionInput,
  deps: EventDescriptionDeps,
): string | null {
  const { t } = deps;
  const from = event.old_value ?? null;
  const to = event.new_value ?? null;
  const change = (a: string, b: string) =>
    t("eventValueChange", { from: a, to: b });

  switch (event.event_type) {
    case "hire":
      return event.description?.startsWith(SYSTEM_HIRE_PREFIX)
        ? null
        : event.description;
    // The title already says it: "Termination" over "Employment terminated".
    case "termination":
    case "status_inactive":
    case "status_reactivated":
      return null;
    case "role_changed":
      return Array.isArray(from?.roles) && Array.isArray(to?.roles)
        ? change(deps.roleLabel(from.roles), deps.roleLabel(to.roles))
        : null;
    case "name_change":
      return from && to ? change(fullName(from), fullName(to)) : null;
    case "position_change":
      // The dev seed writes "Promoted" with no values at all.
      return to && "position_title" in to
        ? change(text(from?.position_title), text(to.position_title))
        : null;
    case "division_change": {
      if (!from || !to) return null;
      const a = division(from.division_id, deps);
      const b = division(to.division_id, deps);
      return a === undefined || b === undefined ? null : change(a, b);
    }
    case "compensation_change": {
      if (!from && !to) {
        return event.description === COMPENSATION_REMOVED
          ? t("eventCompensationRemoved")
          : null;
      }
      // An update keeps only the changed fields in new_value.
      const after = pay({ ...from, ...to }, deps);
      const before = from ? pay(from, deps) : null;
      if (after === null || (from && before === null)) return null;
      return before === null ? after : change(before, after);
    }
    default:
      return event.description;
  }
}

function text(v: unknown): string {
  return typeof v === "string" && v ? v : NONE;
}

function fullName(v: Record<string, unknown>): string {
  return [v.first_name, v.last_name].filter((p) => typeof p === "string" && p).join(" ") || NONE;
}

/** `undefined` for an id the viewer cannot name; no division at all is a dash. */
function division(id: unknown, deps: EventDescriptionDeps): string | undefined {
  if (id === null || id === undefined) return NONE;
  return typeof id === "string" ? deps.divisionName(id) : undefined;
}

function pay(v: Record<string, unknown>, deps: EventDescriptionDeps): string | null {
  if (typeof v.amount !== "number" || typeof v.currency !== "string") return null;
  const key = typeof v.type === "string" ? COMP_TYPE_KEYS[v.type] : undefined;
  const amount = deps.money(v.amount, v.currency);
  return key ? `${deps.t(key)} ${amount}` : amount;
}
