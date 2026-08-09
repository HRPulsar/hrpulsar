// HRP-486: every interview-question code must render as a localized
// label, in both catalogs. A code added on the backend without a label
// would otherwise surface its raw wire value in the UI.
import { describe, expect, it } from "vitest";
import en from "../../messages/en.json";
import de from "../../messages/de.json";
import {
  CRITICALITY_TO_PRIORITY,
  GOAL_LABEL_KEYS,
  PRIORITY_LABEL_KEYS,
  QUESTION_GOALS,
  QUESTION_PRIORITIES,
  QUESTION_SOURCES,
  SOURCE_LABEL_KEYS,
} from "@/lib/question-enums";

const catalogs = { en: en.recruitment, de: de.recruitment } as Record<
  string,
  Record<string, string>
>;

const maps = [
  ["goal", QUESTION_GOALS, GOAL_LABEL_KEYS],
  ["priority", QUESTION_PRIORITIES, PRIORITY_LABEL_KEYS],
  ["source", QUESTION_SOURCES, SOURCE_LABEL_KEYS],
] as const;

describe("question enum label maps", () => {
  it.each(maps)("%s: every code has a label key", (_name, codes, labels) => {
    for (const code of codes) {
      expect(labels[code as keyof typeof labels]).toBeTruthy();
    }
    expect(Object.keys(labels).sort()).toEqual([...codes].sort());
  });

  it.each(maps)(
    "%s: every label key resolves in en and de",
    (_name, _codes, labels) => {
      for (const key of Object.values(labels)) {
        for (const [locale, catalog] of Object.entries(catalogs)) {
          expect(catalog[key], `${key} missing in ${locale}`).toBeTruthy();
        }
      }
    },
  );

  it("labels never leak a raw wire code", () => {
    for (const [, , labels] of maps) {
      for (const key of Object.values(labels)) {
        expect(catalogs.en[key]).not.toMatch(/_/);
      }
    }
  });

  it("maps every vacancy criticality onto a real priority", () => {
    for (const criticality of ["critical", "important", "desirable"]) {
      expect(QUESTION_PRIORITIES).toContain(
        CRITICALITY_TO_PRIORITY[criticality],
      );
    }
  });
});
