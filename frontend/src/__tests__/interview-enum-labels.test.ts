// HRP-579 (a): the interview page still printed raw wire codes — the
// analysis verdict, the process-finding / red-flag types (capitalized,
// underscores intact) and the question-set generation mode — the same
// leak HRP-550 fixed on the AI Insights surfaces one screen over.
//
// Review fix: the enum values below are pinned to the *backend* literals
// (prompts_interview.py / models.py), not iterated from the frontend
// maps — a map keyed on a vocabulary the backend never emits must fail
// here, not render dead UI.

import { readdirSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  AI_VERDICT_LABEL_KEYS,
  PROCESS_FINDING_LABEL_KEYS,
  QUESTION_SET_GENERATION_MODE_LABEL_KEYS,
  RED_FLAG_LABEL_KEYS,
  aiVerdictLabel,
  processFindingLabel,
  questionSetGenerationModeLabel,
  redFlagLabel,
} from "@/lib/recruitment-types";

// Backend ``Verdict`` Literal (prompts_interview.py) minus ``pending``,
// which only ever lives on the DB row default.
const BACKEND_VERDICTS = ["recommended", "needs_check", "not_recommended"];
// Backend ``ProcessFinding.finding_type`` Literal.
const BACKEND_PROCESS_FINDINGS = [
  "bias",
  "leading_question",
  "emotional_pressure",
  "overloaded_question",
  "too_detailed",
];
// Backend ``RedFlag.flag_type`` Literal.
const BACKEND_RED_FLAGS = [
  "contradiction",
  "resume_inconsistency",
  "evasion",
  "exaggeration_risk",
];
// Backend ``InterviewQuestionSet.generation_mode`` (models.py).
const BACKEND_GENERATION_MODES = [
  "initial",
  "regenerated",
  "dynamic_next",
  "manual",
];

type Catalog = { recruitment: Record<string, string> };

// Catalogs are discovered, never hardcoded: ru.json is enterprise-only and
// is absent from the public repo (same approach as the HRP-550 test).
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

const t = (key: string) => CATALOGS.en.recruitment[key] ?? key;

const ALL_KEYS = [
  ...BACKEND_VERDICTS.map((code) => AI_VERDICT_LABEL_KEYS[code as never]),
  ...BACKEND_PROCESS_FINDINGS.map(
    (code) => PROCESS_FINDING_LABEL_KEYS[code as never],
  ),
  ...BACKEND_RED_FLAGS.map((code) => RED_FLAG_LABEL_KEYS[code as never]),
  ...BACKEND_GENERATION_MODES.map(
    (code) => QUESTION_SET_GENERATION_MODE_LABEL_KEYS[code as never],
  ),
];

describe("Interview enum labels (HRP-579)", () => {
  it("translates every backend verdict code", () => {
    for (const code of BACKEND_VERDICTS) {
      const label = aiVerdictLabel(t, code);
      expect(label).toBe(CATALOGS.en.recruitment[AI_VERDICT_LABEL_KEYS[code as never]]);
      expect(label).not.toBe(code);
      expect(label).not.toContain("_");
    }
  });

  it("translates every backend process-finding code", () => {
    for (const code of BACKEND_PROCESS_FINDINGS) {
      const label = processFindingLabel(t, code);
      expect(label).toBe(
        CATALOGS.en.recruitment[PROCESS_FINDING_LABEL_KEYS[code as never]],
      );
      expect(label).not.toContain("_");
    }
  });

  it("translates every backend red-flag code", () => {
    for (const code of BACKEND_RED_FLAGS) {
      const label = redFlagLabel(t, code);
      expect(label).toBe(
        CATALOGS.en.recruitment[RED_FLAG_LABEL_KEYS[code as never]],
      );
      expect(label).not.toContain("_");
    }
  });

  it("translates every backend generation mode", () => {
    for (const code of BACKEND_GENERATION_MODES) {
      const label = questionSetGenerationModeLabel(t, code);
      expect(label).toBe(
        CATALOGS.en.recruitment[
          QUESTION_SET_GENERATION_MODE_LABEL_KEYS[code as never]
        ],
      );
      expect(label).not.toContain("_");
    }
  });

  it("de-slugs an unknown code instead of printing the wire form", () => {
    expect(processFindingLabel(t, "future_finding")).toBe("future finding");
    expect(redFlagLabel(t, "future_flag")).toBe("future flag");
    expect(questionSetGenerationModeLabel(t, "future_mode")).toBe("future mode");
  });

  it("has every key in every catalog", () => {
    for (const [locale, catalog] of Object.entries(CATALOGS)) {
      for (const key of ALL_KEYS) {
        expect(
          catalog.recruitment[key],
          `${key} missing from ${locale}.json`,
        ).toBeTruthy();
      }
    }
  });

  it("renders the surfaces through the helpers, not through string munging", () => {
    const analysis = readFileSync(
      resolve(__dirname, "../components/recruitment/interview-analysis.tsx"),
      "utf8",
    );
    expect(analysis).toContain("aiVerdictLabel(t, analysis.verdict)");
    expect(analysis).toContain("processFindingLabel(t, f.finding_type)");
    expect(analysis).toContain("redFlagLabel(t, f.flag_type)");
    expect(analysis).not.toContain("capitalize");

    const questionSets = readFileSync(
      resolve(
        __dirname,
        "../components/recruitment/interview-question-sets.tsx",
      ),
      "utf8",
    );
    expect(questionSets).toContain("questionSetGenerationModeLabel(");
    expect(questionSets).not.toContain("generation_mode.replace(");
  });
});
