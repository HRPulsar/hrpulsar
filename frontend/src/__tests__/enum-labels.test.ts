// HRP-653: enum values rendered raw were reaching the RU demo untranslated.
// Two rules to keep: every offered option has a catalog key in every
// shipped locale, and an unknown value still renders (raw) instead of
// vanishing behind an empty label.
import { readdirSync, readFileSync } from "node:fs";
import { basename, join, resolve } from "node:path";

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
const BACKEND_APP = resolve(__dirname, "../../../backend/app");

function pythonSources(dir: string): string[] {
  return readdirSync(dir, { recursive: true, encoding: "utf8" })
    .filter((path) => path.endsWith(".py") && !path.includes("tests"))
    .map((path) => join(dir, path));
}

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
      expect(EVENT_TYPE_LABEL_KEYS[value], `no label key for ${value}`)
        .toBeTruthy();
    }
    for (const key of Object.values(EVENT_TYPE_LABEL_KEYS)) {
      expect(leaf(catalog, "employees", key), key).toBeTypeOf("string");
    }
  });

  it("labels every event type the backend writes", () => {
    // HRP-999: a role change read "Role_changed" — the map knew only the
    // types the dialog offers. The backend's own are the literal types of
    // `_create_event(db, <employee>, "<type>", ...)` and the `event_type=`
    // of a file that builds `EmployeeEvent(...)` itself (the seed).
    const written = new Set<string>();
    let seeded = 0;
    for (const file of pythonSources(BACKEND_APP)) {
      const source = readFileSync(file, "utf8");
      for (const match of source.matchAll(
        /_create_event\(\s*db,\s*[\w.]+,\s*"(\w+)"/g,
      )) {
        written.add(match[1]);
      }
      if (!source.includes("EmployeeEvent(")) continue;
      for (const match of source.matchAll(/event_type="(\w+)"/g)) {
        written.add(match[1]);
        seeded += 1;
      }
    }
    // Both readings still find something - a pattern gone blind passes.
    expect(written).toContain("role_changed");
    expect(seeded).toBeGreaterThan(0);
    for (const type of written) {
      expect(EVENT_TYPE_LABEL_KEYS[type], `no label for ${type}`).toBeTruthy();
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
    // An imported history can carry a code nobody labelled.
    expect(eventTypeLabel(t, "sabbatical")).toBe("sabbatical");
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
