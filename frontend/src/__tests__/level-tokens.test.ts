import { describe, expect, it } from "vitest";

import { LEVEL_TOKENS, levelTokens } from "@/lib/competences/level-tokens";

describe("levelTokens", () => {
  it("maps canonical i18n_key to its bucket regardless of position", () => {
    expect(levelTokens({ i18n_key: "basic", sort_index: 99 }, 99)).toBe(
      LEVEL_TOKENS.basic,
    );
    expect(levelTokens({ i18n_key: "intermediate", sort_index: 0 }, 0)).toBe(
      LEVEL_TOKENS.intermediate,
    );
    expect(levelTokens({ i18n_key: "advanced", sort_index: 5 }, 5)).toBe(
      LEVEL_TOKENS.advanced,
    );
    expect(levelTokens({ i18n_key: "expert", sort_index: 1 }, 1)).toBe(
      LEVEL_TOKENS.expert,
    );
  });

  it("accepts familiar aliases (senior → advanced, middle → intermediate)", () => {
    expect(levelTokens({ i18n_key: "senior", sort_index: 2 }, 2)).toBe(
      LEVEL_TOKENS.advanced,
    );
    expect(levelTokens({ i18n_key: "middle", sort_index: 1 }, 1)).toBe(
      LEVEL_TOKENS.intermediate,
    );
    expect(levelTokens({ i18n_key: "lead", sort_index: 3 }, 3)).toBe(
      LEVEL_TOKENS.expert,
    );
  });

  it("falls back to the progression by position when i18n_key is null", () => {
    expect(levelTokens({ i18n_key: null, sort_index: 0 }, 0)).toBe(LEVEL_TOKENS.basic);
    expect(levelTokens({ i18n_key: null, sort_index: 1 }, 1)).toBe(
      LEVEL_TOKENS.intermediate,
    );
    expect(levelTokens({ i18n_key: null, sort_index: 2 }, 2)).toBe(
      LEVEL_TOKENS.advanced,
    );
    expect(levelTokens({ i18n_key: null, sort_index: 3 }, 3)).toBe(
      LEVEL_TOKENS.expert,
    );
  });

  it("caps the fallback at expert for any position beyond the canonical four", () => {
    expect(levelTokens({ i18n_key: null, sort_index: 9 }, 9)).toBe(
      LEVEL_TOKENS.expert,
    );
  });

  it("treats unknown i18n_key like a custom level — falls back to position", () => {
    expect(
      levelTokens({ i18n_key: "level-3", sort_index: 0 }, 0),
    ).toBe(LEVEL_TOKENS.basic);
    expect(
      levelTokens({ i18n_key: "level-3", sort_index: 2 }, 2),
    ).toBe(LEVEL_TOKENS.advanced);
  });

  it("each bucket carries every visual token (no missing field)", () => {
    for (const tokens of Object.values(LEVEL_TOKENS)) {
      expect(tokens.bg).toMatch(/bg-/);
      expect(tokens.border).toMatch(/border-/);
      expect(tokens.rail).toMatch(/bg-/);
      expect(tokens.dot).toMatch(/bg-/);
      expect(tokens.text).toMatch(/text-/);
      expect(tokens.label.length).toBeGreaterThan(0);
    }
  });
});
