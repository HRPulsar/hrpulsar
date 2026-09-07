// HRP-716: the board header shows what is actually on the board ("3
// vacancies · 1 talent") instead of "6 cards". Pins the breakdown helper:
// order, the dropped zero types, and that every type it can return has
// wording in the shipped catalogs.

import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  countCardsByType,
  TALENT_CARD_TYPES,
  TYPE_COUNT_KEYS,
} from "@/lib/talent-card-types";

// Catalogs are discovered, never imported by name: ru.json is
// enterprise-only and absent from the public repo, where a static import
// would fail to resolve (same approach as i18n-catalog-parity.test.ts).
const MESSAGES_DIR = resolve(__dirname, "../../messages");

const CATALOGS: Array<[string, { talentMarket: Record<string, string> }]> =
  readdirSync(MESSAGES_DIR)
    .filter((file) => file.endsWith(".json"))
    .sort()
    .map((file) => [
      basename(file, ".json"),
      JSON.parse(readFileSync(resolve(MESSAGES_DIR, file), "utf8")),
    ]);

function cards(...types: string[]) {
  return types.map((card_type) => ({ card_type }));
}

describe("countCardsByType (HRP-716)", () => {
  it("counts each type and keeps the TALENT_CARD_TYPES order", () => {
    expect(
      countCardsByType(
        cards("project", "vacancy", "talent", "vacancy", "project", "vacancy"),
      ),
    ).toEqual([
      { type: "vacancy", count: 3 },
      { type: "talent", count: 1 },
      { type: "project", count: 2 },
    ]);
  });

  it("drops types with no cards", () => {
    expect(countCardsByType(cards("project", "project"))).toEqual([
      { type: "project", count: 2 },
    ]);
  });

  it("returns nothing for an empty board, so the caller falls back", () => {
    expect(countCardsByType([])).toEqual([]);
  });

  it("ignores unknown card types instead of inventing a key for them", () => {
    expect(countCardsByType(cards("vacancy", "mentorship"))).toEqual([
      { type: "vacancy", count: 1 },
    ]);
  });

  it("has a plural message in every shipped catalog for each type", () => {
    expect(CATALOGS.length).toBeGreaterThan(0);
    for (const type of TALENT_CARD_TYPES) {
      const key = TYPE_COUNT_KEYS[type];
      for (const [locale, catalog] of CATALOGS) {
        expect(catalog.talentMarket[key], `${locale}: ${key} missing`).toContain(
          "{count, plural,",
        );
      }
    }
  });
});
