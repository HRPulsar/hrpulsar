// HRP-479 (i18n F5): origin reference labels resolve through the
// `reference` catalog; tenant-authored rows fall back to their stored
// text. Also pins the catalog keys against the backend seed slugs so a
// future seed/catalog edit can't silently drift.
import { describe, expect, it } from "vitest";

import deMessages from "../../messages/de.json";
import enMessages from "../../messages/en.json";
import {
  answerScaleDescription,
  answerScaleLabel,
  assessmentStatusTitle,
  assessmentTypeTitle,
  dictionaryItemDescription,
  dictionaryItemLabel,
  scaleLevelLabel,
  scaleOptionDescription,
  scaleOptionLabel,
  skillLevelLabel,
  type ReferenceTranslator,
} from "@/lib/reference-labels";

type Catalog = Record<string, unknown>;

function makeT(catalog: Catalog): ReferenceTranslator {
  const lookup = (key: string): unknown =>
    key
      .split(".")
      .reduce<unknown>(
        (acc, part) =>
          acc && typeof acc === "object"
            ? (acc as Catalog)[part]
            : undefined,
        catalog,
      );
  const t = ((key: string) => String(lookup(key))) as ReferenceTranslator;
  t.has = (key: string) => typeof lookup(key) === "string";
  return t;
}

const en = enMessages as { reference: Catalog };
const de = deMessages as { reference: Catalog };
const t = makeT(en.reference);

describe("dictionaryItemLabel / dictionaryItemDescription", () => {
  it("resolves origin items through the catalog", () => {
    expect(
      dictionaryItemLabel(t, { type: "grade", title: "Junior", i18n_key: "junior" }),
    ).toBe("Junior");
    expect(
      dictionaryItemDescription(t, {
        type: "grade",
        description: "Entry-level position",
        i18n_key: "junior",
      }),
    ).toBe("Entry-level position");
  });

  it("renders tenant items verbatim (no key)", () => {
    expect(
      dictionaryItemLabel(t, { type: "grade", title: "Guild Master", i18n_key: null }),
    ).toBe("Guild Master");
    expect(
      dictionaryItemDescription(t, {
        type: "grade",
        description: "Runs the guild",
        i18n_key: null,
      }),
    ).toBe("Runs the guild");
  });

  it("falls back to stored text for a key absent from the catalog", () => {
    expect(
      dictionaryItemLabel(t, {
        type: "grade",
        title: "Custom Grade",
        i18n_key: "custom_grade",
      }),
    ).toBe("Custom Grade");
  });

  it("falls back to stored description when the catalog has none", () => {
    // Seeded specializations have no description keys.
    expect(
      dictionaryItemDescription(t, {
        type: "specialization",
        description: null,
        i18n_key: "designer",
      }),
    ).toBeNull();
  });
});

describe("skillLevelLabel", () => {
  it("resolves origin levels and falls back for custom ones", () => {
    expect(skillLevelLabel(t, { title: "Basic", i18n_key: "basic" })).toBe("Basic");
    expect(skillLevelLabel(t, { title: "Wizard", i18n_key: "wizard" })).toBe("Wizard");
    expect(skillLevelLabel(t, { title: "Novice", i18n_key: null })).toBe("Novice");
  });

  it("renders tenant levels verbatim even with a catalog-colliding key", () => {
    // i18n_key was client-writable before HRP-479 closed the schema, so
    // existing tenant rows may carry e.g. "advanced".
    expect(
      skillLevelLabel(t, {
        title: "Meine Stufe",
        i18n_key: "advanced",
        tenant_id: "3d1c9c9a-0000-0000-0000-000000000001",
      }),
    ).toBe("Meine Stufe");
    expect(
      skillLevelLabel(t, {
        title: "Basic",
        i18n_key: "basic",
        tenant_id: null,
      }),
    ).toBe("Basic");
  });
});

describe("scaleLevelLabel", () => {
  it("keeps the pre-i18n shim contract", () => {
    expect(
      scaleLevelLabel(t, { system_code: "below_expectations", system_title: null }),
    ).toBe("Below expectations");
    // Unknown code surfaces itself (visible in screenshots/logs).
    expect(
      scaleLevelLabel(t, { system_code: "mystery_code", system_title: null }),
    ).toBe("mystery_code");
    expect(
      scaleLevelLabel(t, { system_code: null, system_title: "HR wording" }),
    ).toBe("HR wording");
    expect(scaleLevelLabel(t, { system_code: null, system_title: null })).toBe("");
  });
});

describe("scaleOptionLabel / scaleOptionDescription", () => {
  it("resolves seeded option codes", () => {
    expect(scaleOptionLabel(t, { code: "na", title: "N/A" })).toBe("N/A");
    expect(
      scaleOptionDescription(t, { code: "outstanding", description: null }),
    ).toBe("Significantly exceeds expectations");
  });

  it("falls back for tenant option codes (opt_N / neutral)", () => {
    expect(scaleOptionLabel(t, { code: "opt_0", title: "Meh" })).toBe("Meh");
    expect(scaleOptionLabel(t, { code: "neutral", title: "Skip" })).toBe("Skip");
    expect(
      scaleOptionDescription(t, { code: "opt_0", description: "Custom words" }),
    ).toBe("Custom words");
  });
});

describe("answerScaleLabel / answerScaleDescription", () => {
  it("resolves the seeded default scale (incl. snapshots via i18n_key)", () => {
    expect(
      answerScaleLabel(t, { title: "Standard 5-Point Scale", i18n_key: "standard_5point" }),
    ).toBe("Standard 5-Point Scale");
    expect(
      answerScaleDescription(t, { description: null, i18n_key: "standard_5point" }),
    ).toBe("Default assessment scoring scale");
  });

  it("renders tenant scales verbatim", () => {
    expect(answerScaleLabel(t, { title: "Our scale", i18n_key: null })).toBe(
      "Our scale",
    );
    expect(
      answerScaleDescription(t, { description: "Ours", i18n_key: null }),
    ).toBe("Ours");
  });
});

describe("assessmentStatusTitle / assessmentTypeTitle", () => {
  it("mirrors the seeded DB titles byte-for-byte", () => {
    expect(
      assessmentStatusTitle(t, { status_code: "in_progress", status_title: "In Progress" }),
    ).toBe("In Progress");
    expect(
      assessmentTypeTitle(t, { type_code: "360", type_title: "360° Assessment" }),
    ).toBe("360° Assessment");
  });

  it("falls back to the payload title for unknown codes", () => {
    expect(
      assessmentStatusTitle(t, { status_code: "archived", status_title: "Archived" }),
    ).toBe("Archived");
  });
});

describe("reference catalog invariants", () => {
  const keySets = (node: Catalog, prefix = ""): string[] =>
    Object.entries(node).flatMap(([k, v]) =>
      v && typeof v === "object"
        ? keySets(v as Catalog, `${prefix}${k}.`)
        : [`${prefix}${k}`],
    );

  it("pins the en catalog byte-exactly to the backend seed strings", () => {
    // Byte-for-byte mirror of the seed migrations (aca1005a8e45,
    // c3fc300775f8, cr12s1y2s3t4c5, asr1a1b2c3d4e5) and the pre-i18n
    // scale-levels shim. Any edit here changes rendered English output —
    // that's the F5 invariant this test exists to protect.
    expect(en.reference).toEqual({
      dictionary: {
        grade: {
          junior: { label: "Junior", description: "Entry-level position" },
          middle: { label: "Middle", description: "Mid-level position" },
          senior: { label: "Senior", description: "Senior-level position" },
          lead: { label: "Lead", description: "Team lead position" },
          principal: { label: "Principal", description: "Principal/Staff level" },
        },
        specialization: {
          backend_developer: { label: "Backend Developer" },
          frontend_developer: { label: "Frontend Developer" },
          qa_engineer: { label: "QA Engineer" },
          product_manager: { label: "Product Manager" },
          designer: { label: "Designer" },
          data_scientist: { label: "Data Scientist" },
          devops_engineer: { label: "DevOps Engineer" },
        },
        competence_type: {
          hard_skill: {
            label: "Hard skill",
            description: "Technical and professional skills",
          },
          soft_skill: {
            label: "Soft skill",
            description: "Interpersonal and communication skills",
          },
          unique_skill: {
            label: "Unique skill",
            description: "Domain-specific unique skills",
          },
        },
      },
      assessmentStatus: {
        draft: "Draft",
        sent: "Sent",
        in_progress: "In Progress",
        on_review: "On Review",
        summarizing: "Summarizing",
        await_result: "Awaiting Result",
        done: "Done",
        cancelled: "Cancelled",
      },
      assessmentType: {
        self: "Self Assessment",
        "180": "180° Assessment",
        "360": "360° Assessment",
      },
      skillLevel: {
        basic: "Basic",
        intermediate: "Intermediate",
        advanced: "Advanced",
      },
      scaleLevel: {
        below_expectations: "Below expectations",
        meets_with_growth: "Meets expectations with growth areas",
        fully_meets: "Fully meets expectations",
      },
      scaleOption: {
        na: { label: "N/A", description: "Not applicable or not observed" },
        below: {
          label: "Below Expectations",
          description: "Does not meet the expected level",
        },
        meets: {
          label: "Meets Expectations",
          description: "Meets the expected level",
        },
        exceeds: {
          label: "Exceeds Expectations",
          description: "Exceeds the expected level",
        },
        outstanding: {
          label: "Outstanding",
          description: "Significantly exceeds expectations",
        },
      },
      scale: {
        standard_5point: {
          label: "Standard 5-Point Scale",
          description: "Default assessment scoring scale",
        },
      },
    });
  });

  it("keeps en/de reference parity", () => {
    expect(keySets(de.reference).sort()).toEqual(keySets(en.reference).sort());
  });
});
