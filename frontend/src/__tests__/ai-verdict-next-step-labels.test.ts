// HRP-550 — one label source for every verdict surface, and a real ICU
// plural on the invitation toast.
//
// Before this ticket the AI Insights pill, the run history and the
// next-step line printed the raw wire code with underscores swapped for
// spaces while the AI VERDICT column (HRP-493) was already translated, so
// the same run read differently depending on where you looked at it.

import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  AI_NEXT_STEP_LABEL_KEYS,
  AI_VERDICT_LABEL_KEYS,
  aiNextStepLabel,
  aiVerdictLabel,
  type AiNextStep,
  type AiVerdict,
} from "@/lib/recruitment-types";

type Catalog = { recruitment: Record<string, string> };

// Catalogs are discovered, never hardcoded: ru.json is enterprise-only and
// does not exist in the public repo, so a fixed ["en","de","ru"] list would
// fail collection there with ENOENT. Same approach as
// i18n-catalog-parity.test.ts — the guard covers whatever set ships.
const MESSAGES_DIR = resolve(__dirname, "../../messages");

const CATALOGS: Record<string, Catalog> = Object.fromEntries(
  readdirSync(MESSAGES_DIR)
    .filter((file) => file.endsWith(".json"))
    .sort()
    .map((file) => [
      basename(file, ".json"),
      JSON.parse(readFileSync(resolve(MESSAGES_DIR, file), "utf8")) as Catalog,
    ]),
);

const EN = CATALOGS.en;
const t = (key: string) => EN.recruitment[key] ?? key;

describe("Verdict labels (HRP-550)", () => {
  it("resolves every verdict through the shared key map", () => {
    const expected: Record<AiVerdict, string> = {
      pending: "Pending",
      recommended: "Recommended",
      needs_check: "Needs check",
      not_recommended: "Not recommended",
    };
    for (const [verdict, label] of Object.entries(expected)) {
      expect(aiVerdictLabel(t, verdict)).toBe(label);
    }
  });

  it("falls back to the raw code for a verdict the UI does not know", () => {
    expect(aiVerdictLabel(t, "escalated")).toBe("escalated");
  });

  it("carries every verdict key in all shipped catalogs", () => {
    for (const [locale, catalog] of Object.entries(CATALOGS)) {
      for (const key of Object.values(AI_VERDICT_LABEL_KEYS)) {
        expect(catalog.recruitment[key], `${locale}.${key}`).toBeTruthy();
      }
    }
  });
});

describe("Next-step labels (HRP-550)", () => {
  // Mirrors the backend Literal in prompts_interview.py — if a code is
  // added there, this list and the catalogs have to grow with it.
  const CODES: AiNextStep[] = [
    "schedule_interview",
    "second_interview",
    "final_decision",
    "reject",
  ];

  it("translates every code the analysis prompt can return", () => {
    for (const code of CODES) {
      const label = aiNextStepLabel(t, code);
      expect(label).not.toBe(code);
      expect(label).not.toContain("_");
    }
  });

  it("falls back to the raw code for an unknown recommendation", () => {
    expect(aiNextStepLabel(t, "hold_for_budget")).toBe("hold_for_budget");
  });

  it("carries every next-step key in all shipped catalogs", () => {
    for (const [locale, catalog] of Object.entries(CATALOGS)) {
      for (const code of CODES) {
        const key = AI_NEXT_STEP_LABEL_KEYS[code];
        expect(catalog.recruitment[key], `${locale}.${key}`).toBeTruthy();
      }
    }
  });
});

describe("Invitation toast plural (HRP-550)", () => {
  it("is a real ICU plural in every catalog, not a '(s)' suffix", () => {
    for (const [locale, catalog] of Object.entries(CATALOGS)) {
      const message = catalog.recruitment.managerAssessmentInvitesSent;
      expect(message, locale).toContain("{count, plural,");
      expect(message, locale).not.toContain("(s)");
      expect(message, locale).not.toContain("(en)");
    }
  });
});
