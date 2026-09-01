// HRP-653: enum values rendered raw were reaching the RU demo untranslated.
// Two rules to keep: every offered option has a catalog key in every
// shipped locale, and an unknown value still renders (raw) instead of
// vanishing behind an empty label.
import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  EVENT_TYPE_LABEL_KEYS,
  EVENT_TYPE_OPTIONS,
  MATERIAL_FORMAT_OPTIONS,
  eventTypeLabel,
} from "@/lib/enum-labels";
import {
  MATERIAL_FORMATS,
  MATERIAL_FORMAT_LABELS,
  materialFormatKey,
  materialFormatLabel,
} from "@/lib/competences/material-options";

type Tree = { [key: string]: string | Tree };

const MESSAGES_DIR = resolve(__dirname, "../../messages");

const catalogs = readdirSync(MESSAGES_DIR)
  .filter((file) => file.endsWith(".json"))
  .sort()
  .map(
    (file) =>
      [
        basename(file, ".json"),
        JSON.parse(readFileSync(resolve(MESSAGES_DIR, file), "utf8")) as Tree,
      ] as const,
  );

function leaf(tree: Tree, namespace: string, key: string): unknown {
  const ns = tree[namespace];
  return typeof ns === "object" ? ns[key] : undefined;
}

describe("frontend-owned enum labels", () => {
  it.each(catalogs)("%s translates every event type", (_locale, catalog) => {
    for (const value of EVENT_TYPE_OPTIONS) {
      const key = EVENT_TYPE_LABEL_KEYS[value];
      expect(key, `no label key for event type ${value}`).toBeTruthy();
      expect(leaf(catalog, "employees", key)).toBeTypeOf("string");
    }
  });

  it.each(catalogs)(
    "%s translates every material format the shared vocabulary knows",
    (_locale, catalog) => {
      // HRP-653: the plan copies `Material.format` verbatim, so it has to
      // read the same vocabulary the competence screens use — a shorter
      // map of its own left 12 of these rendering raw on the plan.
      for (const { value, labelKey } of MATERIAL_FORMAT_LABELS) {
        expect(labelKey, `no label key for format ${value}`).toBeTruthy();
        expect(leaf(catalog, "competences", labelKey)).toBeTypeOf("string");
      }
    },
  );

  it("offers only formats the shared vocabulary can label", () => {
    for (const value of MATERIAL_FORMAT_OPTIONS) {
      expect(materialFormatKey(value), `plan offers unlabelled ${value}`)
        .toBeTruthy();
    }
    for (const { value } of MATERIAL_FORMATS) {
      expect(materialFormatKey(value), `competence offers unlabelled ${value}`)
        .toBeTruthy();
    }
  });

  it("keeps the competence card's pick-list as it was", () => {
    // The vocabulary grew a value the plan offers; the competence
    // dropdown must not grow with it (HRP-653 review).
    expect(MATERIAL_FORMATS).toHaveLength(17);
    expect(MATERIAL_FORMAT_LABELS).toHaveLength(18);
    expect(MATERIAL_FORMATS.map((f) => f.value)).not.toContain("practice");
    // ...and the plan's own list is untouched too.
    expect([...MATERIAL_FORMAT_OPTIONS]).toEqual([
      "course",
      "book",
      "article",
      "video",
      "practice",
    ]);
  });

  it("resolves a known value through the catalog", () => {
    const t = (key: string) => `translated:${key}`;
    expect(eventTypeLabel(t, "hire")).toBe("translated:eventTypeHire");
    expect(materialFormatLabel(t, "practice")).toBe(
      "translated:materialFormatPractice",
    );
  });

  it("renders an unknown value raw rather than blank", () => {
    const t = (key: string) => `translated:${key}`;
    // Seeded employee histories carry codes the dialog never offers.
    expect(eventTypeLabel(t, "position_change")).toBe("position_change");
    // A format the plan does not offer but a copied material can carry
    // still resolves — that is the whole point of sharing the vocabulary.
    expect(materialFormatLabel(t, "webinar")).toBe(
      "translated:materialFormatWebinar",
    );
    // Only a value outside the vocabulary entirely falls back to raw.
    expect(materialFormatLabel(t, "workshop")).toBe("workshop");
  });

  it("renders an empty label for a missing value", () => {
    const t = (key: string) => `translated:${key}`;
    expect(eventTypeLabel(t, null)).toBe("");
    expect(materialFormatLabel(t, undefined)).toBeNull();
  });
});
