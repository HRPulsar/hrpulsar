// HRP-653: the Prices page translates credits.yaml codes on the client and
// falls back to the server label for a code the catalog does not carry, so
// a new entry in credits.yaml adds a row instead of breaking the page.
// That promise rests on `t.has()` answering false for an unknown key
// instead of throwing — pinned here.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

const messages = JSON.parse(
  readFileSync(resolve(__dirname, "../../messages/en.json"), "utf8"),
);

const t = createTranslator({ locale: "en", messages, namespace: "settings" });

describe("billing price-list labels", () => {
  it("resolves a known category and action code", () => {
    expect(t.has("billingCategory.employee")).toBe(true);
    expect(t("billingCategory.employee")).toBe("Employees");
    expect(t.has("billingAction.create_event")).toBe(true);
    expect(t("billingAction.create_event")).toBe("Create Event");
  });

  it("answers false for a code credits.yaml grew after this release", () => {
    expect(t.has("billingAction.some_action_added_later")).toBe(false);
    expect(t.has("billingCategory.some_category_added_later")).toBe(false);
  });

  it("labels every category the price list can render", () => {
    // The category column had no guard: `billingCategory.skill_level`
    // deliberately reads "Skill Levels" where humanizeAction produced
    // "Skill Level", and nothing would have caught a category losing its
    // key and silently falling back to the server's English label.
    const categories = messages.settings.billingCategory as Record<
      string,
      string
    >;
    expect(Object.keys(categories).length).toBeGreaterThan(0);
    for (const [code, label] of Object.entries(categories)) {
      expect(label, code).toBeTruthy();
      expect(t.has(`billingCategory.${code}`), code).toBe(true);
    }
    // The two the navigation also names must agree with it (HRP-653).
    expect(categories.exam).toBe("Exams");
    expect(categories.dictionary_item).toBe("Dictionaries");
  });

  it("keeps the English labels byte-identical to humanizeAction", () => {
    // The page rendered `humanizeAction(name)` before the catalog existed;
    // the English column must not shift under existing readers.
    const humanize = (name: string) =>
      name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    const actions = (
      messages.settings.billingAction as Record<string, string>
    );
    for (const [code, label] of Object.entries(actions)) {
      expect(label, code).toBe(humanize(code));
    }
  });
});
