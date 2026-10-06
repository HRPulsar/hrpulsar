// HRP-1013: the employee timeline never shows the backend's English
// sentence under a system event - it is rebuilt from the stored values in
// the viewer's language, or dropped where it only repeats the title.

import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import {
  eventDescription,
  type EventDescriptionInput,
} from "@/lib/employee-events";

// Discovered rather than named: ru.json is enterprise-only and absent from
// the public repo (same approach as i18n-catalog-parity.test.ts).
const MESSAGES_DIR = resolve(__dirname, "../../messages");
const LOCALES = readdirSync(MESSAGES_DIR)
  .filter((f) => f.endsWith(".json"))
  .map((f) => basename(f, ".json"));

function describeIn(locale: string, event: EventDescriptionInput) {
  const messages = JSON.parse(
    readFileSync(resolve(MESSAGES_DIR, `${locale}.json`), "utf8"),
  );
  // Untyped: the catalog is read at runtime, so its keys are not known here.
  const t = createTranslator({ locale, messages, namespace: "employees" }) as unknown as (
    key: string,
    values?: Record<string, string>,
  ) => string;
  return eventDescription(event, {
    t,
    roleLabel: (codes) => codes.join(", ").toUpperCase(),
    divisionName: (id) => ({ d1: "Vertrieb", d2: "Marketing" })[id],
    money: (cents, currency) =>
      (cents / 100).toLocaleString(locale, { style: "currency", currency }),
  });
}

// What employee/service.py writes for each system event.
const SYSTEM_EVENTS: [string, EventDescriptionInput][] = [
  ["hire", { event_type: "hire", description: "Hired as QA Engineer" }],
  [
    "name_change",
    {
      event_type: "name_change",
      description: "Name updated",
      old_value: { first_name: "Anna", last_name: "Alt" },
      new_value: { first_name: "Anna", last_name: "Neu" },
    },
  ],
  [
    "division_change",
    {
      event_type: "division_change",
      description: "Division changed",
      old_value: { division_id: "d1" },
      new_value: { division_id: "d2" },
    },
  ],
  [
    "position_change",
    {
      event_type: "position_change",
      description: "Position changed to Senior QA",
      old_value: { position_title: "QA", position_id: "p1", grade_id: null },
      new_value: { position_title: "Senior QA", position_id: "p2", grade_id: null },
    },
  ],
  [
    "termination",
    {
      event_type: "termination",
      description: "Employment terminated",
      old_value: { status: "active" },
      new_value: { status: "terminated" },
    },
  ],
  [
    "status_inactive",
    {
      event_type: "status_inactive",
      description: "Employment marked inactive",
      old_value: { status: "active" },
      new_value: { status: "inactive" },
    },
  ],
  [
    "status_reactivated",
    {
      event_type: "status_reactivated",
      description: "Employment reactivated",
      old_value: { status: "inactive" },
      new_value: { status: "active" },
    },
  ],
  [
    "compensation_change (new)",
    {
      event_type: "compensation_change",
      description: "New salary: 500000 EUR",
      new_value: { type: "salary", amount: 500000, currency: "EUR" },
    },
  ],
  [
    "compensation_change (updated)",
    {
      event_type: "compensation_change",
      description: "Compensation updated",
      old_value: { type: "salary", amount: 500000, currency: "EUR" },
      new_value: { amount: 550000 },
    },
  ],
  [
    "compensation_change (removed)",
    { event_type: "compensation_change", description: "Compensation record removed" },
  ],
  [
    "role_changed",
    {
      event_type: "role_changed",
      description: "Role changed to Manager",
      old_value: { roles: ["employee"] },
      new_value: { roles: ["manager"] },
    },
  ],
];

// Words of the backend's sentences that must never reach a German screen.
const ENGLISH = /\b(Hired|Name updated|Division changed|Position changed|Employment|New salary|Compensation|record removed|Role changed)\b/;

describe("eventDescription (HRP-1013)", () => {
  for (const locale of LOCALES) {
    it.each(SYSTEM_EVENTS)(`${locale}: %s does not show the backend sentence`, (_, event) => {
      const shown = describeIn(locale, event);
      expect(shown).not.toBe(event.description);
      if (locale !== "en") expect(shown ?? "").not.toMatch(ENGLISH);
    });
  }

  it("rebuilds the values in the viewer's language", () => {
    const [, , division, position, , , , created, updated, removed] =
      SYSTEM_EVENTS.map(([, e]) => e);
    expect(describeIn("de", division)).toBe("Vertrieb → Marketing");
    expect(describeIn("de", position)).toBe("QA → Senior QA");
    expect(describeIn("de", created)).toMatch(/^Gehalt 5\.000,00\s€$/);
    expect(describeIn("de", updated)).toMatch(/^Gehalt 5\.000,00\s€ → Gehalt 5\.500,00\s€$/);
    expect(describeIn("de", removed)).toBe("Eintrag entfernt");
    expect(describeIn("en", SYSTEM_EVENTS[1][1])).toBe("Anna Alt → Anna Neu");
  });

  it("keeps the text of an event added by hand", () => {
    const manual = { event_type: "hire", description: "Eingestellt nach Probetag" };
    expect(describeIn("de", manual)).toBe("Eingestellt nach Probetag");
    expect(describeIn("de", { event_type: "promotion", description: "Teamleitung" })).toBe(
      "Teamleitung",
    );
  });

  it("drops a division change the viewer cannot name instead of guessing", () => {
    const event = {
      event_type: "division_change",
      description: "Division changed",
      old_value: { division_id: "elsewhere" },
      new_value: { division_id: null },
    };
    expect(describeIn("de", event)).toBeNull();
    expect(
      describeIn("de", { ...event, old_value: { division_id: null }, new_value: { division_id: "d2" } }),
    ).toBe("— → Marketing");
  });

  it("drops a position change written without values (dev seed)", () => {
    expect(
      describeIn("de", { event_type: "position_change", description: "Promoted" }),
    ).toBeNull();
  });
});
