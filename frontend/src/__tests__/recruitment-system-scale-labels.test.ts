// HRP-1023: the recruitment scale every tenant is seeded with ("Standard 1-4")
// reads in the interface language - its name, description and level labels -
// while a tenant's own scale renders exactly as typed. The seeded English
// text is the join key (backend manager_assessment_service.DEFAULT_SCALE_*).

import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import {
  localizeRecruitmentScaleLevels,
  recruitmentScaleDescription,
  recruitmentScaleName,
  type ReferenceTranslator,
} from "@/lib/reference-labels";

const MESSAGES_DIR = resolve(__dirname, "../../messages");
const CATALOGS: [string, Record<string, unknown>][] = readdirSync(MESSAGES_DIR)
  .filter((file) => file.endsWith(".json"))
  .map((file) => [
    basename(file, ".json"),
    JSON.parse(readFileSync(resolve(MESSAGES_DIR, file), "utf8")),
  ]);

const tFor = (locale: string, messages: Record<string, unknown>) =>
  createTranslator({ locale, messages, namespace: "reference" }) as unknown as ReferenceTranslator;

// The seed, byte for byte.
const SEEDED = [
  { value: 1, label: "Not suitable", description: "Cannot perform required tasks", weight: 0 },
  { value: 2, label: "Below expectations", description: "Significant gaps", weight: 33 },
  { value: 3, label: "Meets expectations", description: "Acceptable level", weight: 66 },
  { value: 4, label: "Exceeds expectations", description: "Top performer", weight: 100 },
];

describe("the shipped recruitment scale follows the interface language (HRP-1023)", () => {
  it("reads in English exactly as seeded", () => {
    const en = tFor("en", Object.fromEntries(CATALOGS).en as Record<string, unknown>);
    expect(recruitmentScaleName(en, "Standard 1-4")).toBe("Standard 1-4");
    expect(recruitmentScaleDescription(en, "Default scale shipped with HRPulsar.")).toBe(
      "Default scale shipped with HRPulsar.",
    );
    expect(localizeRecruitmentScaleLevels(en, SEEDED)).toEqual(SEEDED);
  });

  it("is translated in every other catalog", () => {
    for (const [locale, messages] of CATALOGS) {
      if (locale === "en") continue;
      const t = tFor(locale, messages);
      expect(recruitmentScaleName(t, "Standard 1-4"), locale).not.toBe("Standard 1-4");
      expect(
        recruitmentScaleDescription(t, "Default scale shipped with HRPulsar."),
        locale,
      ).not.toBe("Default scale shipped with HRPulsar.");
      const levels = localizeRecruitmentScaleLevels(t, SEEDED);
      levels.forEach((l, i) => {
        expect(l.label, `${locale} ${l.value}`).not.toBe(SEEDED[i].label);
        expect(l.description, `${locale} ${l.value}`).not.toBe(SEEDED[i].description);
        // Only the words change: the score and its weight are the data.
        expect([l.value, l.weight]).toEqual([SEEDED[i].value, SEEDED[i].weight]);
      });
    }
  });

  it("leaves a tenant's own scale as typed", () => {
    const [, messages] = CATALOGS.find(([l]) => l === "de")!;
    const de = tFor("de", messages);
    expect(recruitmentScaleName(de, "Our scale")).toBe("Our scale");
    expect(recruitmentScaleDescription(de, "Ours")).toBe("Ours");
    // One relabelled level makes the set the tenant's: nothing translates.
    const edited = SEEDED.map((l) => (l.value === 3 ? { ...l, label: "Solid" } : l));
    expect(localizeRecruitmentScaleLevels(de, edited)).toEqual(edited);
    // A level description the tenant rewrote stays theirs.
    const described = SEEDED.map((l) => (l.value === 4 ? { ...l, description: "Star" } : l));
    expect(localizeRecruitmentScaleLevels(de, described)[3].description).toBe("Star");
  });
});
