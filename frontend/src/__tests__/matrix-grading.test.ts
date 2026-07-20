// HRP-101: pins the two pure helpers driving the matrix UI cleanup —
// per-cell skill-level tint and the competence coverage-gap message.

import { describe, expect, it } from "vitest";
import type { Competence, SkillLevel } from "@/lib/types";
import { coverageGapMessage, levelHueClass, levelTint } from "@/lib/matrix-grading";

function lvl(id: string, sort: number, title: string): SkillLevel {
  return {
    id,
    tenant_id: null,
    title,
    i18n_key: title.toLowerCase(),
    sort_index: sort,
    is_active: true,
  };
}

const LEVELS = [lvl("a", 0, "Basic"), lvl("b", 1, "Intermediate"), lvl("c", 2, "Advanced")];

describe("levelTint", () => {
  it("returns null when no level is assigned", () => {
    expect(levelTint(null, LEVELS)).toBeNull();
  });

  it("returns null when the level id is unknown", () => {
    expect(levelTint("missing", LEVELS)).toBeNull();
  });

  it("picks tints in monotonic order along the sort_index", () => {
    expect(levelTint("a", LEVELS)).toBe("bg-primary/5");
    expect(levelTint("b", LEVELS)).toBe("bg-primary/10");
    expect(levelTint("c", LEVELS)).toBe("bg-primary/15");
  });

  it("clamps levels beyond the tint ramp to the darkest bucket", () => {
    const extra: SkillLevel[] = [
      ...LEVELS,
      lvl("d", 3, "Expert"),
      lvl("e", 4, "Master"),
      lvl("f", 5, "Legend"),
    ];
    expect(levelTint("e", extra)).toBe("bg-primary/20");
    expect(levelTint("f", extra)).toBe("bg-primary/20");
  });
});

function comp(
  levelsCompletion: Competence["levels_completion"],
): Pick<Competence, "levels_completion"> {
  return { levels_completion: levelsCompletion };
}

describe("levelHueClass (HRP-157 REDO)", () => {
  it("returns the neutral chip when no level is assigned", () => {
    expect(levelHueClass(null, LEVELS)).toContain("bg-muted/30");
  });

  it("returns the neutral chip when the level id is unknown", () => {
    expect(levelHueClass("missing", LEVELS)).toContain("bg-muted/30");
  });

  it("walks the hue palette by sort_index — Basic / Intermediate / Advanced", () => {
    expect(levelHueClass("a", LEVELS)).toContain("bg-slate-100");
    expect(levelHueClass("b", LEVELS)).toContain("bg-amber-50");
    expect(levelHueClass("c", LEVELS)).toContain("bg-emerald-50");
  });

  it("uses the violet Expert hue at index 3 and clamps beyond", () => {
    const extra: SkillLevel[] = [
      ...LEVELS,
      lvl("d", 3, "Expert"),
      lvl("e", 4, "Master"),
    ];
    expect(levelHueClass("d", extra)).toContain("bg-violet-50");
    expect(levelHueClass("e", extra)).toContain("bg-violet-50");
  });
});

describe("coverageGapMessage", () => {
  it("returns null when both flags are clear", () => {
    expect(
      coverageGapMessage(
        comp({ has_uncovered_indicators: false, has_uncovered_materials: false }),
      ),
    ).toBeNull();
  });

  it("returns null when levels_completion is null (no signal yet)", () => {
    // Backend omits the field on origin / unused competences — we don't
    // want false positives on rows the operator hasn't even touched.
    expect(coverageGapMessage(comp(null))).toBeNull();
  });

  it("reports only indicators when materials are covered", () => {
    const msg = coverageGapMessage(
      comp({ has_uncovered_indicators: true, has_uncovered_materials: false }),
    );
    expect(msg).toContain("indicators");
    expect(msg).not.toContain("development materials");
  });

  it("reports only materials when indicators are covered", () => {
    const msg = coverageGapMessage(
      comp({ has_uncovered_indicators: false, has_uncovered_materials: true }),
    );
    expect(msg).toContain("development materials");
    expect(msg).not.toMatch(/^Missing indicators/);
  });

  it("joins both gaps with 'and' when neither indicators nor materials are covered", () => {
    const msg = coverageGapMessage(
      comp({ has_uncovered_indicators: true, has_uncovered_materials: true }),
    );
    expect(msg).toBe(
      "Missing indicators and development materials at one or more grade levels. Click the title to add them.",
    );
  });
});
